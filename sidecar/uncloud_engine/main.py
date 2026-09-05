from __future__ import annotations

import asyncio
import json
import re
import secrets
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .agent.graph import ExecutionGraph
from .agent.orchestrator import orchestrator
from .agent.tools import TOOL_SPECS
from .catalog import get_catalog, get_entry
from .chat import build_chat_payload
from . import conversations as conversations_store
from .config import settings
from .downloader import download_manager
from .engines import engine_manager
from .image_engine import image_engine
from .library import invalidate_library_cache, scan_library_cached, scan_components
from . import characters, product_studio, voice_engine
from . import music_engine as music_engine_mod
from .music_engine import music_engine
from . import narration_engine as narration_engine_mod
from .narration_engine import narration_engine
from . import video_engine as video_engine_mod

app = FastAPI(title="Uncloud Engine")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://localhost:1420", "http://127.0.0.1:1420"],
    allow_methods=["*"], allow_headers=["*"],
)


def require_token(authorization: str | None = Header(default=None)) -> None:
    if authorization != f"Bearer {settings.token}":
        raise HTTPException(status_code=401, detail="Invalid or missing token")


def require_token_ws(token: str = Query(default="")) -> bool:
    return secrets.compare_digest(token, settings.token)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.on_event("shutdown")
async def _shutdown() -> None:
    """Release every model and child process.

    A chat server can be holding twenty gigabytes and is a child process, so
    nothing reclaims it just because the window closed.
    """
    from .lifecycle import stop_all

    await stop_all()


def _install_signal_handlers() -> None:
    """Tauri sends SIGTERM on quit; without a handler the process dies before
    FastAPI's shutdown event runs and every loaded model is left orphaned."""
    import signal

    def _handle(signum, _frame):  # noqa: ANN001
        from .lifecycle import stop_all_blocking

        stop_all_blocking()
        raise SystemExit(0)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        try:
            signal.signal(sig, _handle)
        except (ValueError, OSError):
            pass


_install_signal_handlers()

# A quit the app cannot signal — force quit, crash — would otherwise leave this
# process and its models running with nothing left to stop them.
from .lifecycle import watch_parent  # noqa: E402

watch_parent()


# ----------------------------------------------------------------- outputs
@app.get("/api/outputs", dependencies=[Depends(require_token)])
def outputs_list(limit: int = 300, kind: str = "") -> dict:
    from .outputs import list_outputs

    return {"root": str(settings.output_dir), "files": list_outputs(limit, kind)}


@app.get("/api/outputs/file", dependencies=[Depends(require_token)])
def outputs_file(path: str) -> FileResponse:
    from pathlib import Path as _P

    root = settings.output_dir.resolve()
    target = _P(path).resolve()
    # Serving is scoped to the output folder; the path arrives over HTTP.
    if root not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="Not an output file")
    return FileResponse(str(target))


class OutputPathBody(BaseModel):
    path: str


@app.post("/api/outputs/reveal", dependencies=[Depends(require_token)])
def outputs_reveal(body: OutputPathBody) -> dict:
    from .outputs import reveal

    return {"ok": reveal(body.path)}


class SaveCopyBody(BaseModel):
    path: str
    dest: str
    # True when `dest` is a folder to drop the file into keeping its name;
    # False when it is the full filename a Save-as dialog returned.
    into_folder: bool = True


@app.post("/api/outputs/save_copy", dependencies=[Depends(require_token)])
def outputs_save_copy(body: SaveCopyBody) -> dict:
    from .outputs import save_copy

    try:
        return {"path": save_copy(body.path, body.dest, into_folder=body.into_folder)}
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Could not save there: {exc}") from exc


