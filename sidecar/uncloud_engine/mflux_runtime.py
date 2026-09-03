"""Keep an mflux model resident between generations.

Previously every image spawned `mflux-generate-*` as a subprocess, which meant
loading twenty-two gigabytes of weights, rendering, and throwing them away —
per image. The "first run loads ~22GB" note in the UI was not describing a
first run; it was describing every run.

mflux exposes the same models as Python classes, so an instance can be built
once and reused. Loading stays slow the first time and is then free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

# CLI name -> (module, class, ModelConfig factory). The CLI names come from the
# catalog, which is how a model already declares which variant it needs.
_VARIANTS: dict[str, tuple[str, str, str]] = {
    "mflux-generate-krea2": ("mflux.models.krea2", "Krea2", "krea2"),
    "mflux-generate": ("mflux.models.flux.variants.txt2img.flux", "Flux1", "dev"),
    "mflux-generate-flux2-klein": ("mflux.models.flux2", "Flux2Klein", "flux2_klein_9b"),
    "mflux-generate-z-image": ("mflux.models.z_image", "ZImageTurbo", "z_image_turbo"),
}

# Editing variants take a reference image and have their own classes; they stay
# on the subprocess path until they get the same treatment.
UNSUPPORTED_INPROCESS = {"mflux-generate-kontext"}


def can_run_in_process(cli: str) -> bool:
    return cli in _VARIANTS


def _tile_flux2_vae_decode() -> None:
    """Decode FLUX.2 images in tiles, because the decode is the memory peak.

    Not the transformer, as you would assume. Denoising Klein 9B at 1024x1024
    measured 12.1GB resident and steady; the run still peaked at 22.3GB, all of
    it after the last step. At 1024x1536 that peak is 27.3GB on a 25.8GB
    machine, so the decode is what pushes a working laptop into swap.

    mflux can tile it — VAEUtil.decode takes a TilingConfig — but the FLUX.2
    text-to-image path never passes one: it calls decode_packed_latents with
    the latents alone, while the model's own tiling_config is read only by the
    edit variant. Bind the default config to the call so the txt2img path gets
    it too, leaving an explicit config free to override.
    """
    try:
        from mflux.models.common.vae.tiling_config import TilingConfig
        from mflux.models.flux2.model.flux2_vae.vae import Flux2VAE
    except Exception:  # noqa: BLE001 - a newer mflux may have moved these
        return
    if getattr(Flux2VAE.decode_packed_latents, "_uncloud_tiled", False):
        return

    inner = Flux2VAE.decode_packed_latents
    default = TilingConfig()

    def decode_packed_latents(self, packed_latents, tiling_config=None):
        return inner(self, packed_latents, tiling_config or default)

    decode_packed_latents._uncloud_tiled = True
    Flux2VAE.decode_packed_latents = decode_packed_latents


_tile_flux2_vae_decode()


def _fix_lokr_dims_for_odd_bit_widths() -> None:
    """Let a LoKr adapter apply to a 6-bit checkpoint.

    MLX packs quantised weights into uint32 words, so a linear layer's stored
    width is ceil(in_features * bits / 32) and the original has to be recovered
    to check an adapter against it. mflux recovers it with

        input_dims *= 32 // linear.bits

    which is exact only when the bit width divides 32. At 6-bit, 32 // 6 is 5
    rather than 5.333, and a 16384-wide layer is read as 15360 — so every LoKr
    is rejected for a shape mismatch that is arithmetic, not weights. Multiply
    before dividing and it is exact at every width: 4 and 8 are unchanged, and
    3, 5 and 6 stop lying.
    """
    try:
        from mlx import nn
        from mflux.models.common.lora.layer.linear_lokr_layer import LoKrLinear
    except Exception:  # noqa: BLE001 - a newer mflux may have moved this
        return
    if getattr(LoKrLinear.from_linear, "_uncloud_exact_dims", False):
        return

    inner = LoKrLinear.from_linear

    def from_linear(linear, lokr_w1, lokr_w2, dora_scale=None, scale=1.0):
        if isinstance(linear, nn.QuantizedLinear) and 32 % linear.bits:
            out_dims, packed = linear.weight.shape
            return LoKrLinear(
                linear=linear, output_dims=out_dims,
                input_dims=packed * 32 // linear.bits,
                lokr_w1=lokr_w1, lokr_w2=lokr_w2,
                dora_scale=dora_scale, scale=scale,
            )
        return inner(linear, lokr_w1, lokr_w2, dora_scale, scale)

    from_linear._uncloud_exact_dims = True
    LoKrLinear.from_linear = staticmethod(from_linear)


_fix_lokr_dims_for_odd_bit_widths()


class _StepProgress:
    """mflux's in-loop callback protocol, used only to report step counts."""

    def __init__(self, on_step: Callable[[int], None]) -> None:
        self._on_step = on_step

    def call_in_loop(self, t, seed, prompt, latents, config, time_steps) -> None:  # noqa: ANN001
        try:
            self._on_step(int(t) + 1)
        except Exception:  # noqa: BLE001 - progress must never break a render
            pass


