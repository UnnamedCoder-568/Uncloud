"""FLUX.2 Klein pipelines assembled from loose parts.

A diffusers pipeline on disk is a folder of component subfolders. What people
actually download for FLUX.2 Klein is rarely that shape: the community ships a
single fine-tuned transformer as one `.safetensors`, and you are expected to
bring the scheduler, tokenizer, VAE and text encoder from the official release.
Folders like that carry a small JSON manifest naming the pieces.

Handing such a folder to `from_pretrained` fails with

    no file named scheduler_config.json found in directory ...

which is true and useless — the scheduler was never supposed to be there. This
module reads the manifest, borrows the missing components from a complete
pipeline elsewhere in the models folder, and runs generation in two phases.

Two phases because the parts do not fit at once. Klein's text encoder is an 8B
Qwen3 (16GB in bf16) and its transformer is 9B (18GB); on a 24GB machine only
one can be resident. So the prompt is encoded first, the encoder is dropped, and
only then is the transformer loaded. Encoding is the cheaper half to repeat, so
the transformer is what stays resident between generations — and prompt
embeddings are cached, which makes re-rolling the same prompt on a new seed skip
the encoder entirely.
"""

from __future__ import annotations

import gc
import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Filenames the manifest is known by. The second form is per-model rather than
# per-folder, so it is matched as a suffix.
_MANIFEST_NAME = "astro-image-profile.json"
_MANIFEST_SUFFIX = ".astro-image.json"

# How many prompt encodings to remember. Each is roughly 12MB (512 tokens x 3
# hidden layers x 4096), so this is megabytes against the minute of work it
# saves when the same prompt is rendered again at a different seed.
_EMBED_CACHE = 8

# Converted weights are cached here, on the internal disk, because that is the
# whole point — see _cached_load.
CACHE_ROOT = Path.home() / ".uncloud" / "cache" / "flux2"

# Which of the encoder's hidden layers FLUX.2 Klein actually reads. Everything
# above the last one is dead weight — see _truncate_encoder.
ENCODER_LAYERS = (9, 18, 27)

# Bumped whenever what gets written changes shape, so a stale cache from an
# older build is rebuilt rather than loaded into the wrong architecture.
_CACHE_VERSION = 2


@dataclass
class Flux2Profile:
    root: Path
    name: str
    transformer: Path
    base: Path | None = None            # complete pipeline lending the rest
    text_encoder: Path | None = None    # .gguf file or a component folder
    steps: int | None = None
    guidance: float | None = None
    is_distilled: bool = True
    missing: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.base is not None and not self.missing

    @property
    def size_gb(self) -> float:
        total = self.transformer.stat().st_size
        if self.text_encoder and self.text_encoder.is_file():
            total += self.text_encoder.stat().st_size
        return total / (1024 ** 3)

    def note(self) -> str:
        if self.ready:
            borrowed = self.base.name if self.base else "?"
            encoder = (
                f", {self.text_encoder.name} as its text encoder"
                if self.text_encoder else ""
            )
            return (
                f"Assembled at load time: {self.transformer.name} as the diffusion "
                f"transformer{encoder}, with the scheduler, tokenizer and VAE "
                f"borrowed from “{borrowed}”."
            )
        if self.base is None:
            return (
                "Needs a complete FLUX.2 Klein diffusers pipeline in the same "
                "models folder to borrow a scheduler, tokenizer and VAE from — "
                "none was found. Download “FLUX.2 Klein 9B” from the Models tab."
            )
        return "; ".join(self.missing)


# --------------------------------------------------------------- discovery

def _manifest_path(root: Path) -> Path | None:
    direct = root / _MANIFEST_NAME
    if direct.is_file():
        return direct
    try:
        for child in root.iterdir():
            if child.is_file() and child.name.endswith(_MANIFEST_SUFFIX):
                return child
    except OSError:
        pass
    return None


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def is_complete_pipeline(path: Path) -> bool:
    """A folder `from_pretrained` could actually load a Flux2 pipeline from."""
    index = path / "model_index.json"
    if not index.is_file():
        return False
    if not str(_load_json(index).get("_class_name", "")).startswith("Flux2"):
        return False
    return all(
        (path / sub / name).is_file()
        for sub, name in (
            ("transformer", "config.json"),
            ("scheduler", "scheduler_config.json"),
            ("vae", "config.json"),
            ("tokenizer", "tokenizer_config.json"),
        )
    )


