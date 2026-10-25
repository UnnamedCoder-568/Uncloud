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
@pytest.mark.parametrize('literal', [False, True])
def test_resume_retains_completed_steps_and_reasks_interrupted_waits(
    tmp_path, monkeypatch, status, waiting, expected, literal
):
    store = EventStore(tmp_path / "events.json")
    graph = ExecutionGraph("Synthetic saved work",
                           context=[{'role': 'user', 'content': 'Retained task context'}])
    graph.add_task(
        Task(
            "t1",
            "Read",
            "fs_read",
            {"path": "{{literal}}.txt" if literal else "test.txt"},
            status=status,
            output="completed output" if status == "completed" else None,
            literal_args=literal,
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
        assert seen[0].context == graph.context
        assert seen[0].tasks['t1'].literal_args == literal
        assert seen[0].tasks['t1'].args['path'] == ('{{literal}}.txt' if literal else 'test.txt')
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


def test_expired_approval_resumes_only_unexecuted_work_with_fresh_permission(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from uncloud_engine.agent.graph import EXPIRED_APPROVAL, PERMISSION_STOP

    store = EventStore(tmp_path / 'events.json')
    graph = ExecutionGraph('Saved file workflow', halt_reason=EXPIRED_APPROVAL)
    graph.add_task(Task('read', 'Read', 'fs_read', {'path': 'input.txt'},
                        status='completed', output='preserved input'))
    graph.add_task(Task('write', 'Write', 'fs_write', {'path': 'output.txt', 'content': 'result'},
                        dependencies=['read'], status='failed', error=EXPIRED_APPROVAL))
    graph.add_task(Task('verify', 'Verify', 'fs_read', {'path': 'output.txt'},
                        dependencies=['write'], status='failed', error=PERMISSION_STOP))
    store.run('expired', 'desktop', 'failed', graph.to_dict())
    ask = AsyncMock(return_value='no')
    monkeypatch.setattr(store, 'ask', ask)
    monkeypatch.setattr(main, 'user_events', store)
    monkeypatch.setattr(main, 'principal_of', lambda request: 'desktop')
    monkeypatch.setattr(main.engine_manager, 'active', SimpleNamespace(model_path='/test'))
    monkeypatch.setattr(main.automations_service, 'current', None)
    monkeypatch.setattr(main, '_agent_runs', {})
    monkeypatch.setattr(main.orchestrator, '_persist_plan', lambda *args: None)
    monkeypatch.setattr(tools, 'WORKSPACE_DIR', tmp_path)
    monkeypatch.setattr(tools.settings, '_data', {'agent_device_access': False})
    monkeypatch.setattr(tools, '_gate', Gate())

    async def check():
        response = await main.resume_agent(main.ResumeAgentBody(run_id='expired'), None)
        ident = response['run_id']
        assert ident != 'expired'
        await main._agent_runs[ident][1]
        saved = store.data['runs'][ident]['graph']
        assert saved['tasks']['read']['output'] == 'preserved input'
        assert saved['tasks']['read']['status'] == 'completed'
        assert saved['tasks']['write']['error'] == 'the user declined'
        assert store.data['runs']['expired']['status'] == 'resumed'
        assert ask.await_count == 1
        assert ask.call_args.args[1] == ident
        assert not (tmp_path / 'output.txt').exists()

    asyncio.run(check())


@pytest.mark.parametrize('reason', ['the user declined', 'Permission was revoked while waiting',
                                   'Exit 1: execution failed'])
def test_failed_runs_without_expired_approval_are_not_resumable(tmp_path, monkeypatch, reason):
    store = EventStore(tmp_path / 'events.json')
    graph = ExecutionGraph('Stopped work', halt_reason=reason)
    graph.add_task(Task('write', 'Write', 'fs_write', {'path': 'output.txt', 'content': 'result'},
                        status='failed', error=reason))
    store.run('failed', 'desktop', 'failed', graph.to_dict())
    monkeypatch.setattr(main, 'user_events', store)
    monkeypatch.setattr(main, 'principal_of', lambda request: 'desktop')
    monkeypatch.setattr(main, '_agent_runs', {})
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.resume_agent(main.ResumeAgentBody(run_id='failed'), None))
    assert error.value.status_code == 409
    assert not main._agent_runs


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