@app.post("/api/outputs/delete", dependencies=[Depends(require_token)])
def outputs_delete(body: OutputPathBody) -> dict:
    from .outputs import delete

    try:
        return {"ok": delete(body.path)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ------------------------------------------------------------------ system
@app.get("/api/system/resident", dependencies=[Depends(require_token)])
def system_resident() -> dict:
    from .lifecycle import resident

    return resident()


@app.get("/api/system/budget", dependencies=[Depends(require_token)])
def system_budget(frames: int = 0, width: int = 0, height: int = 0,
                  weights_gb: float = 0.0, model_path: str = "") -> dict:
    """What this machine can give, and what the requested job would take.

    Asked before starting rather than discovered during: on macOS an oversized
    job is refused with a message, but a discrete GPU can take the machine down
    with it.
    """
    from .budget import (estimate_video_gb, memory_budget, resident_weights_gb,
                         video_capability)

    out: dict = {"budget": memory_budget()}
    # Whether this machine can run video at all, independent of the job asked
    # for — the Video tab is hidden below this floor rather than failing the
    # same way on every setting.
    from .video_engine import family_for

    family = family_for(model_path).name if model_path else "ltx"
    weights = weights_gb or resident_weights_gb(model_path)
    out["video"] = video_capability(weights, family)
    if frames and width and height:
        # Measure what stays resident rather than trusting a folder size: the
        # text encoder is the bulk of the folder and is freed before denoising.
        est = estimate_video_gb(frames, width, height, weights, family)
        out["estimate"] = est
        budget = out["budget"]["budget_gb"]
        out["fits"] = est["total_gb"] <= budget
        out["tight"] = est["total_gb"] > budget * 0.85
    return out


@app.get("/api/system/weight_cache", dependencies=[Depends(require_token)])
def weight_cache() -> dict:
    from .flux2_profile import CACHE_ROOT, cache_size_bytes

    return {"bytes": cache_size_bytes(), "path": str(CACHE_ROOT)}


@app.post("/api/system/weight_cache/clear", dependencies=[Depends(require_token)])
def weight_cache_clear() -> dict:
    from .flux2_profile import clear_cache

    return {"freed_bytes": clear_cache()}


@app.post("/api/system/stop_all", dependencies=[Depends(require_token)])
async def system_stop_all() -> dict:
    from .lifecycle import stop_all

    return (await stop_all()).to_dict()


# ---------------------------------------------------------------- settings
@app.get("/api/settings", dependencies=[Depends(require_token)])
def get_settings() -> dict:
    return {
        "models_dir": str(settings.models_dir),
        "onboarded": settings.onboarded,
        "agent_device_access": settings.agent_device_access,
        "keep_awake": settings.keep_awake,
        "output_dir": str(settings.output_dir),
        "output_dir_is_default": settings.output_dir_is_default,
        "hf_token_set": settings.hf_token_set,
    }


class ModelsDirBody(BaseModel):
    path: str


@app.post("/api/settings/models_dir", dependencies=[Depends(require_token)])
def set_models_dir(body: ModelsDirBody) -> dict:
    settings.set_models_dir(body.path)
    invalidate_library_cache()
    return {"ok": True}


@app.post("/api/settings/onboarded", dependencies=[Depends(require_token)])
def mark_onboarded() -> dict:
    settings.mark_onboarded()
    return {"ok": True}


class DeviceAccessBody(BaseModel):
    enabled: bool


@app.post("/api/settings/agent_device_access", dependencies=[Depends(require_token)])
def set_device_access(body: DeviceAccessBody) -> dict:
    settings.set_agent_device_access(body.enabled)
    return {"ok": True}


class OutputDirBody(BaseModel):
    path: str


@app.post("/api/settings/output_dir", dependencies=[Depends(require_token)])
def set_output_dir(body: OutputDirBody) -> dict:
    settings.set_output_dir(body.path)
    return {"ok": True, "output_dir": str(settings.output_dir)}


@app.post("/api/settings/keep_awake", dependencies=[Depends(require_token)])
def set_keep_awake(body: DeviceAccessBody) -> dict:
    settings.set_keep_awake(body.enabled)
    return {"ok": True}


@app.get("/api/agent/tools", dependencies=[Depends(require_token)])
def agent_tools() -> dict:
    from .agent.orchestrator import _active_tool_specs
    from .agent.tools import auto_groups, group_summary
    from .engines import engine_manager

    active = engine_manager.active
    configured = settings.agent_tool_groups
    resolved = configured if configured is not None else auto_groups(
        active.model_path if active else None
    )
    return {
        "groups": group_summary(),
        "configured": configured,      # None means automatic
        "resolved": resolved,
        "active_count": len(_active_tool_specs()),
    }


class ToolGroupsBody(BaseModel):
    groups: list[str] | None = None


@app.post("/api/agent/tool_groups", dependencies=[Depends(require_token)])
def set_agent_tool_groups(body: ToolGroupsBody) -> dict:
    settings.set_agent_tool_groups(body.groups)
    return {"ok": True}


class HfTokenBody(BaseModel):
    token: str


@app.post("/api/settings/hf_token", dependencies=[Depends(require_token)])
def set_hf_token(body: HfTokenBody) -> dict:
    settings.set_hf_token(body.token)
    return {"ok": True}


# ----------------------------------------------------------------- catalog
@app.get("/api/catalog", dependencies=[Depends(require_token)])
def catalog() -> list[dict]:
    from .budget import engine_runs_here

    installed = {m.catalog_id for m in scan_library_cached(settings.models_dir) if m.catalog_id}
    out = []
    for entry in get_catalog():
        # A model whose runtime does not exist here is not a model this machine
        # has; offering it is offering a download that ends in a stack trace.
        if not engine_runs_here(entry.engine):
            continue
        d = entry.__dict__.copy()
        d["installed"] = entry.id in installed
        out.append(d)
    return out


@app.get("/api/library", dependencies=[Depends(require_token)])
def library() -> list[dict]:
    return [m.to_dict() for m in scan_library_cached(settings.models_dir)]


@app.get("/api/image/components", dependencies=[Depends(require_token)])
def image_components() -> list[dict]:
    return [c.to_dict() for c in scan_components(settings.models_dir)]


# --------------------------------------------------------------- downloads
# ------------------------------------------------------------- quantising
class QuantizeBody(BaseModel):
    source: str
    base: str
    name: str
    transformer_bits: int = 8
    encoder_bits: int = 4
    dest_dir: str | None = None
    lora_paths: list[str] = []
    lora_scales: list[float] = []


@app.get("/api/quantize/bases", dependencies=[Depends(require_token)])
def quantize_bases() -> dict:
    from .quantize import BITS, base_models

    return {"bits": list(BITS), "bases": base_models()}


@app.get("/api/quantize", dependencies=[Depends(require_token)])
def quantize_list() -> list[dict]:
    from .quantize import quantize_manager

    return quantize_manager.list_jobs()


# async, because start() schedules the build with asyncio.create_task and a
# sync endpoint runs in a threadpool where there is no loop to schedule on.
@app.post("/api/quantize", dependencies=[Depends(require_token)])
async def quantize_start(body: QuantizeBody) -> dict:
    from .quantize import quantize_manager

    try:
        job = quantize_manager.start(
            source=body.source, base=body.base,
            dest_dir=body.dest_dir or str(settings.models_dir),
            name=body.name, transformer_bits=body.transformer_bits,
            encoder_bits=body.encoder_bits,
            lora_paths=body.lora_paths, lora_scales=body.lora_scales,
        )
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job.to_dict()


@app.get("/api/quantize/{job_id}", dependencies=[Depends(require_token)])
def quantize_status(job_id: str) -> dict:
    from .quantize import quantize_manager

    job = quantize_manager.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="No such job")
    return job.to_dict()


