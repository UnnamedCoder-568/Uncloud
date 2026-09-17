from __future__ import annotations

import asyncio
import contextlib
import json
import re
import secrets
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import characters, product_studio, speech, voice_engine
from . import conversations as conversations_store
from . import music_engine as music_engine_mod
from . import narration_engine as narration_engine_mod
from . import profiles as uncloud_profiles
from . import video_engine as video_engine_mod
from .agent import approval as agent_approval
from .agent import tools as agent_tools
from .agent.graph import ExecutionGraph
from .agent.orchestrator import orchestrator
from .agent.tools import TOOL_SPECS
from .catalog import get_catalog, get_entry
from .chat import build_chat_payload
from .config import CONFIG_DIR, settings
from .core import AuditLog, Denied, Gate, Mode, Risk, dump_policy, load_policy
from .core import Request as PermissionRequest
from .core.integrations import credentials as integration_credentials
from .core.integrations import registry as integration_registry
from .downloader import download_manager
from .engines import engine_manager
from .image_engine import image_engine
from .library import invalidate_library_cache, scan_components, scan_library_cached
from .music_engine import music_engine
from .narration_engine import narration_engine

app = FastAPI(title="Uncloud Engine")
app.add_middleware(
    CORSMiddleware,
    # Tauri's production origin is platform-specific: Windows and Android use
    # the HTTP custom-protocol origin, while macOS/Linux use the tauri scheme.
    # Omitting the Windows origin leaves the healthy engine running but makes
    # WebView2 reject every API response as cross-origin traffic.
    allow_origins=[
        "tauri://localhost",
        "http://tauri.localhost",
        "http://localhost:1420",
        "http://127.0.0.1:1420",
    ],
    allow_methods=["*"], allow_headers=["*"],
)


# The LAN surface, when this process was started with --lan. None otherwise,
# and None means none of it exists: no routes, no listener, no cookie accepted.
_lan: Any = None
_job_owners: dict[str, dict[str, str]] = {
    "image": {}, "video": {}, "music": {}, "narration": {}, "speech": {},
}


def _same(given: str, expected: str) -> bool:
    """Constant-time, and safe on input that is not ASCII. `compare_digest` on
    str raises for non-ASCII, which turned a malformed header into a 500."""
    return secrets.compare_digest(given.encode("utf-8", "surrogateescape"),
                                  expected.encode("utf-8"))


def authorised(request: Any) -> bool:
    """The desktop shell's bearer token, or a device paired over the LAN."""
    header = request.headers.get("authorization") or ""
    if _same(header, f"Bearer {settings.token}"):
        return True
    if _lan is None:
        return False
    from .core.lan.web import session_of

    return session_of(request, _lan) is not None


def principal_of(request: Any) -> str:
    """Stable owner for state that must not cross desktop/LAN sessions."""
    if _same(request.headers.get("authorization") or "", f"Bearer {settings.token}"):
        return "desktop"
    if _lan is not None:
        from .core.lan.web import session_of

        if session := session_of(request, _lan):
            return f"lan:{session.id}"
    raise HTTPException(status_code=401, detail="Invalid or missing token")


def claim_jobs(kind: str, ids: list[str], request: Request) -> None:
    owner = principal_of(request)
    _job_owners[kind].update({job_id: owner for job_id in ids})


def require_job(kind: str, job_id: str, request: Request) -> None:
    """Keep progress and output from wandering into another paired session."""
    owner = _job_owners[kind].get(job_id)
    principal = principal_of(request)
    # Jobs created before this build have no owner; preserve desktop access but
    # never expose them to a paired device.
    if owner != principal and not (owner is None and principal == "desktop"):
        raise HTTPException(status_code=404, detail="Unknown job")


def require_token(request: Request) -> None:
    # Was a plain `!=`, which leaks how much of the token matched through
    # timing. Harmless on loopback with a per-launch token; not harmless once a
    # network can reach this.
    if not authorised(request):
        raise HTTPException(status_code=401, detail="Invalid or missing token")


def require_desktop(request: Request) -> None:
    """The desktop shell only — not a device paired over the network.

    For the few actions whose subject is the computer's own disk rather than
    the work done in the app: pointing at an arbitrary folder and writing
    files into it is a decision made at the computer, which is why the phone
    interface never offers it. Enforced here as well, because a hidden button
    is not a boundary.
    """
    if not _same(request.headers.get("authorization") or "", f"Bearer {settings.token}"):
        raise HTTPException(status_code=403,
                            detail="This is only available on the computer running Uncloud.")


def require_token_ws(websocket: WebSocket) -> bool:
    if _same(websocket.query_params.get("token", ""), settings.token):
        return True
    if _lan is None:
        return False
    from .core.lan.web import session_of

    return session_of(websocket, _lan) is not None


def principal_of_ws(websocket: WebSocket) -> str:
    if _same(websocket.query_params.get("token", ""), settings.token):
        return "desktop"
    if _lan is not None:
        from .core.lan.web import session_of

        if session := session_of(websocket, _lan):
            return f"lan:{session.id}"
    return ""


# ----------------------------------------------------------------- approvals
#
# One gate, built once, asked by every surface. The audit log is append-only
# and holds summaries rather than content: it records that a file was written,
# never what was written to it, so the trail never becomes a second copy of the
# user's work.
_audit = AuditLog(Path.home() / ".uncloud" / "audit.jsonl")


def _record(request: PermissionRequest, decision) -> None:
    _audit.write(request, decision)


gate = Gate(
    load_policy(settings.permission_policy),
    record=_record,
    on_policy_change=lambda policy: settings.set_permission_policy(dump_policy(policy)),
)
agent_tools.install_gate(gate)

async def _approve_integration_action(request: PermissionRequest):
    """Decide an integration action, or turn it into a 428.

    Deliberately the same path as every other gated action: `gated` raises
    NeedsApproval, the client renders the prompt, posts the answer and repeats
    the call. An integration-specific approval system is exactly what the
    architecture rules forbid.
    """
    gated(request.action, request.category, request.summary,
          preview=request.preview, origin=request.origin)
    return None


# Core owns the rule that every integration action is asked about; it does not
# own the round trip, which is an HTTP 428 here and something else in another
# host. Installed at import, so there is no window in which an action could run
# ungoverned — and Core raises rather than allowing if this never happened.
integration_registry.install_approver(_approve_integration_action)
integration_credentials.configure(CONFIG_DIR)


class NeedsApproval(HTTPException):
    """A person has to decide, and this is an HTTP request rather than a socket.

    428 rather than 403: the request was not refused, it is unfinished. The
    client renders the prompt, posts the answer, and repeats the call — which
    is what lets Chat's own tools go through the same gate as the agent's,
    instead of being the one surface that never asks (audit R2).
    """

    def __init__(self, request: PermissionRequest) -> None:
        super().__init__(status_code=428, detail={
            "approval": {
                "action": request.action,
                "category": request.category.value,
                "summary": request.summary,
                "preview": request.preview,
                "origin": request.origin,
                "mode": gate.mode_for(request.category).value,
            }})


def gated(action: str, category: Risk, summary: str, *, preview: dict | None = None,
          origin: str = "chat") -> None:
    """Decide an HTTP-triggered action, or ask the client to ask.

    Synchronous and non-blocking: the gate is consulted from policy alone, and
    when a person is needed the call is turned into a 428 rather than waiting.
    An HTTP handler that blocks on a human is a handler that holds a connection
    open for as long as somebody leaves the window.
    """
    request = PermissionRequest(action=action, category=category, summary=summary,
                                preview=preview or {}, origin=origin)
    settled = gate.check(request)
    if settled is None:
        raise NeedsApproval(request)
    try:
        gate.settle(request, settled)
    except Denied as exc:
        # A decision the user already made, reported as one. 403 rather than
        # 428: nothing is pending, and asking again would be pestering them
        # about something they settled.
        raise HTTPException(status_code=403, detail={
            "denied": {"action": request.action,
                       "category": request.category.value,
                       "reason": exc.reason}}) from exc


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.on_event("shutdown")
def _stop_mcp_servers() -> None:
    """Reap MCP subprocesses.

    A server left running after the application closed is somebody's laptop
    fan at three in the morning, and nothing about it points back here.
    """
    from .core import mcp

    mcp.shutdown()


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

    signals = [signal.SIGTERM, signal.SIGINT]
    sighup = getattr(signal, "SIGHUP", None)
    if sighup is not None:
        signals.append(sighup)

    for sig in signals:
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, _handle)


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
    from .budget import estimate_video_gb, memory_budget, resident_weights_gb, video_capability

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
        "check_updates": settings.check_updates,
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


class NoteBody(BaseModel):
    key: str
    value: str


@app.get("/api/notes", dependencies=[Depends(require_token)])
def list_notes(request: Request) -> list[dict]:
    from .agent import memory

    return memory.note_entries(namespace=principal_of(request))


@app.post("/api/notes", dependencies=[Depends(require_token)])
def save_note(body: NoteBody, request: Request) -> dict:
    from .agent import memory

    key = body.key.strip()[:120]
    value = body.value.strip()
    if not key or not value:
        raise HTTPException(status_code=400, detail="A note needs a title and content")
    memory.note_save(key, value, namespace=principal_of(request))
    return {"saved": True, "key": key}


@app.delete("/api/notes/{key}", dependencies=[Depends(require_token)])
def delete_note(key: str, request: Request) -> dict:
    from .agent import memory

    return {"deleted": memory.note_delete(key, namespace=principal_of(request))}


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
class PolicyBody(BaseModel):
    category: str
    mode: str


class AcceptBody(BaseModel):
    document_id: str
    #: The version the interface actually displayed. Required, so agreement can
    #: never be recorded for a page the person did not see.
    version: int


