from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from pathlib import Path

from .catalog import get_catalog
from .flux2_profile import read_profile

DIFFUSION_HINTS = ("qwen-image", "hidream", "flux", "sdxl", "sd3", "stable-diffusion",
                   "video", "wan2", "cogvideo", "ltx", "krea", "klein", "pony")
STT_HINTS = ("whisper",)
TTS_HINTS = ("kokoro", "tts", "xtts", "piper", "bark")
VOICE_HINTS = STT_HINTS + TTS_HINTS


@dataclass
class LocalModel:
    id: str
    name: str
    category: str
    engine: str
    path: str
    size_gb: float
    catalog_id: str | None = None
    tags: list[str] | None = None
    ready: bool = True
    note: str | None = None
    capabilities: list[str] | None = None
    # Generation settings the model itself asks for — a distilled checkpoint at
    # 25 steps is a minute of wasted work, so the picker follows this.
    defaults: dict | None = None
    # For locally-found MLX models: which mflux entry point runs it, and which
    # base model to configure it as. Catalog models carry this in the catalog.
    mflux_cli: str | None = None
    mflux_base: str | None = None
    # Adapters applied at load time. Baking them into a copy of the weights
    # would mean another 8-20GB on disk per variation.
    lora_paths: list[str] | None = None
    lora_scales: list[float] | None = None

    def to_dict(self) -> dict:
        defaults, defaults_source = self.defaults or {}, ''
        if self.category == 'image':
            from .image_defaults import resolve
            defaults, defaults_source = resolve(self)
        return {
            "id": self.id, "name": self.name, "category": self.category,
            "engine": self.engine, "path": self.path, "size_gb": round(self.size_gb, 2),
            "catalog_id": self.catalog_id, "tags": self.tags or [], "ready": self.ready,
            "note": self.note, "capabilities": self.capabilities or ["text2img"],
            "defaults": defaults, "defaults_source": defaults_source,
            "mflux_cli": self.mflux_cli, "mflux_base": self.mflux_base,
            "lora_paths": self.lora_paths or [], "lora_scales": self.lora_scales or [],
        }


def speech_engine(folder: Path) -> str | None:
    """Kokoro, Chatterbox or Bark, recognised by the files the folder holds."""
    from .core.speech.engines import recognise

    found = recognise(folder)
    return found.engine if found else None


def _dir_size_gb(path: Path) -> float:
    """Total bytes under a folder, following symlinked component directories.

    rglob does not descend into symlinked folders, and a model assembled by
    pointing at components from elsewhere — an 8-bit transformer beside a 4-bit
    encoder, say — is entirely symlinks. Reported as 0 GB it reads as broken.
    Real paths are tracked so a link back up the tree cannot loop.
    """
    import os

    total = 0
    seen: set[tuple[int, int]] = set()
    for root, dirs, files in os.walk(path, followlinks=True):
        try:
            st = os.stat(root)
        except OSError:
            continue
        key = (st.st_dev, st.st_ino)
        if key in seen:
            dirs[:] = []
            continue
        seen.add(key)
        for name in files:
            with contextlib.suppress(OSError):
                total += os.stat(os.path.join(root, name)).st_size
    return total / (1024 ** 3)


# Architectures a GGUF header can declare. Diffusion transformers and language
# models share the container format, so the name tells you nothing reliable.
_DIFFUSION_ARCHS = {"flux", "sd3", "sdxl", "stable-diffusion", "sd1", "unet"}
# Prefixes, not exact names: quantisers ship variants like qwen35 and gemma4
# that would otherwise fall through to guessing from the filename.
_LM_ARCH_PREFIXES = ("qwen", "llama", "mistral", "gemma", "phi", "granite",
                     "starcoder", "stablelm", "falcon", "bloom", "deci",
                     "nemotron", "minimax", "lfm", "mamba", "gpt")


