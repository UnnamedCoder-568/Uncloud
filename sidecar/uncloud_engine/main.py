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

from .agent import approval as agent_approval
from .agent import tools as agent_tools
from .agent.graph import ExecutionGraph
from .agent.orchestrator import orchestrator
from .agent.tools import TOOL_SPECS
from . import profiles as uncloud_profiles
from .foundation import AuditLog, Denied, Gate, Mode, Risk, dump_policy, load_policy
from .foundation import Request as PermissionRequest
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
    from .foundation import describe as describe_effort

    return {"selected": settings.effort,
            "levels": describe_effort(_active_profile())}


@app.post("/api/effort", dependencies=[Depends(require_token)])
def set_effort(body: EffortBody) -> dict:
    from .foundation import parse as parse_effort

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
    from .legal import load_notices, summarise

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
    from .legal import describe

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
    """What can be connected, what is, and what each one would need.

    Unbuilt connectors are included on purpose. "Google Workspace needs an
    OAuth client you register with Google" and "we do not support that" send
    somebody in completely different directions, and only one of them is true.
    """
    from .integrations import describe
    from .integrations import credentials as broker

    return {"integrations": describe(),
            # Whether secrets are going into a real keychain. Somebody on a
            # machine with no secret service should be told, and get to decide,
            # rather than find out later.
            "keychain": broker.secure(),
            "credentials": broker.describe()}


@app.post("/api/integrations/connect", dependencies=[Depends(require_token)])
def integrations_connect(body: ConnectBody) -> dict:
    """Connect an integration. The secret goes in and never comes back out."""
    from .integrations import get
    from .integrations import credentials as broker

    integration = get(body.integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="no such integration")
    if not integration.available:
        raise HTTPException(status_code=400, detail=integration.needs
                            or "not available in this build")
    if integration.needs_credential and not body.secret:
        raise HTTPException(status_code=400,
                            detail=f"{integration.name} needs a credential")
    if not integration.needs_credential and not body.label:
        raise HTTPException(status_code=400,
                            detail=f"{integration.name} needs a folder")

    if integration.needs_credential:
        broker.store(body.integration_id, body.secret, label=body.label)
    else:
        # A folder is not a credential. It goes in the index, where it can be
        # displayed without an unlock prompt.
        broker.remember_path(body.integration_id, body.label)
    return integrations_list()


@app.post("/api/integrations/disconnect", dependencies=[Depends(require_token)])
def integrations_disconnect(body: ConnectBody) -> dict:
    from .integrations import credentials as broker

    broker.forget(body.integration_id)
    return integrations_list()


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
    #: fast | balanced | deep | maximum. Unreadable values fall back to the
    #: stored default rather than failing the request — effort is a preference,
    #: and a preference should never be able to break a conversation.
    effort: str = ""


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


@app.post("/api/image/generate", dependencies=[Depends(require_token)])
async def generate_image(body: ImageGenerateBody) -> dict:
    gated("generate_image", Risk.GENERATE,
          f"Generate an image: {body.prompt[:160]}",
          preview={"prompt": body.prompt}, origin="image")
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
            await websocket.send_json({"type": "error", "message": "Empty goal"})
            return

        await websocket.send_json({"type": "planning"})
        graph: ExecutionGraph = await orchestrator.plan(goal, context, effort=effort)

        async def on_update(g: ExecutionGraph) -> None:
            await websocket.send_json({"type": "graph", "graph": g.to_dict()})

        async def ask(request: PermissionRequest) -> str:
            """Put the question to whoever is watching this run.

            Blocking on purpose: the step does not proceed until an answer
            comes back, which is the whole point. `decide_or_refuse` puts a
            ceiling on the wait so a closed window becomes a refusal rather
            than a job that sits in progress for ever.
            """
            await websocket.send_json({"type": "approval", "request": {
                "action": request.action, "category": request.category.value,
                "summary": request.summary, "preview": request.preview,
                "mode": gate.mode_for(request.category).value,
            }})
            reply = json.loads(await websocket.receive_text())
            return str(reply.get("answer", "no"))

        with agent_approval.asking(ask):
            await orchestrator.run(graph, on_update, effort=effort)
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