class AcknowledgeBody(BaseModel):
    model_id: str


class ConnectBody(BaseModel):
    integration_id: str
    #: A folder for a filesystem integration, an account name otherwise. Shown
    #: in the interface, so it must be something a person would recognise.
    label: str = ""
    #: Only ever travels inwards. It goes to the keychain and nothing returns
    #: it — not this route, not any other.
    secret: str = ""


class ProviderConfigBody(BaseModel):
    """An OAuth client the USER registered. Never one of ours."""

    integration_id: str
    client_id: str
    #: Empty for PKCE, which is the point of PKCE.
    client_secret: str = ""
    #: Overrides for a tenant-specific authority, which Microsoft needs.
    authorize_url: str = ""
    token_url: str = ""


class ScopeChoiceBody(BaseModel):
    integration_id: str
    #: Which optional scopes to ask for. A user who wants to read mail but not
    #: send it should be able to decline the second.
    scopes: list[str] = []


class RecipeBody(BaseModel):
    name: str = ""
    description: str = ""
    subject: str = ""
    #: Each step names exactly one of a capability or a tool.
    steps: list[dict] = []
    parameters: dict[str, str] = {}


class RunRecipeBody(BaseModel):
    values: dict[str, str] = {}


class McpRiskBody(BaseModel):
    tool: str
    #: A risk category, or empty to go back to Uncloud's own inference.
    risk: str = ""


class McpServerBody(BaseModel):
    id: str
    command: str
    args: list[str] = []
    cwd: str = ""
    label: str = ""
    #: May hold an API token, so it goes where secrets go.
    env: dict[str, str] = {}


class AnswerBody(BaseModel):
    action: str
    category: str
    summary: str = ""
    #: yes | no | always | never
    answer: str


class EffortBody(BaseModel):
    effort: str


def _active_profile():
    """The loaded model, described in the shared vocabulary, or None.

    Effort translation needs to know what the model accepts. Nothing is loaded
    on a fresh install, and a plan built without a model is still valid — it
    simply buys no native reasoning, which is what most models answer anyway.
    """
    from .library import scan_library

    active = engine_manager.active
    if not active:
        return None
    for model in scan_library(settings.models_dir):
        if model.path == active.model_path:
            return uncloud_profiles.from_local(model)
    return None


class TrainBody(BaseModel):
    model_path: str
    dataset_path: str
    preset: str = "standard"
    batch_size: int | None = None
    name: str = ""


@app.get("/api/training/presets", dependencies=[Depends(require_token)])
def training_presets() -> list[dict]:
    """Three configurations, named for what they do.

    Presets rather than a form: nobody arriving at this feature knows what a
    sensible rank is, and three cover almost everything people actually want.
    """
    from .training import jobs as training

    return training.presets()


@app.post("/api/training/prepare", dependencies=[Depends(require_token)])
def training_prepare(body: TrainBody) -> dict:
    """Everything that would happen, without starting it.

    Asked before the button is offered, so a dataset that cannot train or a
    machine that cannot hold the model is explained while the user is still
    deciding — rather than forty minutes in, which is the failure this whole
    subsystem is arranged around.
    """
    from .training import jobs as training

    try:
        return training.prepare(body.model_path, body.dataset_path, body.preset,
                                batch_size=body.batch_size)
    except training.Refused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/training", dependencies=[Depends(require_token)])
async def training_start(body: TrainBody) -> dict:
    """Start a run. Refuses before spawning anything if it will not work."""
    from .training import jobs as training

    gated("train", Risk.TRAIN,
          f"Fine-tune {Path(body.model_path).name} on "
          f"{Path(body.dataset_path).name}",
          preview={"model": body.model_path, "dataset": body.dataset_path,
                   "preset": body.preset},
          origin="training")
    try:
        job = await training.start(body.model_path, body.dataset_path, body.preset,
                                   batch_size=body.batch_size, name=body.name)
    except training.Refused as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job.to_dict()


@app.get("/api/training", dependencies=[Depends(require_token)])
def training_list() -> list[dict]:
    from .training import jobs as training

    return [job.to_dict() for job in training.all_jobs()]


@app.get("/api/training/{job_id}", dependencies=[Depends(require_token)])
def training_status(job_id: str) -> dict:
    from .training import jobs as training

    job = training.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such training run")
    return job.to_dict()


@app.post("/api/training/{job_id}/cancel", dependencies=[Depends(require_token)])
def training_cancel(job_id: str) -> dict:
    from .training import jobs as training

    return {"cancelled": training.cancel(job_id)}


@app.get("/api/adapters", dependencies=[Depends(require_token)])
def list_adapters() -> list[dict]:
    """Every adapter this machine has trained.

    Each carries a card saying which model it belongs to — an adapter with no
    provenance is unusable six weeks later, and it is not a model: it will not
    load without the one it was trained against.
    """
    from .training import jobs as training

    return training.adapters()


@app.delete("/api/adapters/{name}", dependencies=[Depends(require_token)])
def delete_adapter(name: str) -> dict:
    from .training import jobs as training

    gated("delete_adapter", Risk.DELETE, f"Delete the adapter {name}",
          origin="training")
    if not training.forget(name):
        raise HTTPException(status_code=404, detail="No such adapter")
    return {"deleted": True}


@app.get("/api/skills", dependencies=[Depends(require_token)])
def list_skills() -> list[dict]:
    """Every installed skill, with whether it can be offered here.

    Checked rather than assumed: a skill handed to the planner and then unable
    to run wastes a whole turn, and on a small model a turn is most of the
    budget. Unusable ones are still listed, with the reason — a skill an author
    can see is broken gets fixed; one that silently vanished does not.
    """
    from .agent.skills import discover
    from .agent.tools import auto_groups, tools_for
    from .budget import memory_budget

    groups = settings.agent_tool_groups
    if groups is None:
        active = engine_manager.active
        groups = auto_groups(active.model_path if active else None)
    available = {spec["id"] for spec in tools_for(groups)}

    profile = _active_profile()
    return [entry.to_dict() for entry in discover(
        tools=available,
        capabilities=set(profile.capabilities) if profile else None,
        memory_gb=memory_budget().get("budget_gb", 0.0),
        gate=gate,
    )]


@app.delete("/api/skills/{slug}", dependencies=[Depends(require_token)])
def delete_skill(slug: str) -> dict:
    from .agent.skills import skill_delete

    if not skill_delete(slug):
        raise HTTPException(status_code=404, detail="No such skill")
    return {"deleted": True}


@app.get("/api/effort", dependencies=[Depends(require_token)])
def effort_levels() -> dict:
    """Every level and what it would actually mean for the loaded model.

    Including which levels buy nothing extra here. Offering four options that
    behave identically is worse than saying so: a control that appears to work
    and does nothing teaches people the application is lying to them.
    """
    from .core import describe as describe_effort

    return {"selected": settings.effort,
            "levels": describe_effort(_active_profile())}


@app.post("/api/effort", dependencies=[Depends(require_token)])
def set_effort(body: EffortBody) -> dict:
    from .core import parse as parse_effort

    settings.set_effort(parse_effort(body.effort).value)
    return effort_levels()


@app.get("/api/permissions", dependencies=[Depends(require_token)])
def permissions() -> dict:
    """What is allowed, what asks, and what has been granted for this session."""
    return gate.describe()