class DownloadBody(BaseModel):
    catalog_id: str


@app.post("/api/downloads", dependencies=[Depends(require_token)])
async def start_download(body: DownloadBody) -> dict:
    try:
        state = download_manager.start(body.catalog_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return state.to_dict()


@app.get("/api/downloads", dependencies=[Depends(require_token)])
def list_downloads() -> list[dict]:
    return download_manager.list()


@app.post("/api/downloads/{download_id}/cancel", dependencies=[Depends(require_token)])
def cancel_download(download_id: str) -> dict:
    download_manager.cancel(download_id)
    return {"ok": True}


# ------------------------------------------------------------------ engine
class EngineStartBody(BaseModel):
    model_path: str
    engine: str


@app.post("/api/engine/start", dependencies=[Depends(require_token)])
async def start_engine(body: EngineStartBody) -> dict:
    try:
        active = await engine_manager.start(body.model_path, body.engine)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"running": True, "port": active.port, "engine": active.engine}


@app.post("/api/engine/stop", dependencies=[Depends(require_token)])
def stop_engine() -> dict:
    engine_manager.stop()
    return {"ok": True}


@app.get("/api/engine/status", dependencies=[Depends(require_token)])
def engine_status() -> dict:
    return engine_manager.status()


# ------------------------------------------------------------------- chat
class ChatBody(BaseModel):
    messages: list[dict]
    temperature: float = 0.7
    max_tokens: int = 1024


@app.post("/api/chat", dependencies=[Depends(require_token)])
async def chat(body: ChatBody) -> StreamingResponse:
    if not engine_manager.active:
        raise HTTPException(status_code=400, detail="No text model loaded")

    import httpx

    async def relay() -> Any:
        async with httpx.AsyncClient(timeout=None) as client:
            payload = build_chat_payload(
                body.messages,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                engine=engine_manager.active.engine,
            )
            # Plain Chat is a direct-answer surface. Thinking-capable GGUF
            # templates otherwise default to an unlimited private-reasoning
            # pass, and small Qwen variants can loop there without ever
            # emitting an answer. Agent planning remains a separate endpoint.
            async with client.stream(
                "POST", f"{engine_manager.active.base_url}/v1/chat/completions", json=payload,
            ) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk

    return StreamingResponse(relay(), media_type="text/event-stream")