def _find_base(root: Path, declared: str | None, models_dir: Path | None) -> Path | None:
    if declared:
        candidate = (root / declared).resolve()
        if is_complete_pipeline(candidate):
            return candidate
    # Siblings first — a manifest folder is normally kept beside the release it
    # was cut from — then a bounded walk of the models folder.
    seen: set[Path] = set()
    for parent, depth in ((root.parent, 1), (models_dir, 3)):
        if parent is None or not parent.is_dir():
            continue
        stack = [(parent, 0)]
        while stack:
            current, level = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            if current != root and is_complete_pipeline(current):
                return current
            if level >= depth:
                continue
            try:
                stack.extend(
                    (c, level + 1) for c in current.iterdir()
                    if c.is_dir() and not c.name.startswith(".")
                )
            except OSError:
                pass
    return None


def _largest_safetensors(root: Path) -> Path | None:
    files = [f for f in root.glob("*.safetensors") if f.is_file()]
    return max(files, key=lambda f: f.stat().st_size) if files else None


def _resolve(root: Path, rel: str | None) -> Path | None:
    if not rel:
        return None
    path = (root / rel)
    return path if path.exists() else None


def read_profile(root: Path, models_dir: Path | None = None) -> Flux2Profile | None:
    """Recognise a folder that names its parts instead of shipping a pipeline.

    Returns None for anything that is a normal model — a loadable pipeline, or a
    folder with no manifest and no Flux2 `model_index.json`.
    """
    manifest_file = _manifest_path(root)
    index = root / "model_index.json"
    index_data = _load_json(index) if index.is_file() else {}
    claims_flux2 = str(index_data.get("_class_name", "")).startswith("Flux2")

    if manifest_file is None and not claims_flux2:
        return None
    if is_complete_pipeline(root):
        return None  # loads on its own; nothing to assemble

    data = _load_json(manifest_file) if manifest_file else {}

    # Two manifest shapes are in the wild: named sources, or a list of roles.
    artifacts = {
        str(a.get("role", "")): str(a.get("path", ""))
        for a in data.get("artifacts", []) if isinstance(a, dict)
    }
    transformer = (
        _resolve(root, data.get("transformerSource"))
        or _resolve(root, artifacts.get("diffusion-model"))
        or _largest_safetensors(root)
    )
    if transformer is None or not transformer.is_file():
        return None  # no weights here — not a model folder at all

    encoder = _resolve(root, data.get("textEncoderSource"))
    if encoder is not None and encoder.is_file() and encoder.suffix != ".gguf":
        # A loose fp8 checkpoint is not something transformers can load without
        # the config that went with it; the base pipeline's encoder is used
        # instead rather than failing at generate time.
        encoder = None
    if encoder is None:
        for gguf in sorted(root.glob("*/*.gguf")) + sorted(root.glob("*.gguf")):
            encoder = gguf
            break

    defaults = data.get("defaults") or {}
    base = _find_base(root, data.get("modelSource"), models_dir)

    profile = Flux2Profile(
        root=root,
        name=str(data.get("name") or root.name),
        transformer=transformer,
        base=base,
        text_encoder=encoder,
        steps=defaults.get("steps"),
        guidance=defaults.get("guidance"),
        is_distilled=bool(index_data.get("is_distilled", True)),
    )
    return profile


# ------------------------------------------------------------------ loading

def _dequantise_scaled_fp8(state: dict) -> dict:
    """Undo ComfyUI's scaled-fp8 packing.

    Those checkpoints store `w.weight` as float8_e4m3fn beside a scalar
    `w.weight_scale`, plus a `w.comfy_quant` byte string naming the format.
    diffusers' converter has never seen any of that, so the scale is applied
    here and the bookkeeping tensors are dropped.
    """
    import torch

    scales = {k for k in state if k.endswith(".weight_scale")}
    if not scales:
        return state

    for scale_key in scales:
        base_key = scale_key[: -len("_scale")]
        weight = state.get(base_key)
        if weight is None:
            continue
        state[base_key] = weight.to(torch.bfloat16) * state[scale_key].to(torch.bfloat16)
    for key in list(state):
        if key.endswith((".weight_scale", ".comfy_quant")):
            del state[key]
    return state