@app.post("/api/permissions", dependencies=[Depends(require_token)])
def set_permission(body: PolicyBody) -> dict:
    """Change a category's policy.

    Returns the whole policy rather than an acknowledgement, because what was
    stored may be stricter than what was asked for: a shell can never be set to
    allow, and the interface has to show what actually took effect rather than
    what the user pressed.
    """
    try:
        category, mode = Risk(body.category), Mode(body.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    applied = gate.set_mode(category, mode)
    return {**gate.describe(), "applied": applied.value,
            "clamped": applied is not mode}


@app.post("/api/permissions/forget", dependencies=[Depends(require_token)])
def forget_session_grants() -> dict:
    """Drop every "yes, for this session" answer. The user's "ask me again"."""
    gate.forget_session()
    return gate.describe()


@app.post("/api/approvals/answer", dependencies=[Depends(require_token)])
def answer_approval(body: AnswerBody) -> dict:
    """Apply a person's answer to a request that came back as 428.

    The gate owns what an answer means — which session grant it creates, which
    policy it rewrites — so this route only carries it there. The client then
    repeats the original call, which now passes on policy alone.
    """
    try:
        category = Risk(body.category)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    request = PermissionRequest(action=body.action, category=category,
                                summary=body.summary, origin="chat")
    decision = gate.answer(request, body.answer)
    _audit.write(request, decision)
    return {"decision": decision.to_dict(), "permissions": gate.describe()}


@app.get("/api/audit", dependencies=[Depends(require_token)])
def audit(limit: int = 200) -> list[dict]:
    """What has been asked and decided, newest first.

    Summaries, never content. It records that a file was written, not what was
    written to it — an audit trail that duplicated the user's work would be a
    second thing to protect rather than a record of what happened.
    """
    return _audit.tail(limit=limit)


# --------------------------------------------------------------------- legal
def _profile(model_id: str):
    """One model in the shared vocabulary, catalogue or library.

    Both are searched because a licence question is just as real about
    something found on disk — more so, in fact: that is where `unverified`
    genuinely lives.
    """
    return next((p for p in model_profiles_objects() if p.id == model_id), None)


def model_profiles_objects() -> list:
    from .library import scan_library
    from .profiles import catalogue_profiles, from_local

    local = scan_library(settings.models_dir)
    installed = {m.catalog_id for m in local if m.catalog_id}
    out = list(catalogue_profiles(installed_ids=installed))
    seen = {p.id for p in out}
    for model in local:
        if model.catalog_id in installed or model.id in seen:
            continue
        out.append(from_local(model))
    return out


@app.get("/api/release", dependencies=[Depends(require_token)])
def release_readiness() -> dict:
    """What still has to be supplied before this build can be sold.

    Legal facts only the publisher can state — the entity, the address, the
    jurisdiction — plus any provider whose OAuth client has not been
    registered. Both are placeholders on purpose: an invented company name
    produces an agreement that looks binding and is not, and invented
    credentials belonging to Google or Slack would simply not work.

    Counted here because a blank like that reaches release by everybody
    assuming somebody else had filled it in.
    """
    from .core.integrations import registry as integrations
    from .core.legal import readiness, terms

    legal = readiness.summary(terms.load_all())

    needs_credentials, connected = [], []
    for provider in integrations._providers():
        try:
            connection = provider.connection()
        except Exception:  # noqa: BLE001 - a provider that cannot answer is not ready
            needs_credentials.append(provider.name)
            continue
        if connection.state.value == "not_configured":
            needs_credentials.append(provider.name)
        elif connection.state.value == "connected":
            connected.append(provider.name)

    return {
        "ready": legal["ready"] and not needs_credentials,
        "legal": legal,
        "integrations": {
            "needs_credentials": needs_credentials,
            "connected": connected,
            "note": "These need an OAuth client registered with the provider. "
                    "Uncloud does not own credentials belonging to them, and "
                    "shipping invented ones would not work.",
        },
    }


@app.get("/api/legal", dependencies=[Depends(require_token)])
def legal_state() -> dict:
    """Which agreements exist, which are outstanding, and what was accepted.

    Deliberately not part of `/api/settings` and deliberately not near
    `/api/permissions`. Agreeing to a document and approving an action are both
    a recorded yes, and keeping them at separate addresses is the cheapest
    reminder that one can never satisfy the other.
    """
    from .agreements import register

    return register(settings).state()


@app.get("/api/legal/notices/third-party", dependencies=[Depends(require_token)])
def third_party_notices(text: bool = False) -> dict:
    """Whose work is included, and under what terms."""
    from .core.legal import load_notices, summarise

    entries = load_notices()
    return {"summary": summarise(entries),
            "notices": [n.to_dict(text=text) for n in entries]}


@app.get("/api/legal/{document_id}", dependencies=[Depends(require_token)])
def legal_document(document_id: str) -> dict:
    """One document, with its text. Sent only on request — the state endpoint
    is polled, and three agreements would make every poll expensive."""
    from .agreements import register

    reg = register(settings)
    document = reg.get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="no such document")
    accepted = reg.store.accepted(document_id)
    return {**document.to_dict(body=True),
            "accepted": accepted.to_dict() if accepted else None}


@app.post("/api/legal/accept", dependencies=[Depends(require_token)])
def accept_terms(body: AcceptBody) -> dict:
    from .agreements import register

    try:
        register(settings).accept(body.document_id, body.version)
    except KeyError:
        raise HTTPException(status_code=404, detail="no such document") from None
    except ValueError as exc:
        # The interface displayed a version that is no longer current. Refused
        # rather than recorded against the new one, which would produce a
        # consent record describing a page nobody read.
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return register(settings).state()


@app.get("/api/models/{model_id}/licence", dependencies=[Depends(require_token)])
def model_licence(model_id: str) -> dict:
    """What this model's licence says, and how firmly to say it.

    Note what is absent: nothing here answers "may it be downloaded". Uncloud's
    catalogue carries no verified licence data at all, so almost every answer
    is `unverified` — which is the truth, is not a refusal, and must never be
    rendered as one.
    """
    from .agreements import ledger
    from .core.legal import describe

    profile = _profile(model_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="no such model")
    shown = describe(profile)
    return {**shown.to_dict(),
            "needs_acknowledgement": ledger(settings).needed(profile)}


@app.post("/api/models/licence/acknowledge", dependencies=[Depends(require_token)])
def acknowledge_model_licence(body: AcknowledgeBody) -> dict:
    """Record that the terms were shown. Grants nothing, widens nothing."""
    from .agreements import ledger

    profile = _profile(body.model_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="no such model")
    # The ledger picks the scope: a specific restriction is recorded against
    # this model, "nobody checked" is recorded once for the catalogue.
    made = ledger(settings).acknowledge(profile)
    settings.record_acknowledgement(made.model_id, made.to_dict())
    return model_licence(body.model_id)


# -------------------------------------------------------------- integrations
@app.get("/api/integrations", dependencies=[Depends(require_token)])
def integrations_list() -> dict:
    """Everything connectable, its state, and what each one can do.

    One call rather than one per row, and deliberately no network traffic: a
    settings page that made a token request per integration would be slow, burn
    rate limit, and refresh tokens as a side effect of being looked at.
    """
    from .core.integrations import capability_map, describe
    from .core.integrations import credentials as broker

    return {
        "integrations": describe(),
        # Which providers offer which capability, so the interface can show
        # what would actually work rather than what is installed.
        "capabilities": capability_map(connected_only=False),
        "connected_capabilities": capability_map(),
        # Whether secrets are going into a real keychain. Somebody on a machine
        # with no secret service should be told and get to decide.
        "keychain": broker.secure(),
    }


@app.post("/api/integrations/connect", dependencies=[Depends(require_token)])
def integrations_connect(body: ConnectBody) -> dict:
    """Connect with a pasted token, or point a local integration at a folder.

    The OAuth path is separate — see `/api/integrations/authorize` — because it
    opens a browser and waits, which is a different shape of request.
    """
    from .core.auth import AuthKind, connect_with_token
    from .core.integrations import credentials as broker
    from .core.integrations import get

    integration = get(body.integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="no such integration")
    if not integration.available:
        raise HTTPException(status_code=400,
                            detail=integration.needs or "not available here")

    if integration.auth_kind is AuthKind.NONE:
        if not body.label:
            raise HTTPException(status_code=400,
                                detail=f"{integration.name} needs a folder")
        # A folder is not a credential: it goes in the readable index so a
        # settings screen needs no unlock prompt to draw a list.
        broker.remember_path(body.integration_id, body.label)
        return integrations_list()

    if not body.secret:
        raise HTTPException(status_code=400,
                            detail=f"{integration.name} needs a token")
    account = body.label
    connect_with_token(body.integration_id, body.secret,
                       account=account or body.integration_id)
    # Ask the provider who this is, now that there is something to ask with.
    # Failure is not fatal: the connection works, the label is just less useful.
    if not account and hasattr(integration, "whoami"):
        try:
            discovered = integration.whoami()
            if discovered:
                connect_with_token(body.integration_id, body.secret,
                                   account=discovered)
        except Exception:  # noqa: BLE001 - a label is not worth failing over
            pass
    return integrations_list()


@app.post("/api/integrations/configure", dependencies=[Depends(require_token)])
def integrations_configure(body: ProviderConfigBody) -> dict:
    """Record an OAuth client the user registered with the provider.

    Uncloud ships none of these. An OAuth client is issued to a named party
    under Google's or Microsoft's terms, and fabricating one would be both a
    lie and a violation — so NOT_CONFIGURED is a real state and this is how it
    is left behind.
    """
    from .core.auth import ProviderConfig, configure_provider
    from .core.integrations import get

    integration = get(body.integration_id)
    if integration is None or integration.defaults is None:
        raise HTTPException(status_code=404,
                            detail="that integration does not use OAuth")
    defaults = integration.defaults
    configure_provider(
        ProviderConfig(
            provider=body.integration_id,
            client_id=body.client_id.strip(),
            has_secret=bool(body.client_secret),
            authorize_url=body.authorize_url.strip() or defaults.authorize_url,
            token_url=body.token_url.strip() or defaults.token_url,
            revoke_url=defaults.revoke_url,
            extra_authorize=dict(defaults.extra_authorize)),
        client_secret=body.client_secret)
    return integrations_list()


@app.post("/api/integrations/authorize", dependencies=[Depends(require_token)])
async def integrations_authorize(body: ScopeChoiceBody) -> dict:
    """Run an OAuth sign-in: open a browser, wait for the redirect, store.

    Blocking for as long as somebody takes to sign in, which is why it is its
    own route rather than part of connect — and bounded, so a forgotten browser
    tab does not hold a socket open all afternoon.
    """
    import asyncio
    import webbrowser

    from .core.auth import AuthError, Flow, store_oauth_result
    from .core.integrations import get

    integration = get(body.integration_id)
    if integration is None or integration.defaults is None:
        raise HTTPException(status_code=404,
                            detail="that integration does not use OAuth")

    from .core.auth import provider_config

    config = provider_config(body.integration_id, integration.defaults)
    wanted = tuple(body.scopes) or tuple(
        s.id for s in integration.scopes if s.required)
    try:
        flow = Flow(config, wanted)
        attempt = flow.begin()
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=exc.to_dict()) from exc

    webbrowser.open(attempt.authorize_url)
    try:
        # The listener blocks a thread; kept off the event loop so the rest of
        # the engine stays responsive while somebody signs in.
        code = await asyncio.to_thread(flow.await_redirect, attempt)
        tokens = await asyncio.to_thread(
            lambda: flow.exchange(attempt, code, client=_http_client()))
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=exc.to_dict()) from exc

    account = ""
    if hasattr(integration, "whoami"):
        store_oauth_result(body.integration_id, tokens, account="")
        try:
            account = integration.whoami()
        except Exception:  # noqa: BLE001 - a label is not worth failing over
            account = ""
    store_oauth_result(body.integration_id, tokens, account=account)
    return integrations_list()