# ------------------------------------------------------------------- image
class ImageGenerateBody(BaseModel):
    model_path: str
    engine: str
    # Optional uncensored text encoder, for pipelines whose encoder is a
    # causal LM (FLUX.2 Klein). Ignored elsewhere.
    text_encoder_path: str | None = None
    # Locally-found MLX checkpoints are not in the catalog, so the picker sends
    # which mflux entry point runs them and which base to configure them as.
    mflux_cli: str | None = None
    mflux_base: str | None = None
    # Adapters applied on top of an mflux checkpoint at load time — a fine-tune
    # without a second copy of the weights.
    lora_paths: list[str] = []
    lora_scales: list[float] = []
    prompt: str
    catalog_id: str | None = None
    negative_prompt: str = ""
    steps: int | None = None
    guidance: float | None = None
    width: int = 1024
    height: int = 1024
    seed: int | None = None


@app.post("/api/image/generate", dependencies=[Depends(require_token)])
async def generate_image(body: ImageGenerateBody) -> dict:
    entry = get_entry(body.catalog_id) if body.catalog_id else None
    job = image_engine.start(
        body.model_path, body.engine, body.prompt, negative_prompt=body.negative_prompt,
        steps=body.steps, guidance=body.guidance, width=body.width, height=body.height, seed=body.seed,
        mflux_cli=body.mflux_cli or (entry.mflux_cli if entry else "mflux-generate"),
        mflux_base=body.mflux_base or (entry.mflux_base if entry else None),
        lora_paths=body.lora_paths, lora_scales=body.lora_scales,
        text_encoder_path=body.text_encoder_path,
    )
    return job.to_dict()


UPLOAD_DIR = Path.home() / ".uncloud" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.post("/api/image/upload", dependencies=[Depends(require_token)])
async def upload_image(file: UploadFile = File(...)) -> dict:
    """Stash a user-supplied reference image and hand back its local path."""
    suffix = Path(file.filename or "ref.png").suffix.lower() or ".png"
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {suffix}")
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex[:12]}{suffix}"
    dest.write_bytes(await file.read())
    return {"path": str(dest)}


class ImageEditBody(BaseModel):
    model_path: str
    prompt: str
    reference_path: str
    catalog_id: str | None = None
    steps: int | None = None
    guidance: float | None = None
    width: int | None = None
    height: int | None = None
    seed: int | None = None
    strength: float | None = None


@app.post("/api/image/edit", dependencies=[Depends(require_token)])
async def edit_image(body: ImageEditBody) -> dict:
    entry = get_entry(body.catalog_id) if body.catalog_id else None
    job = image_engine.start_edit(
        body.model_path, body.prompt, body.reference_path,
        steps=body.steps, guidance=body.guidance, width=body.width, height=body.height,
        seed=body.seed, strength=body.strength,
        mflux_cli=entry.mflux_cli if entry else "mflux-generate-kontext",
    )
    return job.to_dict()


# ----------------------------------------------------------------- product
@app.get("/api/product/categories", dependencies=[Depends(require_token)])
def product_categories() -> list[dict]:
    return product_studio.to_dict()


class ProductGenerateBody(BaseModel):
    model_path: str
    reference_path: str
    category: str
    shots: list[str]
    catalog_id: str | None = None
    model_description: str = ""
    background: str = ""
    extra: str = ""
    steps: int | None = None
    guidance: float | None = None
    seed: int | None = None


