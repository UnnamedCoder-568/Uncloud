import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from uncloud_engine import main
from uncloud_engine.agent import tools
from uncloud_engine.agent.graph import ExecutionGraph, Task
from uncloud_engine.core import Gate
from uncloud_engine.user_events import EventStore


@pytest.mark.parametrize(
    "status,waiting,expected", [("completed", False, "completed"), ("in_progress", True, "pending")]
)
def test_resume_retains_completed_steps_and_reasks_interrupted_waits(
    tmp_path, monkeypatch, status, waiting, expected
):
    store = EventStore(tmp_path / "events.json")
    graph = ExecutionGraph("Synthetic saved work")
    graph.add_task(
        Task(
            "t1",
            "Read",
            "fs_read",
            {"path": "test.txt"},
            status=status,
            output="completed output" if status == "completed" else None,
        )
    )
    store.run("old", "desktop", "interrupted", graph.to_dict())
    store.data["runs"]["old"]["previous_status"] = "waiting" if waiting else "running"
    monkeypatch.setattr(main, "user_events", store)
    monkeypatch.setattr(main, "principal_of", lambda request: "desktop")
    monkeypatch.setattr(main.engine_manager, "active", SimpleNamespace(model_path="/test"))
    monkeypatch.setattr(main.automations_service, "current", None)
    monkeypatch.setattr(main, "_agent_runs", {})
    monkeypatch.setattr(tools, "_gate", Gate())
    seen = []

    async def execute(graph, progress, **kwargs):
        seen.append(graph)

    monkeypatch.setattr(main.orchestrator, "run", execute)

    async def check():
        response = await main.resume_agent(main.ResumeAgentBody(run_id="old"), None)
        assert response["run_id"] != "old"
        await main._agent_runs[response["run_id"]][1]
        assert seen, store.data["runs"][response["run_id"]].get("error")
        assert seen[0].tasks["t1"].status == expected
        if expected == "completed":
            assert seen[0].tasks["t1"].output == "completed output"

    asyncio.run(check())


def test_resume_refuses_ambiguous_side_effect_and_foreign_owner(tmp_path, monkeypatch):
    store = EventStore(tmp_path / "events.json")
    graph = ExecutionGraph("Interrupted write")
    graph.add_task(Task("t1", "Write", "fs_write", {}, status="in_progress"))
    store.run("old", "desktop", "interrupted", graph.to_dict())
    monkeypatch.setattr(main, "user_events", store)
    monkeypatch.setattr(main, "principal_of", lambda request: "desktop")
    monkeypatch.setattr(main.engine_manager, "active", SimpleNamespace(model_path="/test"))
    monkeypatch.setattr(main.automations_service, "current", None)
    monkeypatch.setattr(main, "_agent_runs", {})
    with pytest.raises(HTTPException, match="will not be repeated"):
        asyncio.run(main.resume_agent(main.ResumeAgentBody(run_id="old"), None))
    assert not main._agent_runs
    monkeypatch.setattr(main, "principal_of", lambda request: "lan:other")
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.resume_agent(main.ResumeAgentBody(run_id="old"), None))
    assert error.value.status_code == 404


def test_native_default_reset_is_authoritative(tmp_path, monkeypatch):
    store = EventStore(tmp_path / "events.json")
    store.data["inference"] = {"desktop": {"defaults": {"model:/test": {"temperature": 0.9}}}}
    monkeypatch.setattr(main, "user_events", store)
    monkeypatch.setattr(main, "principal_of", lambda request: "desktop")
    monkeypatch.setattr(
        main.engine_manager,
        "active",
        SimpleNamespace(
            model_path="/test",
            engine="mlx",
            process=SimpleNamespace(poll=lambda: None),
            inference_profile={},
            adapter_path=None,
        ),
    )
    monkeypatch.setattr(main.automations_service, "current", None)
    monkeypatch.setattr(main, "_chat_runs", {})
    seen = []

    async def execute(run, body, active):
        seen.append(body.inference)

    monkeypatch.setattr(main, "_run_chat", execute)

    async def check():
        for inherit in (True, False):
            result = await main.start_chat_run(
                main.ChatBody(messages=[], inherit_defaults=inherit), None
            )
            await main._chat_runs[result["id"]].task
        assert seen == [{"temperature": 0.9}, {}]

    asyncio.run(check())