@app.post("/api/integrations/disconnect", dependencies=[Depends(require_token)])
def integrations_disconnect(body: ConnectBody) -> dict:
    """Sign out, telling the provider if it will listen.

    Local state is cleared either way: a disconnect that failed because the
    provider was unreachable, and left the connection looking live, would be
    worse than one that tidied up locally.
    """
    from .core.auth import ProviderConfig, disconnect, forget_provider_config
    from .core.integrations import credentials as broker
    from .core.integrations import get

    integration = get(body.integration_id)
    defaults = (integration.defaults if integration and integration.defaults
                else ProviderConfig(provider=body.integration_id))
    disconnect(body.integration_id, defaults, client=_http_client())
    broker.forget(body.integration_id)
    if body.label == "forget-configuration":
        forget_provider_config(body.integration_id)
    return integrations_list()


def _http_client():
    import httpx

    return httpx.Client(timeout=30.0)


# ------------------------------------------------------------------- recipes
@app.get("/api/recipes", dependencies=[Depends(require_token)])
def recipes_list(subject: str = "") -> list[dict]:
    """Saved procedures, most trusted first.

    Listed rather than hidden because a recipe influences what happens: one
    that has quietly become wrong should be findable and editable, not
    invisible state that somebody has to guess at.
    """
    from . import workflows

    return [r.to_dict() for r in workflows.store().list(subject=subject)]


@app.get("/api/recipes/{recipe_id}", dependencies=[Depends(require_token)])
def recipe_read(recipe_id: str) -> dict:
    from . import workflows

    found = workflows.store().get(recipe_id)
    if found is None:
        raise HTTPException(status_code=404, detail="no such recipe")
    return found.to_dict()


@app.post("/api/recipes", dependencies=[Depends(require_token)])
def recipe_create(body: RecipeBody) -> dict:
    """Write a recipe, refusing one that could not run.

    Validated at save time rather than at run time: a recipe that fails on its
    third step has already done two things, and undoing those is not something
    this layer can offer.
    """
    from . import workflows

    try:
        return workflows.create(
            name=body.name, description=body.description,
            subject=body.subject, steps=body.steps,
            parameters=body.parameters).to_dict()
    except workflows.RecipeError as exc:
        raise HTTPException(status_code=400, detail=exc.to_dict()) from exc


@app.patch("/api/recipes/{recipe_id}", dependencies=[Depends(require_token)])
def recipe_update(recipe_id: str, body: RecipeBody) -> dict:
    from . import workflows

    changes: dict = {}
    if body.name:
        changes["name"] = body.name
    if body.description:
        changes["description"] = body.description
    if body.subject:
        changes["subject"] = body.subject
    if body.steps:
        changes["steps"] = body.steps
        changes["parameters"] = body.parameters
    try:
        return workflows.update(recipe_id, changes).to_dict()
    except workflows.RecipeError as exc:
        raise HTTPException(status_code=400, detail=exc.to_dict()) from exc


@app.delete("/api/recipes/{recipe_id}", dependencies=[Depends(require_token)])
def recipe_delete(recipe_id: str) -> dict:
    from . import workflows

    return {"deleted": workflows.store().delete(recipe_id)}


@app.post("/api/recipes/{recipe_id}/run", dependencies=[Depends(require_token)])
async def recipe_run(recipe_id: str, body: RunRecipeBody) -> dict:
    """Run a recipe's steps in order.

    Every step goes through `run_tool`, so a recipe containing a shell command
    prompts exactly as a shell command does. A recipe is a shortcut for
    somebody's fingers, never for the gate — otherwise "save this as a recipe"
    would be how you escape being asked.
    """
    from . import workflows
    from .core.recipes import record_use

    found = workflows.store().get(recipe_id)
    if found is None:
        raise HTTPException(status_code=404, detail="no such recipe")
    try:
        outcome = await workflows.run(found, body.values)
    except workflows.RecipeError as exc:
        raise HTTPException(status_code=400, detail=exc.to_dict()) from exc

    # Counted whether or not it worked. "Used ten times" is about how often
    # somebody reaches for it, and a recipe that keeps failing should still
    # look well-worn rather than untried.
    workflows.store().save(record_use(found, score=1.0 if outcome.ok else 0.0))
    return outcome.to_dict()


# ----------------------------------------------------------------------- MCP
@app.get("/api/mcp", dependencies=[Depends(require_token)])
def mcp_servers() -> list[dict]:
    """Configured MCP servers, with the risk each tool is governed as.

    The risk is shown rather than hidden because it is an inference about
    somebody else's code, and a user who disagrees should be able to see it
    instead of discovering it by being asked at the wrong moment.
    """
    from .core import mcp

    return mcp.describe()


@app.post("/api/mcp", dependencies=[Depends(require_token)])
def mcp_add(body: McpServerBody) -> list[dict]:
    from .core import mcp

    gated("mcp_configure", Risk.SETTINGS,
          f"Add the MCP server {body.label or body.id}",
          preview={"command": body.command, "args": " ".join(body.args)},
          origin="settings")
    mcp.configure(mcp.ServerConfig(
        id=body.id, command=body.command, args=tuple(body.args),
        cwd=body.cwd, label=body.label, env=dict(body.env)))
    return mcp.describe()


@app.post("/api/mcp/{server_id}/connect", dependencies=[Depends(require_token)])
def mcp_connect(server_id: str) -> dict:
    """Start a server and discover what it offers.

    Starting somebody else's program is a settings-level action and is asked
    about as one — before the process exists, not after.
    """
    from .core import mcp

    server = mcp.get(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="no such server")
    gated("mcp_start", Risk.SETTINGS,
          f"Start the MCP server {server.name}",
          preview={"command": server.config.command}, origin="settings")
    try:
        return mcp.connect(server_id).to_dict()
    except mcp.McpError as exc:
        raise HTTPException(status_code=400, detail=exc.to_dict()) from exc


@app.post("/api/mcp/{server_id}/classify", dependencies=[Depends(require_token)])
def mcp_classify(server_id: str, body: McpRiskBody) -> dict:
    """Say how one of a server's tools should be governed.

    The only path by which a classification can be LOWERED, and deliberately so:
    the user is the authority on their own machine, a server is not. Uncloud
    infers a category from the tool's name and admits when it guessed; this is
    how somebody corrects it rather than living with the guess.

    Changing how something is governed is itself a settings decision, so it is
    asked about — otherwise "reclassify then run" would be a way around the
    prompt you were trying to avoid.
    """
    from .core import mcp

    server = mcp.get(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="no such server")

    if not body.risk:
        gated("mcp_classify", Risk.SETTINGS,
              f"Let Uncloud classify {body.tool} again",
              preview={"server": server.name, "tool": body.tool},
              origin="settings")
        mcp.clear_override(server_id, body.tool)
        return server.to_dict()

    try:
        category = Risk(body.risk)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{body.risk!r} is not a risk category. Known: "
                   + ", ".join(sorted(r.value for r in Risk))) from exc

    gated("mcp_classify", Risk.SETTINGS,
          f"Govern {body.tool} as {category.value}",
          preview={"server": server.name, "tool": body.tool,
                   "was": server.classification(body.tool).risk.value,
                   "becomes": category.value},
          origin="settings")
    mcp.set_override(server_id, body.tool, category)
    return server.to_dict()


@app.post("/api/mcp/{server_id}/disconnect", dependencies=[Depends(require_token)])
def mcp_disconnect(server_id: str) -> list[dict]:
    from .core import mcp

    mcp.disconnect(server_id)
    return mcp.describe()


@app.delete("/api/mcp/{server_id}", dependencies=[Depends(require_token)])
def mcp_forget(server_id: str) -> list[dict]:
    from .core import mcp

    mcp.forget(server_id)
    return mcp.describe()


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


@app.get("/api/models/profiles", dependencies=[Depends(require_token)])
def model_profiles() -> list[dict]:
    """Every model Uncloud knows about, in the shared vocabulary.

    The catalogue and the library keep their own endpoints and their own
    shapes; this is the view both products can be reasoned about through —
    capabilities, cost, reasoning control and licence in one description. It
    touches no weights and loads nothing, so it is cheap enough to ask on
    every render.

    Installed state comes from the library scan rather than from the download
    record: what is on disk is the fact that matters, and a download row can
    outlive the folder it fetched.
    """
    from .library import scan_library
    from .profiles import catalogue_profiles, from_local

    local = scan_library(settings.models_dir)
    installed = {m.catalog_id for m in local if m.catalog_id}
    out = [p.to_dict() for p in catalogue_profiles(installed_ids=installed)]
    seen = {p["id"] for p in out}
    # Models found on disk that no catalogue entry claims. They are real and
    # runnable, and leaving them out would make this view disagree with the
    # Models tab.
    for model in local:
        if model.catalog_id in installed or model.id in seen:
            continue
        out.append(from_local(model).to_dict())
    return out


@app.get("/api/library", dependencies=[Depends(require_token)])
def library() -> list[dict]:
    return [m.to_dict() for m in scan_library_cached(settings.models_dir)]


# ------------------------------------------------------------ adding a model
class ModelPathBody(BaseModel):
    path: str


class ImportModelBody(BaseModel):
    path: str
    name: str = ""
    #: A base model chosen by the person, where the files leave it open.
    family: str = ""
    #: Look up missing configuration on huggingface.co. Off unless asked.
    online: bool = False
    #: What the person says the licence is. "unknown" unless they say otherwise;
    #: never filled in on their behalf.
    licence: str = "unknown"


