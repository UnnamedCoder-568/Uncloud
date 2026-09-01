from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .catalog import get_catalog
from .flux2_profile import read_profile

DIFFUSION_HINTS = ("qwen-image", "hidream", "flux", "sdxl", "sd3", "stable-diffusion", "video", "wan2", "cogvideo", "ltx", "krea", "klein", "pony")
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

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "category": self.category,
            "engine": self.engine, "path": self.path, "size_gb": round(self.size_gb, 2),
            "catalog_id": self.catalog_id, "tags": self.tags or [], "ready": self.ready,
            "note": self.note, "capabilities": self.capabilities or ["text2img"],
            "defaults": self.defaults or {},
        }


def _dir_size_gb(path: Path) -> float:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
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


def _classify_gguf(path: Path) -> tuple[str, str, str | None]:
    """Returns (category, engine, note) for a .gguf file, from its header."""
    arch, name = _gguf_architecture(path)
    lowered_name = (name or "").lower()

    # A language-model architecture whose own name says encoder is a pipeline
    # component, not something to load on its own.
    if "text encoder" in lowered_name or "text_encoder" in lowered_name:
        return ("component", "text-encoder",
                "Text encoder for a diffusion pipeline — pair it with a model, "
                "not selectable on its own.")
    if arch in _DIFFUSION_ARCHS:
        return ("image", "gguf-diffusion",
                "Quantised diffusion transformer. Needs the matching VAE, tokenizer "
                "and text encoder from a full pipeline alongside it.")
    if arch and arch.startswith(_LM_ARCH_PREFIXES):
        return "text", "gguf", None

    # Header unreadable or unfamiliar: fall back to the old filename guess, but
    # say so rather than presenting it as a confident classification.
    if any(h in path.name.lower() for h in DIFFUSION_HINTS):
        return ("image", "gguf-diffusion",
                "Guessed from the filename — the GGUF header could not be read.")
    return "text", "gguf", None


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
    if not models_dir.exists():
        return []

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
        if entry.single_file and entry.files:
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
            capabilities=entry.capabilities,
        ))

    # 1. Loose GGUF files anywhere under the folder.
    for gguf in models_dir.rglob("*.gguf"):
        if str(gguf) in seen_paths or any(str(gguf).startswith(d + "/") for d in seen_dirs):
            continue
        seen_paths.add(str(gguf))
        category, engine, note = _classify_gguf(gguf)
        size_gb = gguf.stat().st_size / (1024 ** 3)
        found.append(LocalModel(
            id=f"local:{gguf}", name=gguf.stem, category=category, engine=engine,
            path=str(gguf), size_gb=size_gb, note=note,
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

            if is_mlx_model and child.name.lower() in ("text_encoder", "text_encoder_2", "vae", "tokenizer", "scheduler", "transformer"):
                is_mlx_model = False  # a bare component folder inside something else, not a model of its own

            if not (is_diffusers_pipeline or is_mlx_model):
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
            if is_diffusers_pipeline:
                if any(h in lowered for h in STT_HINTS):
                    category, engine = "voice-stt", "faster-whisper"
                elif any(h in lowered for h in TTS_HINTS):
                    category, engine = "voice-tts", "kokoro"
                elif any(h in lowered for h in ("video", "wan2", "cogvideo", "ltx")):
                    category, engine = "video", "diffusers"
                else:
                    category, engine = "image", "diffusers"
            elif any(h in lowered for h in STT_HINTS):
                category, engine = "voice-stt", "faster-whisper"
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
                note=entry.note if entry else port_note,
            ))

    return sorted(found, key=lambda m: m.name.lower())


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
    if any(h in lowered_name for h in ("text_encoder", "text-encoder", "qwen", "clip", "t5", "encoder")):
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
