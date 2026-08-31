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
}

# Editing variants take a reference image and have their own classes; they stay
# on the subprocess path until they get the same treatment.
UNSUPPORTED_INPROCESS = {"mflux-generate-kontext"}


def can_run_in_process(cli: str) -> bool:
    return cli in _VARIANTS


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

    def _build(self, cli: str, model_path: str, quantize: int | None):
        module_name, class_name, factory = _VARIANTS[cli]
        module = __import__(module_name, fromlist=[class_name])
        cls = getattr(module, class_name)

        from mflux.models.common.config import ModelConfig

        config = getattr(ModelConfig, factory)()
        kwargs: dict[str, Any] = {"model_config": config}
        if quantize:
            kwargs["quantize"] = quantize
        # A local directory is passed as model_path; without it mflux resolves
        # the model from Hugging Face, which defeats running offline.
        if model_path:
            kwargs["model_path"] = model_path
        return cls(**kwargs)

    def generate(
        self, *, cli: str, model_path: str, prompt: str, seed: int,
        steps: int, width: int, height: int, guidance: float,
        negative_prompt: str = "", quantize: int | None = None,
        on_step: Callable[[int], None] | None = None,
        out_path: str | Path,
    ) -> str:
        if cli not in _VARIANTS:
            raise ValueError(f"{cli} has no in-process path")

        key = (cli, model_path, quantize)
        if self._key != key:
            self.unload()
            self._model = self._build(cli, model_path, quantize)
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