def _existing(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not raw.strip() or not path.exists():
        raise HTTPException(status_code=404, detail="Nothing exists at that path.")
    return path


@app.post("/api/models/inspect", dependencies=[Depends(require_desktop)])
def inspect_model(body: ModelPathBody) -> dict:
    """What a file or folder is, what it is missing, and whether it will run.
    Reads headers and configs only, and writes nothing."""
    from .model_import import inspect

    return inspect(str(_existing(body.path)))


@app.post("/api/models/import", dependencies=[Depends(require_desktop)])
def import_model_route(body: ImportModelBody) -> dict:
    import os

    from .model_import import import_model, inspect

    path = _existing(body.path)
    preview = inspect(str(path))
    files = [s["file"] for s in preview["plan"] if s["action"] in ("create", "copy")]
    files.append("uncloud-model.json")
    # Writing into somebody's folder is a write, whoever asked for it: the same
    # gate as everything else that changes what is on disk.
    gated("import_model", Risk.WRITE,
          f"Add {path.name} to the library, writing {', '.join(files)} beside it",
          preview={"path": str(path), "files": files}, origin="models")
    if body.online:
        gated("model_lookup", Risk.NETWORK,
              f"Look up missing configuration for {path.name} on huggingface.co",
              preview={"host": "huggingface.co", "files": "JSON configuration only"},
              origin="models")

    result = import_model(str(path), name=body.name.strip()[:120], family=body.family,
                          online=body.online, licence=(body.licence or "unknown")[:80],
                          token=os.environ.get("HF_TOKEN") if body.online else None)
    model_path = Path(result["identification"]["path"])
    try:
        model_path.resolve().relative_to(settings.models_dir.resolve())
    except ValueError:
        settings.remember_imported(str(model_path))
    invalidate_library_cache()
    return result


@app.post("/api/models/forget", dependencies=[Depends(require_desktop)])
def forget_model(body: ModelPathBody) -> dict:
    """Stop listing a model added from outside the models folder. Its files,
    including the ones import wrote, are left exactly where they are."""
    forgotten = settings.forget_imported(body.path)
    invalidate_library_cache()
    return {"forgotten": forgotten}


# ------------------------------------------------------------------ updates
_update_checks = None


def update_checks():
    global _update_checks
    if _update_checks is None:
        from .update_checks import UpdateChecks

        _update_checks = UpdateChecks(CONFIG_DIR / "updates.json")
    return _update_checks


@app.get("/api/updates", dependencies=[Depends(require_token)])
def get_updates() -> dict:
    """Notices for this install, checking first if a check is due and enabled."""
    return update_checks().report(enabled=settings.check_updates)


@app.post("/api/updates/check", dependencies=[Depends(require_desktop)])
def check_updates_now() -> dict:
    """A check a person asked for, so it runs even with automatic checks off."""
    return update_checks().report(enabled=settings.check_updates, force=True)


class DismissBody(BaseModel):
    id: str


@app.post("/api/updates/dismiss", dependencies=[Depends(require_token)])
def dismiss_update(body: DismissBody) -> dict:
    """Hide a notice. A critical one comes back — Core decides that, not this."""
    update_checks().dismiss(body.id[:200])
    return update_checks().report(enabled=settings.check_updates)


class CheckUpdatesBody(BaseModel):
    enabled: bool


@app.post("/api/settings/check_updates", dependencies=[Depends(require_desktop)])
def set_check_updates(body: CheckUpdatesBody) -> dict:
    settings.set_check_updates(body.enabled)
    return {"check_updates": settings.check_updates}


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
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
        raise HTTPException(status_code=500, detail=str(exc)) from exc
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
    #: fast | balanced | deep | maximum. Unreadable values fall back to the
    #: stored default rather than failing the request — effort is a preference,
    #: and a preference should never be able to break a conversation.
    effort: str = ""


@dataclass
class ChatRun:
    id: str
    owner: str
    status: str = "running"
    frames: list[str] = field(default_factory=list)
    error: str = ""
    created: float = field(default_factory=time.time)
    task: asyncio.Task | None = field(default=None, repr=False)

    def public(self, cursor: int = 0) -> dict:
        start = max(0, min(cursor, len(self.frames)))
        return {"id": self.id, "status": self.status,
                "frames": self.frames[start:], "cursor": len(self.frames),
                "error": self.error}


_chat_runs: dict[str, ChatRun] = {}


def _chat_run(run_id: str, owner: str) -> ChatRun:
    run = _chat_runs.get(run_id)
    if run is None or run.owner != owner:
        raise HTTPException(status_code=404, detail="No such chat run")
    return run


async def _run_chat(run: ChatRun, body: ChatBody) -> None:
    """Own the model request independently of the browser connection.

    Mobile browsers freeze network readers when backgrounded.  Keeping the
    upstream stream here means generation continues and every frame is waiting
    when the page wakes again.
    """
    import httpx

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            payload = build_chat_payload(
                body.messages, temperature=body.temperature,
                max_tokens=body.max_tokens,
                engine=engine_manager.active.engine if engine_manager.active else "",
                effort=body.effort or settings.effort, model=_active_profile())
            if not engine_manager.active:
                raise RuntimeError("The text model was unloaded before this reply started.")
            async with client.stream(
                "POST", f"{engine_manager.active.base_url}/v1/chat/completions", json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        run.frames.append(line[6:].strip())
        run.status = "done"
    except asyncio.CancelledError:
        run.status = "cancelled"
        raise
    except Exception as exc:  # noqa: BLE001 - delivered to the owning UI
        run.status = "error"
        run.error = str(exc).strip() or type(exc).__name__


@app.post("/api/chat/runs", dependencies=[Depends(require_token)])
async def start_chat_run(body: ChatBody, request: Request) -> dict:
    if not engine_manager.active:
        raise HTTPException(status_code=400, detail="No text model loaded")
    # Finished runs are useful for a reconnect, but not forever.
    cutoff = time.time() - 3600
    for old_id, old in list(_chat_runs.items()):
        if old.created < cutoff and old.status != "running":
            _chat_runs.pop(old_id, None)
    run = ChatRun(id=uuid.uuid4().hex, owner=principal_of(request))
    _chat_runs[run.id] = run
    run.task = asyncio.create_task(_run_chat(run, body), name=f"chat-{run.id[:8]}")
    return run.public()


@app.get("/api/chat/runs/{run_id}", dependencies=[Depends(require_token)])
def chat_run_status(run_id: str, request: Request, cursor: int = 0) -> dict:
    return _chat_run(run_id, principal_of(request)).public(cursor)


@app.delete("/api/chat/runs/{run_id}", dependencies=[Depends(require_token)])
def cancel_chat_run(run_id: str, request: Request) -> dict:
    run = _chat_run(run_id, principal_of(request))
    if run.task and not run.task.done():
        run.task.cancel()
    return {"cancelled": True}


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
                effort=body.effort or settings.effort,
                model=_active_profile(),
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
    #: How many images. They render one after another, each on its own seed.
    count: int = 1


#: A batch is queued work the machine is committed to; past this it is better
#: started again than left running for an hour.
MAX_BATCH = 8


def _batch_seeds(seed: int | None, count: int) -> list[int]:
    """Consecutive seeds from the one given, or from a random start. Chosen up
    front, so any image in a batch can be made again from its own seed."""
    import secrets

    if not 1 <= count <= MAX_BATCH:
        raise HTTPException(status_code=400,
                            detail=f"Generate between 1 and {MAX_BATCH} images at a time")
    base = seed if seed is not None else secrets.randbelow(2**31 - MAX_BATCH)
    return [base + i for i in range(count)]


@app.post("/api/image/generate", dependencies=[Depends(require_token)])
async def generate_image(body: ImageGenerateBody, request: Request) -> dict:
    """Start one image or a batch. Returns the first job, with every job in
    the batch under `batch`. Approved once for the whole batch."""
    seeds = _batch_seeds(body.seed, body.count)
    gated("generate_image", Risk.GENERATE,
          (f"Generate {body.count} images: " if body.count > 1 else "Generate an image: ")
          + body.prompt[:160],
          preview={"prompt": body.prompt, "count": body.count}, origin="image")
    entry = get_entry(body.catalog_id) if body.catalog_id else None
    jobs = [image_engine.start(
        body.model_path, body.engine, body.prompt, negative_prompt=body.negative_prompt,
        steps=body.steps, guidance=body.guidance, width=body.width,
        height=body.height, seed=seed,
        mflux_cli=body.mflux_cli or (entry.mflux_cli if entry else "mflux-generate"),
        mflux_base=body.mflux_base or (entry.mflux_base if entry else None),
        lora_paths=body.lora_paths, lora_scales=body.lora_scales,
        text_encoder_path=body.text_encoder_path,
        label=f"{i + 1} of {body.count}" if body.count > 1 else None,
    ) for i, seed in enumerate(seeds)]
    claim_jobs("image", [job.id for job in jobs], request)
    return {**jobs[0].to_dict(), "batch": [j.to_dict() for j in jobs]}


UPLOAD_DIR = Path.home() / ".uncloud" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CHAT_DOCUMENT_TYPES = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".yaml", ".yml",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".xml", ".toml",
    ".ini", ".log", ".sql", ".rs", ".go", ".java", ".c", ".h", ".cpp",
    ".docx", ".xlsx", ".pptx",
}
MAX_CHAT_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_CHAT_DOCUMENT_CHARS = 120_000


@app.post("/api/chat/attachments", dependencies=[Depends(require_token)])
async def upload_chat_attachment(file: UploadFile = File(...)) -> dict:
    """Extract a bounded, user-visible document for a chat turn."""
    from .core.integrations.documents import extract

    name = Path(file.filename or "attachment.txt").name
    suffix = Path(name).suffix.lower()
    if suffix not in CHAT_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(f"{suffix or 'That file type'} cannot be read in Chat yet. "
                    "Use text, source code, Word, Excel, or PowerPoint."))
    raw = await file.read(MAX_CHAT_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_CHAT_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="That file is larger than 10 MB")
    dest = UPLOAD_DIR / f"chat-{uuid.uuid4().hex[:12]}{suffix}"
    try:
        dest.write_bytes(raw)
        text = extract(dest).strip()
    except Exception as exc:  # noqa: BLE001 - convert parser detail to a useful 400
        raise HTTPException(status_code=400, detail=f"{name} could not be read: {exc}") from exc
    finally:
        with contextlib.suppress(OSError):
            dest.unlink()
    if not text:
        raise HTTPException(status_code=400, detail=f"{name} contains no readable text")
    clipped = len(text) > MAX_CHAT_DOCUMENT_CHARS
    return {"name": name, "type": file.content_type or "application/octet-stream",
            "text": text[:MAX_CHAT_DOCUMENT_CHARS], "clipped": clipped}


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
    count: int = 1


