import asyncio
import time

import pytest

from uncloud_engine.automations import Automations, NeedsAttention


def store(tmp_path, execute):
    return Automations(tmp_path / "agents.enc", execute, key=lambda: b"x" * 32)


def test_due_encrypted_single_flight_and_recurring(tmp_path):
    async def check():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def execute(item, update):
            calls.append(item["id"])
            await update({"tasks": {"a": {"status": "completed"}}})
            entered.set()
            await release.wait()
            return {"tasks": {"a": {"status": "completed"}}}

        service = store(tmp_path, execute)
        first = service.create("private goal", "/model", "gguf", 3600, 10, ["fs_read"])
        service.create("other", "/model", "gguf", 0, 11, [])
        await service.tick(9)
        assert service.running is None
        await service.tick(11)
        await entered.wait()
        await service.tick(11)
        assert calls == [first["id"]]
        assert b"private goal" not in service.path.read_bytes()
        assert service.path.stat().st_mode & 0o777 == 0o600
        release.set()
        await service.running
        assert first["status"] == "completed" and not first["paused"]
        assert first["next_run"] > time.time() + 3500
        assert first["history"][0]["graph"]["tasks"]["a"]["status"] == "completed"
        assert first["progress"] is None  # a fresh recurring run must not skip prior work
        reloaded = store(tmp_path, execute)
        assert reloaded.items[first["id"]]["goal"] == "private goal"

    asyncio.run(check())


def test_pause_resume_preserves_checkpoint_and_once_finishes(tmp_path):
    async def check():
        entered = asyncio.Event()

        async def execute(item, update):
            await update({"tasks": {"a": {"status": "completed"}}})
            entered.set()
            await asyncio.Event().wait()

        service = store(tmp_path, execute)
        item = service.create("task", "/model", "mlx", 0, 1, [])
        await service.tick(2)
        await entered.wait()
        service.control(item["id"], "pause")
        await service.running
        assert item["paused"] and item["progress"]["tasks"]["a"]["status"] == "completed"
        service.control(item["id"], "resume")
        assert not item["paused"] and item["progress"]

        async def done(item, update):
            return {"tasks": {}}

        service.execute = done
        await service.tick(time.time() + 1)
        await service.running
        assert item["paused"] and item["status"] == "completed"

    asyncio.run(check())


def test_needs_attention_restart_and_corrupt_data(tmp_path):
    async def execute(item, update):
        raise NeedsAttention("Review access")

    async def check():
        service = store(tmp_path, execute)
        item = service.create("task", "/model", "gguf", 60, 1, [])
        await service.tick(2)
        await service.running
        assert item["paused"] and item["status"] == "needs_attention"
        item["status"] = "running"
        service.save()
        recovered = store(tmp_path, execute)
        assert recovered.items[item["id"]]["status"] == "needs_attention"
        service.path.write_bytes(b"broken")
        broken = store(tmp_path, execute)
        with pytest.raises(ValueError):
            broken.create("new", "/model", "gguf", 0, 1, [])
        assert service.path.read_bytes() == b"broken"
        assert not broken.items

    asyncio.run(check())


def test_invalid_interval_and_run_fresh(tmp_path):
    async def execute(item, update):
        return {}

    service = store(tmp_path, execute)
    with pytest.raises(ValueError):
        service.create("task", "/model", "gguf", 1, 1, [])
    item = service.create("task", "/model", "gguf", 0, 1, [])
    item["progress"] = {"old": True}
    service.control(item["id"], "run")
    assert item["progress"] is None
    service.control(item["id"], "delete")
    assert not service.items