@app.post("/api/product/generate", dependencies=[Depends(require_token)])
async def product_generate(body: ProductGenerateBody) -> list[dict]:
    """Queue one edit job per requested shot type. They run sequentially — each
    holds several GB, so overlapping them would thrash memory."""
    if not body.shots:
        raise HTTPException(status_code=400, detail="Pick at least one shot type")
    entry = get_entry(body.catalog_id) if body.catalog_id else None
    cli = entry.mflux_cli if entry else "mflux-generate-kontext"

    jobs = []
    for shot_id in body.shots:
        try:
            instruction = product_studio.build_instruction(
                body.category, shot_id,
                model_description=body.model_description,
                background=body.background,
                extra=body.extra,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        shot = product_studio.get_shot(body.category, shot_id)
        width, height = product_studio.ASPECT_SIZES.get(shot.aspect if shot else "portrait", (768, 1024))
        job = image_engine.start_edit(
            body.model_path, instruction, body.reference_path,
            steps=body.steps, guidance=body.guidance,
            width=width, height=height, seed=body.seed,
            mflux_cli=cli, label=shot.name if shot else shot_id,
        )
        jobs.append(job.to_dict())
    return jobs


# -------------------------------------------------------------- characters
@app.get("/api/characters", dependencies=[Depends(require_token)])
def list_chars() -> list[dict]:
    return [c.to_dict() for c in characters.list_characters()]


class CharacterBody(BaseModel):
    name: str
    description: str = ""
    tags: list[str] = []
    reference_path: str | None = None
    slug: str | None = None


@app.post("/api/characters", dependencies=[Depends(require_token)])
def save_char(body: CharacterBody) -> dict:
    try:
        char = characters.save_character(
            body.name, body.description, body.tags, body.reference_path, body.slug,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return char.to_dict()


@app.delete("/api/characters/{slug}", dependencies=[Depends(require_token)])
def delete_char(slug: str) -> dict:
    if not characters.delete_character(slug):
        raise HTTPException(status_code=404, detail="No such character")
    return {"ok": True}


@app.get("/api/characters/{slug}/reference", dependencies=[Depends(require_token)])
def character_reference(slug: str) -> FileResponse:
    char = characters.get_character(slug)
    if not char or not char.reference_path.exists():
        raise HTTPException(status_code=404, detail="No reference image")
    return FileResponse(char.reference_path, media_type="image/png")


class ExportBody(BaseModel):
    job_ids: list[str]
    dest_dir: str
    prefix: str = ""


@app.post("/api/image/export", dependencies=[Depends(require_token)])
def export_images(body: ExportBody) -> dict:
    """Copy finished renders out to a folder the user picked, named per shot."""
    import shutil

    dest = Path(body.dest_dir).expanduser()
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Cannot write to {dest}: {exc}")

    written: list[str] = []
    for i, job_id in enumerate(body.job_ids, 1):
        job = image_engine.jobs.get(job_id)
        if not job or not job.output_path or not Path(job.output_path).exists():
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", (job.label or f"shot-{i}").lower()).strip("-")
        name = f"{body.prefix}{'-' if body.prefix else ''}{i:02d}-{slug}.png"
        target = dest / name
        shutil.copyfile(job.output_path, target)
        written.append(str(target))

    if not written:
        raise HTTPException(status_code=400, detail="No finished images to export")
    return {"written": written, "dir": str(dest)}


@app.get("/api/image/jobs", dependencies=[Depends(require_token)])
def list_image_jobs() -> list[dict]:
    return image_engine.list_jobs()


@app.get("/api/image/jobs/{job_id}", dependencies=[Depends(require_token)])
def get_image_job(job_id: str) -> dict:
    job = image_engine.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job")
    return job.to_dict()


@app.get("/api/image/output/{job_id}", dependencies=[Depends(require_token)])
def get_image_output(job_id: str) -> FileResponse:
    job = image_engine.jobs.get(job_id)
    if not job or not job.output_path:
        raise HTTPException(status_code=404, detail="Image not ready")
    return FileResponse(job.output_path, media_type="image/png")


# ------------------------------------------------------------------- video
class VideoGenerateBody(BaseModel):
    model_path: str
    prompt: str
    negative_prompt: str = video_engine_mod.DEFAULT_NEGATIVE_PROMPT
    frames: int = video_engine_mod.DEFAULT_FRAMES
    fps: int = video_engine_mod.DEFAULT_FPS
    width: int = video_engine_mod.DEFAULT_W
    height: int = video_engine_mod.DEFAULT_H
    steps: int = video_engine_mod.DEFAULT_STEPS
    guidance: float = video_engine_mod.DEFAULT_GUIDANCE
    seed: int | None = None


@app.get("/api/video/options", dependencies=[Depends(require_token)])
def video_options() -> dict:
    return {
        "default_frames": video_engine_mod.DEFAULT_FRAMES,
        "default_fps": video_engine_mod.DEFAULT_FPS,
        "default_width": video_engine_mod.DEFAULT_W,
        "default_height": video_engine_mod.DEFAULT_H,
        "default_steps": video_engine_mod.DEFAULT_STEPS,
        "default_guidance": video_engine_mod.DEFAULT_GUIDANCE,
        "default_negative_prompt": video_engine_mod.DEFAULT_NEGATIVE_PROMPT,
        "max_pixels": video_engine_mod.MAX_PIXELS,
    }


@app.post("/api/video/generate", dependencies=[Depends(require_token)])
async def video_generate(body: VideoGenerateBody) -> dict:
    from .video_engine import video_engine

    job = video_engine.start(
        body.model_path, body.prompt, negative_prompt=body.negative_prompt,
        frames=body.frames, fps=body.fps, width=body.width, height=body.height,
        steps=body.steps, guidance=body.guidance, seed=body.seed,
    )
    return job.to_dict()


@app.get("/api/video/jobs/{job_id}", dependencies=[Depends(require_token)])
def video_job(job_id: str) -> dict:
    from .video_engine import video_engine

    job = video_engine.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="No such video job")
    return job.to_dict()


@app.get("/api/video/output/{job_id}", dependencies=[Depends(require_token)])
def video_output(job_id: str) -> FileResponse:
    from .video_engine import video_engine

    job = video_engine.get(job_id)
    if not job or not job.output_path:
        raise HTTPException(status_code=404, detail="Video not ready")
    return FileResponse(job.output_path, media_type="video/mp4")


# ------------------------------------------------------------------- music
@app.get("/api/music/options", dependencies=[Depends(require_token)])
def music_options() -> dict:
    return {
        "sample_rates": music_engine_mod.SAMPLE_RATES,
        "bit_depths": music_engine_mod.BIT_DEPTHS,
        "stems": list(music_engine_mod.STEM_NAMES),
        "formats": music_engine_mod.AUDIO_FORMATS,
        "quality": music_engine_mod.QUALITY_PRESETS,
        "installed": music_engine_mod.acestep_available(),
        "max_duration": 600,
    }


class MusicGenerateBody(BaseModel):
    model_dir: str
    prompt: str
    lyrics: str = ""
    instrumental: bool = False
    duration: float = 180.0
    bpm: int | None = None
    keyscale: str = ""
    steps: int = 8
    guidance: float = 7.0
    seed: int | None = None
    sample_rate: int = 44100
    bit_depth: int = 24
    audio_format: str = "wav"
    separate_stems: bool = False


@app.post("/api/music/generate", dependencies=[Depends(require_token)])
async def generate_music_track(body: MusicGenerateBody) -> dict:
    if body.sample_rate not in music_engine_mod.SAMPLE_RATES:
        raise HTTPException(status_code=400, detail=f"sample_rate must be one of {music_engine_mod.SAMPLE_RATES}")
    if body.bit_depth not in music_engine_mod.BIT_DEPTHS:
        raise HTTPException(status_code=400, detail=f"bit_depth must be one of {music_engine_mod.BIT_DEPTHS}")
    job = music_engine.start(
        body.model_dir, body.prompt, lyrics=body.lyrics, instrumental=body.instrumental,
        duration=body.duration, bpm=body.bpm, keyscale=body.keyscale, steps=body.steps,
        guidance=body.guidance, seed=body.seed, sample_rate=body.sample_rate,
        bit_depth=body.bit_depth, separate_stems=body.separate_stems,
        audio_format=body.audio_format,
    )
    return job.to_dict()


@app.get("/api/music/jobs", dependencies=[Depends(require_token)])
def list_music_jobs() -> list[dict]:
    return music_engine.list_jobs()


@app.get("/api/music/jobs/{job_id}", dependencies=[Depends(require_token)])
def get_music_job(job_id: str) -> dict:
    job = music_engine.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job")
    return job.to_dict()


@app.get("/api/music/audio/{job_id}", dependencies=[Depends(require_token)])
def get_music_audio(job_id: str, stem: str = Query(default="")) -> FileResponse:
    """Return the mixdown, or one separated stem when `stem` is given."""
    job = music_engine.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job")
    path = job.stems.get(stem) if stem else job.output_path
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Audio not ready")
    return FileResponse(path, media_type="audio/wav", filename=Path(path).name)


# --------------------------------------------------------------- narration
@app.get("/api/narration/options", dependencies=[Depends(require_token)])
def narration_options(engine: str = Query(default="realtime")) -> dict:
    return {
        "sample_rates": narration_engine_mod.SAMPLE_RATES,
        "bit_depths": narration_engine_mod.BIT_DEPTHS,
        "formats": narration_engine_mod.AUDIO_FORMATS,
        "quality": narration_engine_mod.QUALITY_PRESETS,
        "installed": narration_engine_mod.vibevoice_available(),
        "engines": narration_engine_mod.available_engines(),
        "voices": [v.to_dict() for v in narration_engine_mod.list_voices(engine)],
    }


class NarrationBody(BaseModel):
    model_dir: str
    text: str
    voice_slug: str = ""
    sample_rate: int = 44100
    bit_depth: int = 24
    audio_format: str = "wav"
    cfg_scale: float = 1.3
    ddpm_steps: int = 20
    engine: str = "realtime"


@app.post("/api/narration/generate", dependencies=[Depends(require_token)])
async def generate_narration(body: NarrationBody) -> dict:
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    job = narration_engine.start(
        body.model_dir, body.text, voice_slug=body.voice_slug,
        sample_rate=body.sample_rate, bit_depth=body.bit_depth, cfg_scale=body.cfg_scale,
        ddpm_steps=body.ddpm_steps, audio_format=body.audio_format, engine=body.engine,
    )
    return job.to_dict()


@app.get("/api/narration/jobs/{job_id}", dependencies=[Depends(require_token)])
def get_narration_job(job_id: str) -> dict:
    job = narration_engine.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job")
    return job.to_dict()


@app.get("/api/narration/audio/{job_id}", dependencies=[Depends(require_token)])
def get_narration_audio(job_id: str) -> FileResponse:
    job = narration_engine.jobs.get(job_id)
    if not job or not job.output_path or not Path(job.output_path).exists():
        raise HTTPException(status_code=404, detail="Audio not ready")
    return FileResponse(job.output_path, media_type="audio/wav",
                        filename=Path(job.output_path).name)


class VoiceBody(BaseModel):
    name: str
    sample_path: str | None = None
    notes: str = ""


@app.post("/api/narration/voices", dependencies=[Depends(require_token)])
def save_narration_voice(body: VoiceBody) -> dict:
    try:
        voice = narration_engine_mod.save_voice(body.name, body.sample_path, body.notes)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return voice.to_dict()


@app.delete("/api/narration/voices/{slug}", dependencies=[Depends(require_token)])
def delete_narration_voice(slug: str) -> dict:
    if not narration_engine_mod.delete_voice(slug):
        raise HTTPException(status_code=404, detail="No such voice")
    return {"ok": True}


@app.post("/api/narration/voices/upload", dependencies=[Depends(require_token)])
async def upload_voice_sample(file: UploadFile = File(...)) -> dict:
    """Stash a reference recording so it can be attached to a saved voice."""
    suffix = Path(file.filename or "sample.wav").suffix.lower() or ".wav"
    if suffix not in (".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"):
        raise HTTPException(status_code=400, detail=f"Unsupported audio type: {suffix}")
    dest = UPLOAD_DIR / f"voice-{uuid.uuid4().hex[:10]}{suffix}"
    dest.write_bytes(await file.read())
    return {"path": str(dest)}


# ------------------------------------------------------------------- voice
@app.post("/api/voice/transcribe", dependencies=[Depends(require_token)])
async def transcribe_audio(file: UploadFile = File(...), model_path: str = Form(...)) -> dict:
    import tempfile

    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        text = await asyncio.to_thread(voice_engine.transcribe, model_path, tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return {"text": text}


class SpeakBody(BaseModel):
    text: str
    voice: str = "af_heart"
    speed: float = 1.0


@app.post("/api/voice/speak", dependencies=[Depends(require_token)])
async def speak_text(body: SpeakBody) -> FileResponse:
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    try:
        out_path = await asyncio.to_thread(voice_engine.speak, body.text, body.voice, body.speed)
    except Exception as exc:  # noqa: BLE001 - surface synthesis failures (e.g. missing espeak-ng)
        raise HTTPException(status_code=500, detail=str(exc))
    return FileResponse(out_path, media_type="audio/wav")


@app.get("/api/voice/voices", dependencies=[Depends(require_token)])
def list_voices() -> list[str]:
    return voice_engine.KOKORO_VOICES


# ------------------------------------------------------------------- tools
@app.get("/api/tools", dependencies=[Depends(require_token)])
def tools() -> list[dict]:
    return TOOL_SPECS


# --------------------------------------------------------------------- web
class SearchBody(BaseModel):
    query: str


class ReadBody(BaseModel):
    url: str


@app.post("/api/web/search", dependencies=[Depends(require_token)])
async def web_search(body: SearchBody) -> dict:
    """Search the web, for Chat as well as Chisel.

    The same DuckDuckGo lookup the agent has always had, reachable over HTTP so
    a plain conversation can use it too. It needs no API key and no account,
    which is what makes it fit an application that is otherwise offline: the
    request goes out only when the user's question needs it.
    """
    from .agent.tools import _web_search

    try:
        return {"results": await _web_search(body.query.strip())}
    except Exception as exc:  # noqa: BLE001 - a failed lookup is not a crash
        raise HTTPException(status_code=502,
                            detail=f"The search did not work: {exc}") from exc


@app.post("/api/web/read", dependencies=[Depends(require_token)])
async def web_read(body: ReadBody) -> dict:
    """Fetch a page as readable prose.

    Extracted rather than raw: HTML markup would burn most of a local model's
    context window on things it cannot use.
    """
    from .agent.tools import _web_read

    try:
        return {"text": await _web_read(body.url.strip())}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502,
                            detail=f"That page could not be read: {exc}") from exc


# ----------------------------------------------------------- conversations
class ConversationBody(BaseModel):
    messages: list[dict] = []
    title: str | None = None
    model_path: str | None = None


@app.get("/api/conversations", dependencies=[Depends(require_token)])
def list_conversations() -> dict:  # noqa: D401
    """Every saved conversation, newest first.

    `unreadable` is reported rather than hidden. A conversation the user
    remembers, silently absent from the list, is worse than one shown as
    damaged — and it is the symptom of a key that changed, which they would
    otherwise have no way to notice.
    """
    try:
        result = conversations_store.listing()
    except conversations_store.EncryptionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"conversations": result.conversations, "unreadable": result.unreadable,
            "secure": result.secure, "backend": result.backend}