@app.post("/api/image/edit", dependencies=[Depends(require_token)])
async def edit_image(body: ImageEditBody, request: Request) -> dict:
    seeds = _batch_seeds(body.seed, body.count)
    entry = get_entry(body.catalog_id) if body.catalog_id else None
    jobs = [image_engine.start_edit(
        body.model_path, body.prompt, body.reference_path,
        steps=body.steps, guidance=body.guidance, width=body.width, height=body.height,
        seed=seed, strength=body.strength,
        mflux_cli=entry.mflux_cli if entry else "mflux-generate-kontext",
        label=f"{i + 1} of {body.count}" if body.count > 1 else None,
    ) for i, seed in enumerate(seeds)]
    claim_jobs("image", [job.id for job in jobs], request)
    return {**jobs[0].to_dict(), "batch": [j.to_dict() for j in jobs]}


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
async def product_generate(body: ProductGenerateBody, request: Request) -> list[dict]:
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
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        shot = product_studio.get_shot(body.category, shot_id)
        width, height = product_studio.ASPECT_SIZES.get(
            shot.aspect if shot else "portrait", (768, 1024))
        job = image_engine.start_edit(
            body.model_path, instruction, body.reference_path,
            steps=body.steps, guidance=body.guidance,
            width=width, height=height, seed=body.seed,
            mflux_cli=cli, label=shot.name if shot else shot_id,
        )
        jobs.append(job.to_dict())
        claim_jobs("image", [job.id], request)
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
def export_images(body: ExportBody, request: Request) -> dict:
    """Copy finished renders out to a folder the user picked, named per shot."""
    import shutil

    dest = Path(body.dest_dir).expanduser()
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Cannot write to {dest}: {exc}") from exc

    written: list[str] = []
    for i, job_id in enumerate(body.job_ids, 1):
        require_job("image", job_id, request)
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
def list_image_jobs(request: Request) -> list[dict]:
    owner = principal_of(request)
    return [job.to_dict() for job in image_engine.jobs.values()
            if _job_owners["image"].get(job.id, "desktop") == owner]


@app.get("/api/image/jobs/{job_id}", dependencies=[Depends(require_token)])
def get_image_job(job_id: str, request: Request) -> dict:
    require_job("image", job_id, request)
    job = image_engine.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job")
    return job.to_dict()


@app.get("/api/image/output/{job_id}", dependencies=[Depends(require_token)])
def get_image_output(job_id: str, request: Request) -> FileResponse:
    require_job("image", job_id, request)
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
async def video_generate(body: VideoGenerateBody, request: Request) -> dict:
    from .video_engine import video_engine

    job = video_engine.start(
        body.model_path, body.prompt, negative_prompt=body.negative_prompt,
        frames=body.frames, fps=body.fps, width=body.width, height=body.height,
        steps=body.steps, guidance=body.guidance, seed=body.seed,
    )
    claim_jobs("video", [job.id], request)
    return job.to_dict()


@app.get("/api/video/jobs/{job_id}", dependencies=[Depends(require_token)])
def video_job(job_id: str, request: Request) -> dict:
    require_job("video", job_id, request)
    from .video_engine import video_engine

    job = video_engine.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="No such video job")
    return job.to_dict()


@app.get("/api/video/output/{job_id}", dependencies=[Depends(require_token)])
def video_output(job_id: str, request: Request) -> FileResponse:
    require_job("video", job_id, request)
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
async def generate_music_track(body: MusicGenerateBody, request: Request) -> dict:
    if body.sample_rate not in music_engine_mod.SAMPLE_RATES:
        raise HTTPException(
            status_code=400,
            detail=f"sample_rate must be one of {music_engine_mod.SAMPLE_RATES}")
    if body.bit_depth not in music_engine_mod.BIT_DEPTHS:
        raise HTTPException(
            status_code=400,
            detail=f"bit_depth must be one of {music_engine_mod.BIT_DEPTHS}")
    job = music_engine.start(
        body.model_dir, body.prompt, lyrics=body.lyrics, instrumental=body.instrumental,
        duration=body.duration, bpm=body.bpm, keyscale=body.keyscale, steps=body.steps,
        guidance=body.guidance, seed=body.seed, sample_rate=body.sample_rate,
        bit_depth=body.bit_depth, separate_stems=body.separate_stems,
        audio_format=body.audio_format,
    )
    claim_jobs("music", [job.id], request)
    return job.to_dict()


@app.get("/api/music/jobs", dependencies=[Depends(require_token)])
def list_music_jobs(request: Request) -> list[dict]:
    owner = principal_of(request)
    return [job.to_dict() for job in music_engine.jobs.values()
            if _job_owners["music"].get(job.id, "desktop") == owner]


@app.get("/api/music/jobs/{job_id}", dependencies=[Depends(require_token)])
def get_music_job(job_id: str, request: Request) -> dict:
    require_job("music", job_id, request)
    job = music_engine.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job")
    return job.to_dict()


@app.get("/api/music/audio/{job_id}", dependencies=[Depends(require_token)])
def get_music_audio(job_id: str, request: Request,
                    stem: str = Query(default="")) -> FileResponse:
    """Return the mixdown, or one separated stem when `stem` is given."""
    require_job("music", job_id, request)
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


class NarrationInstallBody(BaseModel):
    engine: str = "realtime"


@app.post("/api/narration/install", dependencies=[Depends(require_token)])
async def narration_install(body: NarrationInstallBody) -> StreamingResponse:
    """Set up one narration engine, streaming the log.

    Streamed rather than awaited, because building the environment takes
    minutes and a progress bar that says nothing for minutes is
    indistinguishable from a hang. The same reasoning as the first-run engine
    install, which already works this way.
    """
    name = body.engine
    if name not in narration_engine_mod.ENGINES:
        raise HTTPException(status_code=400, detail=f"No engine called {name!r}")

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_line(line: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, line)

    def run() -> None:
        try:
            narration_engine_mod.install_engine(name, on_line)
            loop.call_soon_threadsafe(queue.put_nowait, "__done__")
        except Exception as exc:  # noqa: BLE001 - reported to the user, not raised
            loop.call_soon_threadsafe(queue.put_nowait, f"__error__{exc}")

    async def stream():
        task = loop.run_in_executor(None, run)
        while True:
            line = await queue.get()
            if line == "__done__":
                yield 'data: {"done": true}\n\n'
                break
            if line.startswith("__error__"):
                yield f"data: {json.dumps({'error': line[len('__error__'):]})}\n\n"
                break
            yield f"data: {json.dumps({'line': line})}\n\n"
        await task

    return StreamingResponse(stream(), media_type="text/event-stream")


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
async def generate_narration(body: NarrationBody, request: Request) -> dict:
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    job = narration_engine.start(
        body.model_dir, body.text, voice_slug=body.voice_slug,
        sample_rate=body.sample_rate, bit_depth=body.bit_depth, cfg_scale=body.cfg_scale,
        ddpm_steps=body.ddpm_steps, audio_format=body.audio_format, engine=body.engine,
    )
    claim_jobs("narration", [job.id], request)
    return job.to_dict()


@app.get("/api/narration/jobs/{job_id}", dependencies=[Depends(require_token)])
def get_narration_job(job_id: str, request: Request) -> dict:
    require_job("narration", job_id, request)
    job = narration_engine.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job")
    return job.to_dict()


@app.get("/api/narration/audio/{job_id}", dependencies=[Depends(require_token)])
def get_narration_audio(job_id: str, request: Request) -> FileResponse:
    require_job("narration", job_id, request)
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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
    #: A voice saved in Voice. When set it decides the engine and everything
    #: else, and `voice` and `speed` are ignored.
    saved_voice: str = ""


@app.post("/api/voice/speak", dependencies=[Depends(require_token)])
async def speak_text(body: SpeakBody) -> FileResponse:
    """A reply read aloud. Every reply is kept as a clip, so one worth keeping
    can be found in Voice afterwards rather than lost with the conversation."""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    try:
        if body.saved_voice:
            clip = await asyncio.to_thread(speech.speak_reply, body.text, body.saved_voice)
        else:
            out_path = await asyncio.to_thread(voice_engine.speak, body.text, body.voice,
                                               body.speed)
            clip = speech.record_reply(out_path, body.text, body.voice)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface synthesis failures (e.g. missing espeak-ng)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(clip.path, media_type="audio/wav", headers={"X-Clip-Id": clip.id})


@app.get("/api/voice/voices", dependencies=[Depends(require_token)])
def list_voices() -> list[str]:
    return voice_engine.KOKORO_VOICES