def _gguf_architecture(path: Path) -> tuple[str | None, str | None]:
    """Read `general.architecture` and `general.name` from a GGUF header.

    Filenames lie. One of these files is called flux2-klein-9b-uncensored and
    is a Qwen3 text encoder, which classified by name lands in the image picker
    and fails the moment it is selected.

    This parses the key-value block by hand and stops as soon as both fields are
    found, which is within the first few entries. Using gguf.GGUFReader here
    instead cost twenty-four seconds across six files, because it materialises
    every value including the tokenizer vocabulary — hundreds of thousands of
    strings nobody asked for.
    """
    import struct

    # GGUF value type ids -> fixed byte width. Strings and arrays are variable.
    FIXED = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
    STRING, ARRAY = 8, 9

    try:
        with path.open("rb") as f:
            if f.read(4) != b"GGUF":
                return None, None
            struct.unpack("<I", f.read(4))[0]           # version
            f.read(8)                                    # tensor count
            n_kv = struct.unpack("<Q", f.read(8))[0]

            def read_str() -> str:
                n = struct.unpack("<Q", f.read(8))[0]
                if n > 1 << 20:                          # implausible: bail out
                    raise ValueError("oversized key")
                return f.read(n).decode("utf-8", "replace")

            def skip(vtype: int) -> None:
                if vtype in FIXED:
                    f.seek(FIXED[vtype], 1)
                elif vtype == STRING:
                    n = struct.unpack("<Q", f.read(8))[0]
                    f.seek(n, 1)
                elif vtype == ARRAY:
                    elem = struct.unpack("<I", f.read(4))[0]
                    count = struct.unpack("<Q", f.read(8))[0]
                    if elem in FIXED:
                        f.seek(FIXED[elem] * count, 1)   # one seek, not count reads
                    else:
                        for _ in range(count):
                            skip(elem)
                else:
                    raise ValueError(f"unknown GGUF value type {vtype}")

            arch = name = None
            # The fields we want sit at the front; scanning the whole table would
            # walk the vocabulary, which is the thing being avoided.
            for _ in range(min(n_kv, 64)):
                key = read_str()
                vtype = struct.unpack("<I", f.read(4))[0]
                if key == "general.architecture" and vtype == STRING:
                    arch = read_str().strip().lower()
                elif key == "general.name" and vtype == STRING:
                    name = read_str().strip()
                else:
                    skip(vtype)
                if arch and name:
                    break
            return arch, name
    except Exception:  # noqa: BLE001 - an unreadable header just falls back
        return None, None


def _classify_gguf(path: Path, models_dir: Path) -> tuple[str, str, str | None, bool]:
    """(category, engine, note, ready) for a .gguf file, from its header.

    Through Core's identifier, which reads the architecture rather than trusting
    the name. The table this replaced knew flux and sd*, so a Z-Image GGUF —
    architecture lumina2 — was filed as a chat model, and a Wan one was filed
    correctly only by luck of its filename, with a note claiming the header
    could not be read when it had been.

    A lone diffusion transformer is the one verdict this can overturn. Core can
    only see the file, and judges it unrunnable because it is: no VAE, no text
    encoder, no scheduler. Whether those exist elsewhere in the models folder is
    something only the folder knows — so it is asked here.
    """
    from .core.models import identify
    from .model_import import verdict

    identification = identify(path, sizes=False)
    v = verdict(identification)
    note = v.note or None
    if v.engine == "gguf-diffusion" and v.category == "image":
        from .gguf_diffusion import assembly_for

        assembly = assembly_for(path, identification.family or "", models_dir)
        return v.category, v.engine, assembly.note(), assembly.ready
    if identification.warnings and not note:
        note = identification.warnings[0]
    return v.category, v.engine, note, v.runnable


# A checkpoint written by `mflux-save` has no manifest at the root — just
# component folders of numbered shards — so it is recognised by that shape.
# The quantisation level is recorded in the shard index; the base model it was
# cut from is not, and mflux needs it (Klein ships as both 4B and 9B, and the
# wrong config fails on tensor shape). Uncloud writes that alongside.
MLX_MARKER = "uncloud-mlx.json"

_MLX_BASE_CLI = {
    "dev_kontext": "mflux-generate-kontext",
    "flux2_klein_9b": "mflux-generate-flux2-klein",
    "flux2_klein_9b_kv": "mflux-generate-flux2-klein",
    "flux2_klein_base_9b": "mflux-generate-flux2-klein",
    "flux2_klein_4b": "mflux-generate-flux2-klein",
    "flux2_klein_base_4b": "mflux-generate-flux2-klein",
    "krea2": "mflux-generate-krea2",
    "krea2_raw": "mflux-generate-krea2",
    "krea_dev": "mflux-generate-krea2",
    "z_image": "mflux-generate-z-image",
    "z_image_turbo": "mflux-generate-z-image",
}