class MfluxRuntime:
    """One loaded model at a time, keyed by (variant, path, quantisation)."""

    def __init__(self) -> None:
        self._model: Any = None
        self._key: tuple | None = None

    @property
    def loaded(self) -> str | None:
        return None if self._key is None else f"{self._key[0]} @ {self._key[1]}"

    def unload(self) -> None:
        self._model = None
        self._key = None
        try:
            import gc

            import mlx.core as mx

            gc.collect()
            mx.clear_cache()
        except Exception:  # noqa: BLE001
            pass

    def _build(self, cli: str, model_path: str, quantize: int | None,
               base: str | None = None,
               lora_paths: tuple[str, ...] = (), lora_scales: tuple[float, ...] = ()):
        module_name, class_name, factory = _VARIANTS[cli]
        module = __import__(module_name, fromlist=[class_name])
        cls = getattr(module, class_name)

        from mflux.models.common.config import ModelConfig

        # One CLI can cover several sizes — Klein ships as both 4B and 9B, and
        # loading a 4B checkpoint against the 9B config fails on shape. A
        # pre-quantised checkpoint records which base it came from.
        factory = base or factory
        if not hasattr(ModelConfig, factory):
            raise RuntimeError(
                f"mflux does not know a base model called '{factory}'."
            )
        config = getattr(ModelConfig, factory)()
        kwargs: dict[str, Any] = {"model_config": config}
        if quantize:
            kwargs["quantize"] = quantize
        # A local directory is passed as model_path; without it mflux resolves
        # the model from Hugging Face, which defeats running offline.
        if model_path:
            kwargs["model_path"] = model_path
        if lora_paths:
            # mflux applies adapters after the weights are in place, so this
            # works on a checkpoint that is already quantised — no second copy.
            kwargs["lora_paths"] = list(lora_paths)
            kwargs["lora_scales"] = list(lora_scales) or [1.0] * len(lora_paths)
        return cls(**kwargs)

    def generate(
        self, *, cli: str, model_path: str, prompt: str, seed: int,
        steps: int, width: int, height: int, guidance: float,
        negative_prompt: str = "", quantize: int | None = None,
        base: str | None = None,
        lora_paths: list[str] | None = None,
        lora_scales: list[float] | None = None,
        on_step: Callable[[int], None] | None = None,
        out_path: str | Path,
    ) -> str:
        if cli not in _VARIANTS:
            raise ValueError(f"{cli} has no in-process path")

        loras = tuple(lora_paths or ())
        scales = tuple(lora_scales or ())
        # Adapters are part of the identity: the same checkpoint with different
        # adapters is a different model and must not be served from the cache.
        key = (cli, model_path, quantize, base, loras, scales)
        if self._key != key:
            self.unload()
            self._model = self._build(cli, model_path, quantize, base, loras, scales)
            self._key = key

        if on_step is not None:
            try:
                from mflux.callbacks.callback_registry import CallbackRegistry

                registry = getattr(self._model, "callbacks", None)
                if isinstance(registry, CallbackRegistry):
                    registry.register(_StepProgress(on_step))
            except Exception:  # noqa: BLE001 - progress is optional
                pass

        kwargs: dict[str, Any] = {
            "seed": int(seed),
            "prompt": prompt,
            "num_inference_steps": int(steps),
            "width": int(width),
            "height": int(height),
            "guidance": float(guidance),
        }
        if negative_prompt:
            kwargs["negative_prompt"] = negative_prompt

        image = self._model.generate_image(**kwargs)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        image.save(str(out))
        return str(out)


mflux_runtime = MfluxRuntime()
