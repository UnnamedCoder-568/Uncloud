from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .catalog import get_catalog

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

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "category": self.category,
            "engine": self.engine, "path": self.path, "size_gb": round(self.size_gb, 2),
            "catalog_id": self.catalog_id, "tags": self.tags or [], "ready": self.ready,
            "note": self.note, "capabilities": self.capabilities or ["text2img"],
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


def _classify_gguf(path: Path) -> tuple[str, str, str | None]:
    """Returns (category, engine, note) for a .gguf file based on its name."""
    lowered = path.name.lower()
    if any(h in lowered for h in DIFFUSION_HINTS):
        return "image", "stable-diffusion-cpp", "GGUF diffusion checkpoint — needs the stable-diffusion.cpp backend (not yet wired up)."
    return "text", "gguf", None


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

            config_json = child / "config.json"
            model_index_json = child / "model_index.json"
            has_safetensors = any(child.glob("*.safetensors")) or any(child.glob("**/*.safetensors"))
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
                category, engine = "image", "mflux"
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