@dataclass
class MlxCheckpoint:
    path: Path                       # folder that identifies this entry
    base: str | None
    quantize: int | None
    name: str
    defaults: dict | None = None
    weights: Path | None = None      # where the shards actually live
    lora_paths: list[str] | None = None
    lora_scales: list[float] | None = None

    @property
    def checkpoint(self) -> Path:
        return self.weights or self.path

    @property
    def cli(self) -> str | None:
        return _MLX_BASE_CLI.get(self.base or "")

    @property
    def ready(self) -> bool:
        from .budget import engine_runs_here

        return self.cli is not None and engine_runs_here("mflux")

    def note(self) -> str:
        from .budget import engine_runs_here

        bits = f"{self.quantize}-bit MLX" if self.quantize else "MLX"
        if not engine_runs_here("mflux"):
            # Model folders travel — copied between machines, or synced. Say
            # what this is rather than reporting it broken.
            return (f"An Apple Silicon checkpoint. {bits} weights run through "
                    f"mflux, which exists only on Apple Silicon, so this one "
                    f"cannot be loaded on this machine.")
        if self.ready:
            return (f"Pre-quantised {bits} checkpoint — loads in seconds and stays "
                    f"in memory, instead of being rebuilt for every prompt.")
        return (f"{bits} checkpoint, but nothing records which base model it was "
                f"cut from, so mflux cannot configure it. Add a {MLX_MARKER} "
                f'beside it with {{"base_model": "flux2_klein_9b"}} or similar.')


def _mlx_display_name(child: Path) -> str:
    """A folder called Quantized-Q8 says nothing about which model it is.

    Published checkpoints often sit in a subfolder named after the
    quantisation, under a folder named after the model. Fold the parent in when
    the name on its own would be meaningless in a picker.
    """
    generic = ("quantized", "q4", "q6", "q8", "4bit", "6bit", "8bit", "mlx", "model")
    if child.name.lower().replace("-", " ").replace("_", " ").split()[0] in generic:
        return f"{child.parent.name} ({child.name})"
    return child.name


def read_mlx_checkpoint(child: Path) -> MlxCheckpoint | None:
    """Recognise an MLX checkpoint, in any of the three shapes they arrive in.

    mflux-save writes the transformer into its own folder, but some published
    checkpoints leave its shards at the root beside vae/ and text_encoder/ —
    both are valid and both load.

    The third shape is a recipe: a folder holding nothing but a marker, naming
    a checkpoint elsewhere plus the adapters to apply on top. That is how a
    fine-tune gets its own entry in the picker without a second copy of the
    weights, which for these models is tens of gigabytes.
    """
    # Uncloud Studio writes its own marker in the same shape. A folder either
    # product set up is one either product can read.
    marker_data: dict = {}
    for marker in (child / MLX_MARKER, child / "adstudio-mlx.json"):
        if marker.is_file():
            try:
                marker_data = json.loads(marker.read_text())
                break
            except (OSError, ValueError):
                marker_data = {}

    weights = child
    declared = marker_data.get("checkpoint")
    if declared:
        candidate = (child / declared).resolve()
        if not candidate.is_dir():
            return None
        weights = candidate

    from .core.models.identify import mflux_index

    index = mflux_index(weights / "transformer") or mflux_index(weights)
    if index is None or not (weights / "vae").is_dir():
        return None
    quantize = None
    try:
        raw = (index.get("metadata") or {}).get("quantization_level")
        quantize = int(raw) if raw is not None else None
    except (ValueError, TypeError):
        pass

    base = marker_data.get("base_model")
    if not base:
        # Nothing records the base, but the tensors do: Core tells FLUX.2 Klein
        # 4B, 9B and Krea 2 apart by their block layout, on real checkpoints.
        from .core.models import identify

        derived = identify(weights, sizes=False)
        if derived.layout.value == "mflux-checkpoint" and derived.family and not derived.candidates:
            base = derived.family

    loras = [str((child / p).resolve() if not Path(p).is_absolute() else Path(p))
             for p in marker_data.get("lora_paths", [])]
    scales = marker_data.get("lora_scales") or [1.0] * len(loras)
    return MlxCheckpoint(
        path=child, base=base, quantize=quantize,
        name=marker_data.get("name") or _mlx_display_name(child),
        defaults=marker_data.get("defaults"),
        weights=weights if weights != child else None,
        lora_paths=loras or None,
        lora_scales=list(scales)[:len(loras)] or None,
    )