@app.post("/api/conversations", dependencies=[Depends(require_token)])
def create_conversation(body: ConversationBody) -> dict:
    conversation = conversations_store.create(body.messages, body.model_path)
    if body.title:
        conversation.title = body.title
    return conversations_store.save(conversation).to_dict()


@app.get("/api/conversations/{conversation_id}", dependencies=[Depends(require_token)])
def read_conversation(conversation_id: str) -> dict:
    try:
        conversation = conversations_store.load(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Not a conversation id")
    except Exception as exc:  # noqa: BLE001 - a damaged file is not a crash
        raise HTTPException(
            status_code=422,
            detail="This conversation could not be decrypted. It was written "
                   "with a different key, or the file has been altered.") from exc
    if conversation is None:
        raise HTTPException(status_code=404, detail="No such conversation")
    return conversation.to_dict()


@app.put("/api/conversations/{conversation_id}", dependencies=[Depends(require_token)])
def write_conversation(conversation_id: str, body: ConversationBody) -> dict:
    """Save, creating the file if this is the first write.

    Deliberately an upsert. The alternative is the client having to create
    before it can save, and a failed create silently costing the conversation
    the user is in the middle of.
    """
    try:
        existing = conversations_store.load(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Not a conversation id")
    except Exception:  # noqa: BLE001 - overwrite a file we cannot read
        existing = None

    if existing is None:
        conversation = conversations_store.Conversation(
            id=conversation_id, title=body.title or "",
            created=time.time(), updated=time.time(),
            messages=body.messages, model_path=body.model_path)
    else:
        existing.messages = body.messages
        existing.model_path = body.model_path or existing.model_path
        if body.title:
            existing.title = body.title
        conversation = existing
    return conversations_store.save(conversation).to_dict()


@app.delete("/api/conversations/{conversation_id}", dependencies=[Depends(require_token)])
def remove_conversation(conversation_id: str) -> dict:
    try:
        return {"deleted": conversations_store.delete(conversation_id)}
    except ValueError:
        raise HTTPException(status_code=400, detail="Not a conversation id")


# ------------------------------------------------------------------- agent
@app.websocket("/ws/agent")
async def agent_ws(websocket: WebSocket) -> None:
    if not require_token_ws(websocket.query_params.get("token", "")):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        raw = await websocket.receive_text()
        payload = json.loads(raw)
        goal = payload.get("goal", "")
        # A conversation handed over from Chat, so the plan is made knowing
        # what was already discussed rather than from one sentence in
        # isolation. Optional: a goal typed here directly has none.
        context = payload.get("context") or None
        if not isinstance(context, list):
            context = None
        if not goal:
            await websocket.send_json({"type": "error", "message": "Empty goal"})
            return

        await websocket.send_json({"type": "planning"})
        graph: ExecutionGraph = await orchestrator.plan(goal, context)

        async def on_update(g: ExecutionGraph) -> None:
            await websocket.send_json({"type": "graph", "graph": g.to_dict()})

        await orchestrator.run(graph, on_update)
        await websocket.send_json({"type": "done", "graph": graph.to_dict()})
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - report any planner/tool failure to the client
        # Some exceptions (httpx timeouts especially) stringify to nothing, which
        # would surface in the UI as a blank error. Always send something useful.
        message = str(exc).strip() or f"{type(exc).__name__} (no further detail)"
        try:
            await websocket.send_json({"type": "error", "message": message})
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    import atexit

    import uvicorn

    atexit.register(engine_manager.stop)

    port = 0
    for arg in sys.argv[1:]:
        if arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
    if not port:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

    # Handshake line consumed by the Tauri parent process to learn our port/token.
    print(json.dumps({"port": port, "token": settings.token}), flush=True)

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