def _fingerprint(path: Path) -> str:
    """Identify a source file cheaply, so a replaced checkpoint invalidates."""
    st = path.stat()
    raw = f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _free_bytes(path: Path) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def _cached_load(kind: str, source: Path, build, load):
    """Load converted weights from a local cache, building it on first use.

    Neither of these models is stored in a form torch can use directly. The
    transformer is fp8 in the original BFL key layout and has to be converted;
    the text encoder is a GGUF that gets dequantised tensor by tensor. That work
    was being redone on every generation with a new prompt — measured at 61s and
    64s — because the two do not fit in memory together, so loading one means
    dropping the other.

    Converting once and writing the result to the internal disk turns both into
    a plain safetensors read. It also loads better: safetensors is mmapped, so
    the weights are clean file-backed pages the system can drop and re-read at
    disk speed, rather than anonymous memory that has to go to swap.

    Failing to cache is never fatal — it just means the slow path, every time.
    """
    target = CACHE_ROOT / f"{kind}-v{_CACHE_VERSION}-{_fingerprint(source)}"
    if (target / "config.json").is_file():
        try:
            return load(target)
        except Exception:  # noqa: BLE001 - a corrupt cache must not be fatal
            shutil.rmtree(target, ignore_errors=True)

    model = build()

    try:
        CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        needed = sum(p.numel() * p.element_size() for p in model.parameters())
        # Leave real headroom: filling the boot disk to save a minute is a bad
        # trade, and the user did not ask for this file.
        if _free_bytes(CACHE_ROOT) > needed * 2:
            staging = CACHE_ROOT / f".{kind}-{os.getpid()}"
            shutil.rmtree(staging, ignore_errors=True)
            model.save_pretrained(staging)
            os.replace(staging, target)
    except Exception:  # noqa: BLE001 - the model is loaded; caching is a bonus
        shutil.rmtree(CACHE_ROOT / f".{kind}-{os.getpid()}", ignore_errors=True)
    return model


def cache_size_bytes() -> int:
    if not CACHE_ROOT.is_dir():
        return 0
    return sum(f.stat().st_size for f in CACHE_ROOT.rglob("*") if f.is_file())


def clear_cache() -> int:
    """Drop the converted-weight cache. Costs the conversion time again."""
    size = cache_size_bytes()
    shutil.rmtree(CACHE_ROOT, ignore_errors=True)
    return size


def _is_scaled_fp8(path: Path) -> bool:
    from safetensors import safe_open

    with safe_open(str(path), framework="pt") as f:
        return any(k.endswith(".weight_scale") for k in f.keys())


def _load_transformer(profile: Flux2Profile):
    import torch
    from diffusers import Flux2Transformer2DModel

    def build():
        # from_single_file reads the file itself, so hand it the path unless the
        # weights need unpacking first — reading 9GB twice costs half a minute.
        if _is_scaled_fp8(profile.transformer):
            from safetensors.torch import load_file

            source: Any = _dequantise_scaled_fp8(load_file(str(profile.transformer)))
        else:
            source = str(profile.transformer)

        model = Flux2Transformer2DModel.from_single_file(
            source, config=str(profile.base), subfolder="transformer",
            torch_dtype=torch.bfloat16, local_files_only=True,
        )
        del source
        gc.collect()
        return model

    return _cached_load(
        "transformer", profile.transformer, build,
        lambda d: Flux2Transformer2DModel.from_pretrained(
            str(d), torch_dtype=torch.bfloat16, local_files_only=True),
    )


def _truncate_encoder(model):
    """Throw away the part of the text encoder the pipeline never reads.

    Klein takes hidden states from layers 9, 18 and 27 of a 36-layer Qwen3, so
    layers 28 upward cannot affect the result, and the language-model head — a
    151936 x 4096 matrix, 1.2GB on its own — is never consulted at all. Loading
    them costs 4.5GB of memory on a machine that is already having to drop the
    image model to make room, and a 318 GFLOP matmul per prompt for an answer
    nobody looks at.

    Cutting them is exact, not an approximation: a transformer layer cannot
    influence the output of a layer beneath it.
    """
    keep = max(ENCODER_LAYERS) + 1
    base = getattr(model, "model", model)
    layers = getattr(base, "layers", None)
    if layers is None or len(layers) <= keep:
        return model
    base.layers = layers[:keep]
    base.config.num_hidden_layers = keep
    if hasattr(base.config, "layer_types"):
        base.config.layer_types = base.config.layer_types[:keep]
    # Return the bare model: the CausalLM wrapper exists only to run the head.
    return base


def _load_text_encoder(profile: Flux2Profile, override: str | None):
    import torch
    from transformers import AutoModelForCausalLM

    from transformers import AutoModel

    def read(path: Path):
        # The cache holds the truncated base model, so it reloads as one.
        return AutoModel.from_pretrained(
            str(path), dtype=torch.bfloat16, local_files_only=True)

    source = Path(override) if override else profile.text_encoder
    if source is not None and source.is_file() and source.suffix == ".gguf":
        return _cached_load(
            "text_encoder", source,
            lambda: _truncate_encoder(AutoModelForCausalLM.from_pretrained(
                str(source.parent), gguf_file=source.name,
                dtype=torch.bfloat16, local_files_only=True)),
            read,
        )

    folder = source if (source and source.is_dir()) else (profile.base / "text_encoder")
    # Already plain safetensors, but still worth trimming and caching: the
    # layers being dropped are a third of it.
    return _cached_load(
        "text_encoder", folder / "config.json",
        lambda: _truncate_encoder(AutoModelForCausalLM.from_pretrained(
            str(folder), dtype=torch.bfloat16, local_files_only=True)),
        read,
    )