# ------------------------------------------------------------------ speech
def _speech_call(fn, *args, **kwargs):
    """Speech errors a person can act on are 400s with the reason, not 500s."""
    try:
        return fn(*args, **kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/speech/engines", dependencies=[Depends(require_token)])
async def speech_engines() -> list[dict]:
    return await asyncio.to_thread(speech.engines)


@app.post("/api/speech/engines/{engine}/install", dependencies=[Depends(require_desktop)])
async def speech_install(engine: str) -> StreamingResponse:
    """Build an engine's environment, streaming the log. Desktop only: it
    installs software, which is not something a paired phone should start."""
    from .core.speech.engines import ENGINES as SPEECH_ENGINES

    if engine not in SPEECH_ENGINES:
        raise HTTPException(status_code=404, detail=f"No speech engine called {engine!r}")
    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_line(line: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, {"line": line})

    def run() -> None:
        try:
            speech.install(engine, on_line)
            loop.call_soon_threadsafe(queue.put_nowait, {"done": True})
        except Exception as exc:  # noqa: BLE001 - reported to the user, not raised
            loop.call_soon_threadsafe(queue.put_nowait, {"error": str(exc)})

    async def stream():
        task = loop.run_in_executor(None, run)
        while True:
            item = await queue.get()
            yield f"data: {json.dumps(item)}\n\n"
            if "line" not in item:
                break
        await task

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/speech/presets", dependencies=[Depends(require_token)])
async def speech_presets(engine: str, model_path: str) -> list[dict]:
    return await asyncio.to_thread(_speech_call, speech.presets, engine, model_path)


@app.get("/api/speech/voices", dependencies=[Depends(require_token)])
def speech_saved_voices() -> list[dict]:
    return [v.to_dict() for v in speech.saved_voices()]


class SpeechVoiceBody(BaseModel):
    name: str
    engine: str
    model_path: str = ""
    variant: str = ""
    preset: str = ""
    language: str = ""
    controls: dict[str, float] = {}
    notes: str = ""
    recording_path: str | None = None


@app.post("/api/speech/voices", dependencies=[Depends(require_token)])
async def speech_save_voice(body: SpeechVoiceBody) -> dict:
    voice = await asyncio.to_thread(
        _speech_call, speech.save_voice, name=body.name, engine=body.engine,
        model_path=body.model_path, variant=body.variant, preset=body.preset,
        language=body.language, controls=body.controls, notes=body.notes,
        recording_path=body.recording_path)
    return voice.to_dict()


@app.delete("/api/speech/voices/{slug}", dependencies=[Depends(require_token)])
def speech_delete_voice(slug: str) -> dict:
    if not speech.delete_voice(slug):
        raise HTTPException(status_code=404, detail="No such voice")
    return {"deleted": slug}


@app.post("/api/speech/recordings", dependencies=[Depends(require_token)])
async def speech_upload_recording(file: UploadFile = File(...)) -> dict:
    """Keep a recording to speak in, or to convert. Stored as WAV whatever it
    arrived as: a browser records webm, which the speech engines cannot read."""
    suffix = Path(file.filename or "recording.webm").suffix.lower() or ".webm"
    if suffix not in speech.AUDIO_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Unsupported audio type: {suffix}")
    raw = UPLOAD_DIR / f"rec-{uuid.uuid4().hex[:10]}{suffix}"
    raw.write_bytes(await file.read())

    def to_wav() -> tuple[Path, float]:
        import soundfile as sf
        from faster_whisper import decode_audio

        audio = decode_audio(str(raw), sampling_rate=24000)
        dest = raw.with_suffix(".wav")
        sf.write(str(dest), audio, 24000, subtype="PCM_16")
        if dest != raw:
            raw.unlink(missing_ok=True)
        return dest, len(audio) / 24000

    try:
        dest, seconds = await asyncio.to_thread(to_wav)
    except Exception as exc:  # noqa: BLE001 - an unreadable file is the user's to fix
        raw.unlink(missing_ok=True)
        raise HTTPException(status_code=400,
                            detail=f"Could not read that recording: {exc}") from exc
    return {"path": str(dest), "seconds": round(seconds, 1)}


class SpeechBody(BaseModel):
    text: str
    engine: str
    model_path: str = ""
    voice: str = ""
    saved_voice: str = ""
    recording_path: str | None = None
    language: str = ""
    variant: str = ""
    controls: dict[str, float] = {}
    format: str = "wav"
    sample_rate: int | None = None
    bit_depth: int = 24


@app.post("/api/speech/speak", dependencies=[Depends(require_token)])
def speech_speak(body: SpeechBody) -> dict:
    job = _speech_call(
        speech.start_speech, text=body.text, engine=body.engine, model_path=body.model_path,
        voice=body.voice, saved=body.saved_voice, recording_path=body.recording_path,
        language=body.language, variant=body.variant, controls=body.controls,
        audio_format=body.format, sample_rate=body.sample_rate, bit_depth=body.bit_depth)
    return job.to_dict()


class SpeechConvertBody(BaseModel):
    model_path: str
    source_path: str
    saved_voice: str = ""
    recording_path: str | None = None


@app.post("/api/speech/convert", dependencies=[Depends(require_token)])
def speech_convert(body: SpeechConvertBody) -> dict:
    job = _speech_call(speech.start_conversion, model_path=body.model_path,
                       source_path=body.source_path, saved=body.saved_voice,
                       recording_path=body.recording_path)
    return job.to_dict()


@app.get("/api/speech/jobs/{job_id}", dependencies=[Depends(require_token)])
def speech_job(job_id: str) -> dict:
    job = speech.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such job")
    return job.to_dict()


@app.get("/api/speech/clips", dependencies=[Depends(require_token)])
def speech_clips(kind: str = "") -> list[dict]:
    return [c.to_dict() for c in speech.clips(kind)]


@app.get("/api/speech/clips/{clip_id}/audio", dependencies=[Depends(require_token)])
def speech_clip_audio(clip_id: str) -> FileResponse:
    clip = _speech_call(speech.clip, clip_id)
    return FileResponse(clip.path)


class SpeechClipBody(BaseModel):
    name: str


@app.patch("/api/speech/clips/{clip_id}", dependencies=[Depends(require_token)])
def speech_rename_clip(clip_id: str, body: SpeechClipBody) -> dict:
    return _speech_call(speech.rename_clip, clip_id, body.name).to_dict()


@app.delete("/api/speech/clips/{clip_id}", dependencies=[Depends(require_token)])
def speech_delete_clip(clip_id: str) -> dict:
    _speech_call(speech.delete_clip, clip_id)
    return {"deleted": clip_id}


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
    gated("web_search", Risk.NETWORK,
          f"Search the web for: {body.query}", preview={"query": body.query})
    from .agent.tools import _web_search

    try:
        return {"results": await _web_search(body.query.strip())}
    except Exception as exc:  # noqa: BLE001 - a failed lookup is not a crash
        raise HTTPException(status_code=502,
                            detail=f"The search did not work: {exc}") from exc


@app.post("/api/web/images", dependencies=[Depends(require_token)])
async def web_images(body: SearchBody) -> dict:
    """Find pictures on the web, for showing examples.

    DuckDuckGo's image endpoint, which needs a token it hands out on the plain
    search page first. No API key and no account, which is what keeps this
    usable in an application that is otherwise offline.

    Only the thumbnail URLs are returned. They are served by the search engine
    rather than by the origin site, so displaying one does not announce the
    user to whichever site happens to host the picture.
    """
    gated("web_images", Risk.NETWORK,
          f"Search the web for pictures of: {body.query}",
          preview={"query": body.query})
    import re
    from urllib.parse import quote

    import httpx

    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Empty query")

    headers = {"User-Agent": "Mozilla/5.0 (compatible; Uncloud/0.1)"}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=25,
                                     headers=headers) as client:
            page = await client.get(f"https://duckduckgo.com/?q={quote(query)}&iax=images&ia=images")
            token = re.search(r"vqd=[\"']?([\d-]+)", page.text)
            if not token:
                return {"images": []}
            resp = await client.get(
                "https://duckduckgo.com/i.js",
                params={"l": "us-en", "o": "json", "q": query,
                        "vqd": token.group(1), "f": ",,,", "p": "1"},
                headers={**headers, "Referer": "https://duckduckgo.com/"},
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:  # noqa: BLE001 - a failed lookup is not a crash
        raise HTTPException(status_code=502,
                            detail=f"The image search did not work: {exc}") from exc

    images = []
    for item in (payload.get("results") or [])[:8]:
        thumbnail = item.get("thumbnail")
        if not thumbnail:
            continue
        images.append({
            "thumbnail": thumbnail,
            "source": item.get("url") or item.get("image") or "",
            "title": (item.get("title") or "").strip(),
        })
    return {"images": images}


@app.post("/api/web/read", dependencies=[Depends(require_token)])
async def web_read(body: ReadBody) -> dict:
    """Fetch a page as readable prose.

    Extracted rather than raw: HTML markup would burn most of a local model's
    context window on things it cannot use.
    """
    gated("web_read", Risk.NETWORK, f"Read this page: {body.url}",
          preview={"url": body.url})
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
def list_conversations(request: Request) -> dict:  # noqa: D401
    """Every saved conversation, newest first.

    `unreadable` is reported rather than hidden. A conversation the user
    remembers, silently absent from the list, is worse than one shown as
    damaged — and it is the symptom of a key that changed, which they would
    otherwise have no way to notice.
    """
    try:
        result = conversations_store.listing(owner=principal_of(request))
    except conversations_store.EncryptionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"conversations": result.conversations, "unreadable": result.unreadable,
            "secure": result.secure, "backend": result.backend}