def _mlx_dir_engine(child: Path) -> tuple[str, str, str | None] | None:
    """Distinguish an mflux-loadable model from a self-contained MLX port.

    Some MLX repos ship their own inference code and expect to be run with it —
    config.json says library_name: mlx and the weights are a single transformer
    file beside a package of Python. mflux cannot load those, and handing one to
    it produces a stack trace about missing safetensors rather than anything a
    person can act on.
    """
    cfg = child / "config.json"
    if not cfg.is_file():
        return None
    try:
        import json

        data = json.loads(cfg.read_text())
    except (OSError, ValueError):
        return None

    if data.get("library_name") != "mlx":
        return None
    # Bundled inference code is the tell: a directory of Python beside the weights.
    bundled = [
        d for d in child.iterdir()
        if d.is_dir() and (d / "__init__.py").is_file()
    ]
    entry = any((child / f).is_file() for f in ("generate.py", "app.py"))
    if bundled or entry:
        base = data.get("base_model") or "its base model"
        return ("image", "mlx-port",
                f"Self-contained MLX port of {base} — ships its own inference code "
                "and cannot be run by mflux. Not supported yet.")
    return None


def scan_library(models_dir: Path) -> list[LocalModel]:
    from .config import settings
    hidden = set(settings.hidden_models)
    return [model for model in _scan_library(models_dir) if model.path not in hidden]