def test_background_scope_never_inherits_grants_or_full_device_access(monkeypatch, tmp_path):
    from uncloud_engine.agent import tools
    from uncloud_engine.core import Gate, Mode, Risk

    original = Gate({Risk.READ: Mode.ALLOW, Risk.NETWORK: Mode.ASK})
    original._session_categories.add(Risk.NETWORK)
    monkeypatch.setattr(tools, "_gate", original)
    monkeypatch.setattr(tools, "WORKSPACE_DIR", tmp_path)
    from types import SimpleNamespace

    monkeypatch.setattr(tools, "settings", SimpleNamespace(agent_device_access=True))
    with tools.automation_scope(["fs_read"]):
        gate = tools.current_gate()
        assert gate.mode_for(Risk.READ) == Mode.ALLOW
        assert gate.mode_for(Risk.NETWORK) == Mode.DENY
        assert not gate._session_categories
        with pytest.raises(PermissionError):
            tools._resolve_path("/etc/passwd")
        assert tools._resolve_path("notes.txt") == tmp_path / "notes.txt"
        with pytest.raises(PermissionError):
            asyncio.run(tools.run_tool("shell", {"command": "echo no"}))
        original.set_mode(Risk.READ, Mode.DENY)
        assert tools.current_gate().mode_for(Risk.READ) == Mode.DENY
    assert tools.current_gate() is original


def test_api_validates_installed_model_and_scope(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from uncloud_engine import main

    async def execute(item, update):
        return {}

    monkeypatch.setattr(main, "automations_service", store(tmp_path, execute))
    monkeypatch.setattr(
        main,
        "scan_library_cached",
        lambda _: [SimpleNamespace(path="/model", engine="gguf", category="text", ready=True)],
    )
    client = TestClient(main.app)
    client.headers.update({"Authorization": f"Bearer {main.settings.token}"})
    body = dict(goal="Read notes", model_path="/model", engine="gguf", tools=["fs_read"])
    assert (
        client.post("/api/automations", json={**body, "model_path": "/unknown"}).status_code == 400
    )
    assert client.post("/api/automations", json={**body, "tools": ["shell"]}).status_code == 400
    response = client.post("/api/automations", json=body)
    assert response.status_code == 200
    ident = response.json()["id"]
    assert client.get("/api/automations").json()["items"][0]["id"] == ident
    assert client.post(f"/api/automations/{ident}/pause").json()["paused"]
    assert not client.post(f"/api/automations/{ident}/resume").json()["paused"]
    assert client.post(f"/api/automations/{ident}/delete").status_code == 200
    assert not client.get("/api/automations").json()["items"]
    assert TestClient(main.app).get("/api/automations").status_code == 403


def test_background_planner_exposes_only_scoped_tools(monkeypatch):
    from uncloud_engine.agent import orchestrator, tools

    with tools.automation_scope(["web_search", "fs_read"]):
        assert {t["id"] for t in orchestrator._active_tool_specs()} == {"web_search", "fs_read"}


def test_chat_and_model_changes_do_not_interrupt_background_run(monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from uncloud_engine import main

    monkeypatch.setattr(main, "automations_service", SimpleNamespace(current="busy"))
    for operation in [
        main.start_engine(main.EngineStartBody(model_path="/model", engine="gguf")),
        main.start_chat_run(main.ChatBody(messages=[]), None),
        main.chat(main.ChatBody(messages=[])),
    ]:
        with pytest.raises(HTTPException) as error:
            asyncio.run(operation)
        assert error.value.status_code == 409
    with pytest.raises(HTTPException):
        main.stop_engine()


def test_storage_failure_stops_scheduling_without_unhandled_task(tmp_path, monkeypatch):
    async def execute(item, update):
        raise AssertionError("No execution with unsaved state")

    async def check():
        service = store(tmp_path, execute)
        item = service.create("task", "/model", "gguf", 60, 1, [])

        def fail():
            raise OSError("Disk full")

        monkeypatch.setattr(service, "save", fail)
        await service.tick(2)
        await service.running
        assert service.error and service.current is None and item["paused"]

    asyncio.run(check())


def test_pause_before_first_instruction_releases_model_reservation(tmp_path):
    async def execute(item, update):
        raise AssertionError("Cancelled task must not execute")

    async def check():
        service = store(tmp_path, execute)
        item = service.create("task", "/model", "gguf", 0, 1, [])
        await service.tick(2)
        service.control(item["id"], "pause")
        await asyncio.gather(service.running, return_exceptions=True)
        assert service.current is None and item["paused"]
        await service.close()

    asyncio.run(check())
