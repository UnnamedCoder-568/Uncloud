"""Authenticated configuration/history surfaces, separate from inference streaming."""

from __future__ import annotations

import copy

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .inference_controls import apply, validate


class ProfileBody(BaseModel):
    values: dict = Field(default_factory=dict)
    preset: str = ""
    scope: str = "model"
    scope_id: str = ""


class ImportBody(BaseModel):
    version: int
    presets: dict[str, dict]


class PreferencesBody(BaseModel):
    values: dict


class EventBody(BaseModel):
    operation: str
    id: str = ""


class ResponseBody(BaseModel):
    answer: str


class DeliveryBody(BaseModel):
    id: str
    status: str


class CompactBody(BaseModel):
    messages: list[dict] = Field(max_length=10000)
    memory: str = Field(default="", max_length=100000)
    inference: dict = Field(default_factory=dict)


class PlanningContextBody(BaseModel):
    goal: str = Field(max_length=1000000)
    context: list[dict] = Field(default_factory=list, max_length=10000)
    inference: dict = Field(default_factory=dict)


def install(app, events, manager, require_token, require_desktop, principal_of):
    def configuration(owner: str) -> dict:
        with events.lock:
            return copy.deepcopy(
                events.data.get("inference", {}).get(
                    owner, {"version": 1, "presets": {}, "defaults": {}}
                )
            )

    @app.post("/api/agent/context", dependencies=[Depends(require_token)])
    async def planning_context(body: PlanningContextBody):
        from .agent.orchestrator import planning_messages
        from .context_count import count

        active = manager.active
        if not active:
            raise HTTPException(status_code=409, detail="Load the selected model first.")
        try:
            values = validate(body.inference)
            _, messages = planning_messages(body.goal, body.context, values)
            used = await count(active, messages, values)
            return {"used": used, "limit": active.context_limit}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/context/compact", dependencies=[Depends(require_token)])
    async def compact_context(body: CompactBody):
        from .compaction import compact

        active = manager.active
        if not active:
            raise HTTPException(status_code=409, detail="Load the selected model first.")
        try:
            values = validate(body.inference)
            apply(active, {}, values)
            return await compact(active, body.messages, body.memory, values)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/inference", dependencies=[Depends(require_token)])
    def inference(request: Request):
        active = manager.active
        return {
            "saved": configuration(principal_of(request)),
            "active": {
                "model_path": active.model_path,
                "engine": active.engine,
                "context_limit": active.context_limit,
                "profile": active.inference_profile,
            }
            if active
            else None,
        }

    @app.post("/api/inference/preview", dependencies=[Depends(require_token)])
    def preview_inference(body: ProfileBody):
        from .chat import model_payload

        if not manager.active:
            raise HTTPException(status_code=409, detail="Load the selected model first.")
        try:
            payload = model_payload(manager.active, [], inference=validate(body.values))
            return {
                k: v
                for k, v in payload.items()
                if k not in {"messages", "stream", "stream_options"}
            }
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/inference", dependencies=[Depends(require_token)])
    def save_inference(body: ProfileBody, request: Request):
        try:
            values = validate(body.values)
            if manager.active:
                apply(manager.active, {}, values)
            if body.scope not in {"model", "conversation", "project"}:
                raise ValueError("Choose model, conversation or project scope")
            scope_id = body.scope_id or (manager.active.model_path if manager.active else "")
            if not scope_id or len(scope_id) > 1024:
                raise ValueError("Choose a model or provide the scope identifier")
            if len(body.preset) > 80:
                raise ValueError("Preset names must be at most 80 characters")
            if body.preset in {
                "Auto",
                "Fast",
                "Balanced",
                "Deep",
                "Creative",
                "Deterministic",
                "Custom",
            }:
                raise ValueError("Choose a name different from the built-in presets")
            owner = principal_of(request)
            data = configuration(owner)
            if body.preset:
                data["presets"][body.preset] = values
            else:
                data["defaults"][f"{body.scope}:{scope_id}"] = values
            if len(data["presets"]) > 100 or len(data["defaults"]) > 300:
                raise ValueError("Remove unused presets or defaults before adding more")
            with events.lock:
                events.data.setdefault("inference", {})[owner] = data
                events._save()
            return data
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/api/inference/presets/{name}", dependencies=[Depends(require_token)])
    def delete_preset(name: str, request: Request):
        owner = principal_of(request)
        with events.lock:
            data = configuration(owner)
            data["presets"].pop(name, None)
            events.data.setdefault("inference", {})[owner] = data
            events._save()
            return data

    @app.post("/api/inference/import", dependencies=[Depends(require_token)])
    def import_presets(body: ImportBody, request: Request):
        try:
            if body.version != 1 or len(body.presets) > 100:
                raise ValueError("Use a version 1 preset file with at most 100 presets")
            checked = {}
            for name, values in body.presets.items():
                if (
                    not name.strip()
                    or len(name) > 80
                    or name
                    in {"Auto", "Fast", "Balanced", "Deep", "Creative", "Deterministic", "Custom"}
                ):
                    raise ValueError("Use a unique custom preset name (at most 80 characters)")
                checked[name] = validate(values)
                if manager.active:
                    apply(manager.active, {}, checked[name])
            owner = principal_of(request)
            with events.lock:
                data = configuration(owner)
                data["presets"].update(checked)
                if len(data["presets"]) > 100:
                    raise ValueError("Remove unused presets before adding more")
                events.data.setdefault("inference", {})[owner] = data
                events._save()
            return data
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/notifications", dependencies=[Depends(require_token)])
    def notifications(request: Request):
        return events.listing(principal_of(request))

    @app.post("/api/notifications/preferences", dependencies=[Depends(require_desktop)])
    def preferences(body: PreferencesBody):
        try:
            return events.set_preferences(body.values)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/notifications/mark", dependencies=[Depends(require_token)])
    def mark(body: EventBody, request: Request):
        try:
            events.mark(principal_of(request), body.id, body.operation)
            return {"ok": True}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown notification") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/notifications/native", dependencies=[Depends(require_desktop)])
    def native_batch():
        return events.native_batch()

    @app.post("/api/notifications/test", dependencies=[Depends(require_desktop)])
    def test_notice():
        import uuid

        return events.emit("background", "notification_test", uuid.uuid4().hex, target="settings")

    @app.post("/api/notifications/delivery", dependencies=[Depends(require_desktop)])
    def delivery(body: DeliveryBody):
        try:
            events.delivered(body.id, body.status)
            return {"ok": True}
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="Unknown delivery record") from exc

    @app.post("/api/notifications/update", dependencies=[Depends(require_desktop)])
    def update_notice(body: ResponseBody):
        import re

        if not re.fullmatch(r"\d+\.\d+\.\d+", body.answer):
            raise HTTPException(status_code=422, detail="Invalid release version")
        return events.emit("update", "updater", body.answer, target="settings")

    @app.post("/api/interactions/{request_id}/answer", dependencies=[Depends(require_token)])
    async def answer(request_id: str, body: ResponseBody, request: Request):
        try:
            events.answer(principal_of(request), request_id, body.answer)
            return {"accepted": True}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown request") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