def _scan_library(models_dir: Path) -> list[LocalModel]:
    if not models_dir.exists():
        # Nothing to walk — but models imported from elsewhere are still
        # models. Returning early here hid every one of them on a machine whose
        # models folder had not been created yet.
        return sorted(_imported(models_dir, set()), key=lambda m: m.name.lower())

    catalog_by_repo = {e.repo: e for e in get_catalog()}
    found: list[LocalModel] = []
    seen_paths: set[str] = set()
    seen_dirs: set[str] = set()

    # 0. Directories named after a catalog id — these were downloaded through
    #    Astro itself, so trust the catalog's own metadata rather than sniffing.
    for entry in get_catalog():
        entry_dir = models_dir / entry.id
        if not entry_dir.is_dir() or not any(entry_dir.iterdir()):
            continue
        seen_dirs.add(str(entry_dir))
        # llama.cpp opens a .gguf file, never its folder. Only diffusers entries
        # set `single_file`, so every GGUF chat model downloaded from the
        # catalogue used to be listed as its folder and failed to load.
        if entry.files and (entry.single_file or entry.engine == "gguf"):
            target = entry_dir / entry.files[0]
            if not target.exists():
                continue
            path_str, size_gb = str(target), target.stat().st_size / (1024 ** 3)
        else:
            path_str, size_gb = str(entry_dir), _dir_size_gb(entry_dir)
        seen_paths.add(path_str)
        found.append(LocalModel(
            id=f"local:{path_str}", name=entry.name, category=entry.category,
            engine=entry.engine, path=path_str, size_gb=size_gb,
            catalog_id=entry.id, tags=entry.tags, note=entry.note,
            mflux_cli=entry.mflux_cli, mflux_base=entry.mflux_base,
            defaults=entry.defaults or None, capabilities=entry.capabilities,
        ))

    # GGUF files a pipeline folder names as its own parts belong to that entry,
    # not the list: Wan's transformer and UMT5 encoder are how its folder runs.
    claimed: set[str] = set()
    for marker in models_dir.rglob("uncloud-video.json"):
        try:
            data = json.loads(marker.read_text())
        except (OSError, ValueError):
            continue
        for key in ("transformer_gguf", "text_encoder_gguf"):
            if data.get(key):
                claimed.add(str((marker.parent / str(data[key])).resolve()))
        claimed.update(str(p.resolve()) for p in marker.parent.glob("*.gguf"))

    # 1. Loose GGUF files anywhere under the folder.
    for gguf in models_dir.rglob("*.gguf"):
        if str(gguf) in seen_paths or any(str(gguf).startswith(d + "/") for d in seen_dirs):
            continue
        if str(gguf.resolve()) in claimed:
            continue
        seen_paths.add(str(gguf))
        category, engine, note, ready = _classify_gguf(gguf, models_dir)
        size_gb = gguf.stat().st_size / (1024 ** 3)
        found.append(LocalModel(
            id=f"local:{gguf}", name=gguf.stem, category=category, engine=engine,
            path=str(gguf), size_gb=size_gb, note=note, ready=ready,
        ))

    # 2. HF-cache-style `models--org--name` dirs (from huggingface_hub snapshot downloads)
    #    and mlx-community style folders containing config.json + safetensors. Recurses
    #    into arbitrarily nested folders (e.g. "Image Models/some-model/"), but stops
    #    descending once a directory is recognized as a model root — its own
    #    subfolders (text_encoder/, vae/, ...) are that model's components, not
    #    separate models.
    SKIP_DIRS = {"blobs", "manifests", "downloads", ".cache"}
    stack = [models_dir]
    while stack:
        current = stack.pop()
        try:
            children = sorted(current.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            if child.name in SKIP_DIRS or str(child) in seen_dirs:
                continue

            # Pre-quantised MLX checkpoints, which have no root manifest at all
            # and would otherwise be walked into as if they were a folder of
            # unrelated models.
            mlx = read_mlx_checkpoint(child)
            if mlx is not None:
                path_str = str(child)
                if path_str in seen_paths:
                    continue
                seen_paths.add(path_str)
                seen_dirs.add(path_str)
                found.append(LocalModel(
                    id=f"local:{child}", name=mlx.name, category="image",
                    engine="mflux", path=str(mlx.checkpoint),
                    # A recipe is a kilobyte of JSON; report the weights it
                    # points at, so the picker shows what loading it costs.
                    size_gb=_dir_size_gb(mlx.checkpoint),
                    ready=mlx.ready, note=mlx.note(), defaults=mlx.defaults,
                    mflux_cli=mlx.cli, mflux_base=mlx.base,
                    capabilities=["edit", "reference"] if mlx.base == "dev_kontext" else None,
                    lora_paths=mlx.lora_paths, lora_scales=mlx.lora_scales,
                ))
                continue

            # Folders that name their parts rather than shipping a loadable
            # pipeline. Checked first: one of these carries a model_index.json
            # copied from the release it was cut from, which would otherwise
            # read as a complete pipeline and fail on load.
            profile = read_profile(child, models_dir)
            if profile is not None:
                path_str = str(child)
                if path_str in seen_paths:
                    continue
                seen_paths.add(path_str)
                seen_dirs.add(path_str)
                found.append(LocalModel(
                    id=f"local:{child}", name=profile.name, category="image",
                    engine="flux2-profile", path=path_str, size_gb=profile.size_gb,
                    ready=profile.ready, note=profile.note(),
                    defaults={k: v for k, v in
                              (("steps", profile.steps), ("guidance", profile.guidance))
                              if v is not None},
                ))
                continue

            config_json = child / "config.json"
            model_index_json = child / "model_index.json"
            # A recursive glob here is what made scanning a large models folder
            # take twelve seconds: it walks the entire subtree of every
            # directory visited, on a drive holding hundreds of gigabytes. A
            # model root keeps its weights at the top level or one level down
            # inside a component folder, so two levels is all that is needed.
            has_safetensors = (
                any(child.glob("*.safetensors"))
                or any(child.glob("*/*.safetensors"))
            )
            is_diffusers_pipeline = model_index_json.exists() and has_safetensors
            is_mlx_model = config_json.exists() and has_safetensors and not is_diffusers_pipeline

            if is_mlx_model and child.name.lower() in (
                    "text_encoder", "text_encoder_2", "vae", "tokenizer", "scheduler",
                    "transformer"):
                # a bare component folder inside something else, not a model of its own
                is_mlx_model = False

            if not (is_diffusers_pipeline or is_mlx_model):
                recognised = _recognised_elsewhere(child)
                if recognised is not None:
                    seen_paths.add(str(child))
                    seen_dirs.add(str(child))
                    found.append(recognised)
                    continue
                stack.append(child)  # not a model root itself — keep looking inside it
                continue

            path_str = str(child)
            if path_str in seen_paths:
                continue
            seen_paths.add(path_str)

            # HF-cache-style dirs land here as models--org--name/snapshots/<commit hash> —
            # use the org/name folder for display instead of the raw commit hash.
            display_name = child.name
            if child.parent.name == "snapshots" and child.parent.parent.name.startswith("models--"):
                display_name = child.parent.parent.name.removeprefix("models--").replace("--", "/")
            lowered = display_name.lower()
            port_note: str | None = None
            ready, verdict_note = True, None
            if is_diffusers_pipeline:
                # From the pipeline class the folder declares, not from its name:
                # a renamed LTX folder is still LTX, and a HunyuanVideo folder
                # is video that the engine here cannot load.
                from .core.models import identify
                from .model_import import verdict

                v = verdict(identify(child, sizes=False))
                category, engine = v.category, v.engine
                ready, verdict_note = v.runnable, v.note or None
            elif any(h in lowered for h in STT_HINTS):
                # CTranslate2 conversions go to faster-whisper; a transformers
                # checkpoint (config.json and safetensors) is transcribed through
                # transformers instead of being turned away.
                category = "voice-stt"
                engine = ("faster-whisper" if (child / "model.bin").is_file()
                          else "transformers-whisper")
            elif speech_engine(child):
                category, engine = "voice-tts", speech_engine(child)
            elif any(h in lowered for h in TTS_HINTS):
                category, engine = "voice-tts", "kokoro"
            elif any(h in lowered for h in DIFFUSION_HINTS):
                port = _mlx_dir_engine(child)
                if port:
                    category, engine, port_note = port
                else:
                    category, engine, port_note = "image", "mflux", None
            elif "vibevoice" in lowered:
                # Narration models, not chat models. Left as text they appear in
                # the Chat picker and fail on load, which reads as the app being
                # broken rather than the choice being wrong.
                category, engine = "voice-tts", "vibevoice"
            elif "ace-step" in lowered or "acestep" in lowered:
                category, engine = "music", "acestep"
            else:
                category, engine = "text", "mlx"
            entry = None
            manifest = model_index_json if is_diffusers_pipeline else config_json
            try:
                cfg = json.loads(manifest.read_text())
                repo = cfg.get("_name_or_path", "") or cfg.get("_diffusers_version", "")
                entry = catalog_by_repo.get(repo)
            except (json.JSONDecodeError, OSError):
                pass
            found.append(LocalModel(
                id=f"local:{child}", name=entry.name if entry else display_name,
                category=entry.category if entry else category,
                engine=entry.engine if entry else engine,
                path=path_str, size_gb=_dir_size_gb(child),
                catalog_id=entry.id if entry else None,
                tags=entry.tags if entry else None,
                capabilities=entry.capabilities if entry else None,
                note=entry.note if entry else (port_note or verdict_note),
                ready=ready if not entry else True,
            ))

    found.extend(_imported(models_dir, {m.path for m in found} | seen_paths))
    return sorted(found, key=lambda m: m.name.lower())


def _recognised_elsewhere(child: Path) -> LocalModel | None:
    """A folder the shapes above do not match, but Core recognises: a model
    imported with a manifest, or a set such as Chatterbox or ACE-Step.

    Listed even when nothing here can run it. Invisible was the previous
    behaviour, and it is indistinguishable from the model not being there.
    """
    from .core.models import MANIFEST, Confidence, identify
    from .model_import import local_model, verdict

    has_manifest = (child / MANIFEST).is_file()
    identification = identify(child, sizes=False)
    if identification.contents or identification.confidence in (Confidence.UNKNOWN,
                                                               Confidence.GUESSED):
        return None
    if not has_manifest and identification.layout.value not in ("bundle", "ctranslate2",
                                                                "transformers"):
        return None
    identification.size_bytes = int(_dir_size_gb(child) * 1024 ** 3)
    return local_model(identification, verdict(identification))


def _imported(models_dir: Path, already: set[str]) -> list[LocalModel]:
    """Models added from outside the models folder, re-read from their files."""
    from .config import settings
    from .core.models import identify
    from .model_import import local_model, verdict

    out: list[LocalModel] = []
    for raw in settings.imported_models:
        path = Path(raw)
        if raw in already or not path.exists():
            continue
        try:
            path.relative_to(models_dir)
            continue                      # inside the folder: the walk has it
        except ValueError:
            pass
        mlx = read_mlx_checkpoint(path) if path.is_dir() else None
        if mlx is not None:
            out.append(LocalModel(
                id=f"local:{path}", name=mlx.name, category="image", engine="mflux",
                path=str(mlx.checkpoint), size_gb=_dir_size_gb(mlx.checkpoint),
                ready=mlx.ready, note=mlx.note(), defaults=mlx.defaults,
                mflux_cli=mlx.cli, mflux_base=mlx.base, lora_paths=mlx.lora_paths,
                lora_scales=mlx.lora_scales, tags=["imported"]))
            continue
        identification = identify(path, sizes=False)
        identification.size_bytes = (path.stat().st_size if path.is_file()
                                     else int(_dir_size_gb(path) * 1024 ** 3))
        model = local_model(identification, verdict(identification))
        if model.engine == "gguf-diffusion" and model.category == "image":
            # Same second opinion as the folder walk: a lone transformer is
            # runnable if something in the models folder can complete it.
            from .gguf_diffusion import assembly_for

            assembly = assembly_for(path, identification.family or "", models_dir)
            model.note, model.ready = assembly.note(), assembly.ready
        out.append(model)
    return out


@dataclass
class Component:
    path: str
    name: str
    role: str  # diffusion | text_encoder | vae
    arch: str  # flux2 | flux1 | sdxl | unknown
    size_gb: float

    def to_dict(self) -> dict:
        return {"path": self.path, "name": self.name, "role": self.role,
                "arch": self.arch, "size_gb": round(self.size_gb, 2)}


def _guess_arch(lowered_name: str) -> str:
    if "flux2" in lowered_name or "flux.2" in lowered_name or "klein" in lowered_name:
        return "flux2"
    if "flux" in lowered_name:
        return "flux1"
    if "sdxl" in lowered_name or "xl" in lowered_name:
        return "sdxl"
    return "unknown"


def _guess_role(lowered_name: str) -> str:
    if "vae" in lowered_name:
        return "vae"
    if any(h in lowered_name for h in
           ("text_encoder", "text-encoder", "qwen", "clip", "t5", "encoder")):
        return "text_encoder"
    return "diffusion"


def scan_components(models_dir: Path) -> list[Component]:
    """Standalone .safetensors files (diffusion/text-encoder/VAE distributed as
    separate files, e.g. ComfyUI-style checkpoints) rather than a bundled model."""
    if not models_dir.exists():
        return []

    found: list[Component] = []
    for f in models_dir.rglob("*.safetensors"):
        if f.stat().st_size < 200 * 1024 * 1024:  # skip small LoRA/adapter files
            continue
        lowered = f.name.lower()
        found.append(Component(
            path=str(f), name=f.stem, role=_guess_role(lowered),
            arch=_guess_arch(lowered), size_gb=f.stat().st_size / (1024 ** 3),
        ))
    return sorted(found, key=lambda c: (c.role, c.name.lower()))


# Scanning walks the whole models folder, which on an external drive holding a
# few hundred gigabytes is slow enough that doing it per request makes the app
# look broken. Results are cached and invalidated on a timer or on demand —
# models do not appear on disk without the user knowing.
_CACHE_TTL = 45.0
_cache: dict[str, tuple[float, list]] = {}


def scan_library_cached(models_dir: Path, *, refresh: bool = False) -> list[LocalModel]:
    import time

    key = str(models_dir)
    now = time.monotonic()
    hit = _cache.get(key)
    if not refresh and hit and (now - hit[0]) < _CACHE_TTL:
        return hit[1]
    found = scan_library(models_dir)
    _cache[key] = (now, found)
    return found


def invalidate_library_cache() -> None:
    """Called after a download finishes or the models folder changes."""
    _cache.clear()