@app.post("/api/conversations", dependencies=[Depends(require_token)])
def create_conversation(body: ConversationBody, request: Request) -> dict:
    conversation = conversations_store.create(
        body.messages, body.model_path, owner=principal_of(request))
    if body.title:
        conversation.title = body.title
    return conversations_store.save(conversation).to_dict()


@app.get("/api/conversations/{conversation_id}", dependencies=[Depends(require_token)])
def read_conversation(conversation_id: str, request: Request) -> dict:
    try:
        conversation = conversations_store.load(
            conversation_id, owner=principal_of(request))
    except ValueError:
        # `from None`, unlike everywhere else here: a malformed id is a
        # validation failure whose original exception says nothing the message
        # does not, and chaining it puts a parser traceback in the log for
        # somebody mistyping a URL.
        raise HTTPException(status_code=400,
                            detail="Not a conversation id") from None
    except Exception as exc:  # noqa: BLE001 - a damaged file is not a crash
        raise HTTPException(
            status_code=422,
            detail="This conversation could not be decrypted. It was written "
                   "with a different key, or the file has been altered.") from exc
    if conversation is None:
        raise HTTPException(status_code=404, detail="No such conversation")
    return conversation.to_dict()


@app.put("/api/conversations/{conversation_id}", dependencies=[Depends(require_token)])
def write_conversation(conversation_id: str, body: ConversationBody, request: Request) -> dict:
    """Save, creating the file if this is the first write.

    Deliberately an upsert. The alternative is the client having to create
    before it can save, and a failed create silently costing the conversation
    the user is in the middle of.
    """
    try:
        owner = principal_of(request)
        existing = conversations_store.load(conversation_id, owner=owner)
    except ValueError:
        # `from None`, unlike everywhere else here: a malformed id is a
        # validation failure whose original exception says nothing the message
        # does not, and chaining it puts a parser traceback in the log for
        # somebody mistyping a URL.
        raise HTTPException(status_code=400,
                            detail="Not a conversation id") from None
    except Exception:  # noqa: BLE001 - handled below as occupied, never overwritten
        existing = None

    if existing is None:
        if conversations_store.exists(conversation_id):
            # Occupied by another paired session (or unreadable). Never turn an
            # upsert into a cross-device overwrite oracle.
            raise HTTPException(status_code=404, detail="No such conversation")
        conversation = conversations_store.Conversation(
            id=conversation_id, title=body.title or "",
            created=time.time(), updated=time.time(),
            messages=body.messages, model_path=body.model_path, owner=owner)
    else:
        existing.messages = body.messages
        existing.model_path = body.model_path or existing.model_path
        if body.title:
            existing.title = body.title
        conversation = existing
    return conversations_store.save(conversation).to_dict()


@app.delete("/api/conversations/{conversation_id}", dependencies=[Depends(require_token)])
def remove_conversation(conversation_id: str, request: Request) -> dict:
    try:
        return {"deleted": conversations_store.delete(
            conversation_id, owner=principal_of(request))}
    except ValueError:
        # `from None`, unlike everywhere else here: a malformed id is a
        # validation failure whose original exception says nothing the message
        # does not, and chaining it puts a parser traceback in the log for
        # somebody mistyping a URL.
        raise HTTPException(status_code=400,
                            detail="Not a conversation id") from None


# ------------------------------------------------------------------- agent
_agent_runs: dict[str, tuple[str, asyncio.Task]] = {}


@app.delete("/api/agent/runs/{run_id}", dependencies=[Depends(require_token)])
def cancel_agent_run(run_id: str, request: Request) -> dict:
    found = _agent_runs.get(run_id)
    if found is None or found[0] != principal_of(request):
        raise HTTPException(status_code=404, detail="No such agent run")
    found[1].cancel()
    return {"cancelled": True}


@app.websocket("/ws/agent")
async def agent_ws(websocket: WebSocket) -> None:
    if not require_token_ws(websocket):
        await websocket.close(code=4401)
        return
    owner = principal_of_ws(websocket)
    await websocket.accept()
    run_id = ""
    graph: ExecutionGraph | None = None
    connected = True

    async def send(event: dict) -> bool:
        """Best-effort progress delivery; the run belongs to the engine.

        Mobile browsers routinely suspend their socket while backgrounded.
        Losing that viewer must not kill a safe, already-running plan.
        """
        nonlocal connected
        if not connected:
            return False
        try:
            await websocket.send_json(event)
            return True
        except (WebSocketDisconnect, RuntimeError, OSError):
            connected = False
            return False

    try:
        raw = await websocket.receive_text()
        payload = json.loads(raw)
        goal = payload.get("goal", "")
        run_id = str(payload.get("run_id") or uuid.uuid4().hex)
        if not re.fullmatch(r"[a-fA-F0-9-]{16,64}", run_id):
            await send({"type": "error", "message": "Invalid run id"})
            return
        current = asyncio.current_task()
        if current is not None:
            _agent_runs[run_id] = (owner, current)
        # Effort travels with the run rather than being read from settings, so
        # a person can spend more on one task without changing their default.
        effort = payload.get("effort") or settings.effort
        # A conversation handed over from Chat, so the plan is made knowing
        # what was already discussed rather than from one sentence in
        # isolation. Optional: a goal typed here directly has none.
        context = payload.get("context") or None
        if not isinstance(context, list):
            context = None
        if not goal:
            await send({"type": "error", "message": "Empty goal"})
            return

        await send({"type": "planning"})
        graph = await orchestrator.plan(goal, context, effort=effort)

        async def on_update(g: ExecutionGraph) -> None:
            await send({"type": "graph", "graph": g.to_dict()})

        async def ask(request: PermissionRequest) -> str:
            """Put the question to whoever is watching this run.

            Blocking on purpose: the step does not proceed until an answer
            comes back, which is the whole point. `decide_or_refuse` puts a
            ceiling on the wait so a closed window becomes a refusal rather
            than a job that sits in progress for ever.
            """
            nonlocal connected
            offered = await send({"type": "approval", "request": {
                "action": request.action, "category": request.category.value,
                "summary": request.summary, "preview": request.preview,
                "mode": gate.mode_for(request.category).value,
            }})
            if not offered:
                return "no"
            try:
                reply = json.loads(await websocket.receive_text())
            except (WebSocketDisconnect, RuntimeError, OSError, json.JSONDecodeError):
                connected = False
                return "no"
            return str(reply.get("answer", "no"))

        with agent_approval.asking(ask):
            await orchestrator.run(graph, on_update, effort=effort)
        await send({"type": "done", "graph": graph.to_dict()})
    except asyncio.CancelledError:
        if graph is not None:
            for task in graph.tasks.values():
                if task.status in ("pending", "in_progress"):
                    task.status = "failed"
                    task.error = "Stopped by the user"
        with contextlib.suppress(Exception):
            await send({"type": "cancelled",
                        "graph": graph.to_dict() if graph else None})
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - report any planner/tool failure to the client
        # Some exceptions (httpx timeouts especially) stringify to nothing, which
        # would surface in the UI as a blank error. Always send something useful.
        message = str(exc).strip() or f"{type(exc).__name__} (no further detail)"
        with contextlib.suppress(Exception):
            await send({"type": "error", "message": message})
    finally:
        if run_id:
            _agent_runs.pop(run_id, None)


def _web_dist() -> Path | None:
    """The built frontend, for serving to other devices.

    The desktop shell passes where its bundled copy is; a checkout falls back
    to the Vite output beside the engine.
    """
    import os

    for candidate in (os.environ.get("UNCLOUD_WEB_DIST"),
                      Path(__file__).resolve().parents[2] / "uncloud" / "dist"):
        if candidate and (Path(candidate) / "index.html").is_file():
            return Path(candidate)
    return None


def main() -> None:
    import atexit

    from .core.lan import Lan
    from .core.lan import run as lan_run
    from .core.lan import web as lan_web

    argv = sys.argv[1:]
    verb = lan_run.command(argv, config_dir=CONFIG_DIR, product="Uncloud", slug="uncloud")
    if verb is not None:
        sys.exit(verb)

    atexit.register(engine_manager.stop)

    port = 0
    if (given := lan_run.option(argv, "port")) is not None:
        port = int(given)
    if not port:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

    global _lan
    if lan_run.lan_requested(argv):
        from .core.lan import candidates

        found = candidates()
        _lan = Lan(product="Uncloud", slug="uncloud", config_dir=CONFIG_DIR,
                   port=lan_run.lan_port("uncloud", lan_run.option(argv, "lan-port"),
                                         [i.address for i in found]),
                   chosen=found)
        app.include_router(lan_web.router(_lan, authorised))
        dist = _web_dist()
        if dist is not None:
            lan_web.serve_frontend(app, dist)

    # Handshake line consumed by the Tauri parent process to learn our port/token.
    print(json.dumps({"port": port, "token": settings.token}), flush=True)

    if _lan is not None:
        offer = _lan.offer()
        # Only to a terminal. When the desktop app started this, stderr may be
        # captured to a log that outlives the code; the app asks for a code over
        # its own authenticated connection instead.
        if sys.stderr.isatty():
            print(_lan.banner(offer), file=sys.stderr, flush=True)
        else:
            print("Uncloud is on the local network. Run `pair` in a terminal, or "
                  "open Settings > Devices, for a pairing code.", file=sys.stderr, flush=True)
        if _web_dist() is None:
            print("No built frontend was found, so paired devices get the API only. "
                  "Build it with `npm run build` in uncloud/.", file=sys.stderr, flush=True)

    lan_run.serve(app, port=port, lan=_lan)


if __name__ == "__main__":
    main()