def _load_tokenizer(profile: Flux2Profile):
    from transformers import AutoTokenizer

    for candidate in (profile.base / "tokenizer", profile.root / "text_encoder"):
        if (candidate / "tokenizer_config.json").is_file():
            return AutoTokenizer.from_pretrained(str(candidate), local_files_only=True)
    raise FileNotFoundError(
        f"No tokenizer found for {profile.name} — expected one in "
        f"{profile.base / 'tokenizer'}."
    )


def _device() -> str:
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _release() -> None:
    import torch

    gc.collect()
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()
    elif torch.cuda.is_available():
        torch.cuda.empty_cache()


class Flux2ProfileRuntime:
    """Keeps the denoising half of an assembled pipeline resident."""

    def __init__(self) -> None:
        self._pipe: Any = None
        self._key: tuple | None = None
        self._embeds: dict[tuple, Any] = {}

    @property
    def loaded(self) -> str | None:
        return self._key[0] if self._key else None

    @property
    def holding(self) -> bool:
        """True while anything is worth releasing — weights or cached prompts."""
        return self._pipe is not None or bool(self._embeds)

    def _drop_pipeline(self) -> None:
        self._pipe = None
        self._key = None
        _release()

    def unload(self) -> None:
        self._drop_pipeline()
        self._embeds.clear()

    def _encode(self, profile: Flux2Profile, prompt: str, override: str | None):
        import torch
        from diffusers import Flux2KleinPipeline

        key = (str(override or profile.text_encoder or profile.base), prompt)
        cached = self._embeds.get(key)
        if cached is not None:
            return cached

        # The transformer and the encoder cannot both be resident; the resident
        # one goes first so the encoder is not loaded into a full machine.
        self._drop_pipeline()

        tokenizer = _load_tokenizer(profile)
        encoder = _load_text_encoder(profile, override).to(_device())
        try:
            with torch.no_grad():
                embeds = Flux2KleinPipeline._get_qwen3_prompt_embeds(  # noqa: SLF001
                    text_encoder=encoder, tokenizer=tokenizer, prompt=[prompt],
                    dtype=torch.bfloat16, device=torch.device(_device()),
                )
            embeds = embeds.to("cpu")
        finally:
            del encoder
            _release()

        if len(self._embeds) >= _EMBED_CACHE:
            self._embeds.pop(next(iter(self._embeds)))
        self._embeds[key] = embeds
        return embeds

    def _pipeline(self, profile: Flux2Profile):
        key = (str(profile.transformer), str(profile.base))
        if self._pipe is not None and self._key == key:
            return self._pipe

        import torch
        from diffusers import (AutoencoderKLFlux2, Flux2KleinPipeline,
                               FlowMatchEulerDiscreteScheduler)

        self._drop_pipeline()

        transformer = _load_transformer(profile)
        vae = AutoencoderKLFlux2.from_pretrained(
            str(profile.base), subfolder="vae",
            torch_dtype=torch.bfloat16, local_files_only=True,
        )
        scheduler = FlowMatchEulerDiscreteScheduler.from_pretrained(
            str(profile.base), subfolder="scheduler", local_files_only=True,
        )
        pipe = Flux2KleinPipeline(
            scheduler=scheduler, vae=vae, text_encoder=None,
            tokenizer=_load_tokenizer(profile), transformer=transformer,
            is_distilled=profile.is_distilled,
        ).to(_device())

        self._pipe, self._key = pipe, key
        return pipe

    def generate(
        self, profile: Flux2Profile, *, prompt: str, steps: int, guidance: float,
        width: int, height: int, seed: int, out_path: Path,
        on_step: Callable[[int], None] | None = None,
        text_encoder_path: str | None = None,
    ) -> str:
        import torch

        if profile.base is None:
            raise RuntimeError(profile.note())

        embeds = self._encode(profile, prompt, text_encoder_path)
        pipe = self._pipeline(profile)
        embeds = embeds.to(_device())

        def callback(_pipe, step, _timestep, kwargs):
            if on_step:
                on_step(step + 1)
            return kwargs

        result = pipe(
            prompt_embeds=embeds, height=height, width=width,
            num_inference_steps=steps, guidance_scale=guidance,
            generator=torch.Generator("cpu").manual_seed(seed),
            callback_on_step_end=callback,
        )
        result.images[0].save(out_path)
        return str(out_path)


flux2_profile_runtime = Flux2ProfileRuntime()


def profile_for(model_path: str) -> Flux2Profile:
    """Re-read the manifest at generate time, so an edit takes effect at once."""
    from .config import settings

    profile = read_profile(Path(model_path), settings.models_dir)
    if profile is None:
        raise RuntimeError(
            f"{model_path} is no longer a FLUX.2 profile folder — its manifest "
            "or weights have moved."
        )
    return profile
