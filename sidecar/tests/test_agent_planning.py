import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from uncloud_engine.agent import orchestrator as module

SPECS = [{"id": "fs_write", "description": "Write a file", "args": ["path", "content"]}]
PLAN = {
    "tasks": {
        "t1": {
            "tool_id": "fs_write",
            "args": {"path": "x.txt", "content": "a } brace"},
            "dependencies": [],
        }
    }
}


def test_extract_plan_with_quoted_braces_and_other_json():
    text = '{"unrelated": true} then ```json\n' + json.dumps(PLAN) + "\n``` trailing { text"
    assert module._extract_json(text) == PLAN


@pytest.mark.parametrize(
    "tasks",
    [
        [],
        {},
        {"a": {"tool_id": "invented", "args": {}}},
        {"a": {"tool_id": "fs_write", "args": {}, "dependencies": ["missing"]}},
        {"a": {"tool_id": "fs_write", "args": {}, "dependencies": ["a"]}},
        {"a": {"tool_id": [], "args": {}}},
    ],
)
def test_invalid_plan_is_refused_before_execution(tasks):
    with pytest.raises(ValueError):
        module._graph_from_plan({"tasks": tasks}, "goal", SPECS)


def test_prose_is_repaired_without_executing_tools(monkeypatch):
    active = SimpleNamespace(base_url="http://model", engine="gguf")
    monkeypatch.setattr(module.engine_manager, "active", active)
    monkeypatch.setattr(module, "_active_profile", lambda: None)
    monkeypatch.setattr(module, "_active_tool_specs", lambda: SPECS)
    requests = []

    async def post(self, url, json):
        requests.append(json)
        content = (
            "The user wants a PDF on the desktop."
            if len(requests) == 1
            else __import__("json").dumps(PLAN)
        )
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    runner = AsyncMock()
    monkeypatch.setattr(module, "run_tool", runner)
    graph = asyncio.run(module.Orchestrator().plan("Save a file"))
    assert graph.tasks["t1"].args["content"] == "a } brace"
    assert len(requests) == 2
    assert "response_format" not in requests[0]  # Unknown backend capabilities are not guessed.
    assert "chat_template_kwargs" not in requests[0]  # Preserve native reasoning.
    assert "temperature" not in requests[0]  # No generic planner sampling override.
    runner.assert_not_called()


def test_reasoning_without_an_answer_is_not_executed(monkeypatch):
    monkeypatch.setattr(
        module.engine_manager, "active", SimpleNamespace(base_url="http://model", engine="gguf")
    )
    monkeypatch.setattr(module, "_active_profile", lambda: None)
    monkeypatch.setattr(module, "_active_tool_specs", lambda: SPECS)

    async def post(self, url, json):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning_content": __import__("json").dumps(PLAN),
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(RuntimeError, match="No tools were run"):
        asyncio.run(module.Orchestrator().plan("goal"))


@pytest.mark.parametrize("approved", [True, False])
def test_coding_plan_applies_real_files_only_after_approval(tmp_path, monkeypatch, approved):
    """Chat presentation changes must not turn Chisel into code-only replies."""
    from uncloud_engine.agent import approval, tools
    from uncloud_engine.core import Gate

    monkeypatch.setattr(tools, "WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(tools.settings, "_data", {"agent_device_access": False})
    monkeypatch.setattr(
        module.engine_manager, "active", SimpleNamespace(base_url="http://model", engine="gguf")
    )
    specs = [spec for spec in tools.TOOL_SPECS if spec["id"] in {"fs_write", "fs_read"}]
    monkeypatch.setattr(module, "_active_tool_specs", lambda: specs)
    monkeypatch.setattr(module.Orchestrator, "_persist_plan", lambda *args: None)
    content = "def square(number):\n    return number * number\n"
    plan = {"tasks": {
        "write": {"tool_id": "fs_write", "args": {"path": "src/square.py", "content": content}},
        "verify": {"tool_id": "fs_read", "args": {"path": "src/square.py"},
                   "dependencies": ["write"]},
    }}

    async def post(self, url, json):
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": __import__("json").dumps(plan)}}],
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    target = tmp_path / "src/square.py"
    asked = []

    async def ask(request):
        assert not target.exists()  # Still a proposal when permission is requested.
        asked.append(request.action)
        return "yes" if approved else "no"

    async def exercise():
        planner = module.Orchestrator()
        graph = await planner.plan("Create src/square.py with a square function")
        assert not target.exists()  # Planning does not perform the write.

        async def update(graph):
            pass

        with approval.asking(ask):
            await planner._execute(graph, update)
        return graph

    tools.install_gate(Gate())
    try:
        graph = asyncio.run(exercise())
    finally:
        tools.install_gate(None)
    assert asked == ["fs_write"]
    if approved:
        assert target.read_text() == content
        assert graph.tasks["verify"].output == content
        assert all(task.status == "completed" for task in graph.tasks.values())
    else:
        assert not target.exists()
        assert all(task.status == "failed" for task in graph.tasks.values())


def test_code_example_is_not_reported_as_an_executed_coding_task(monkeypatch):
    monkeypatch.setattr(
        module.engine_manager, "active", SimpleNamespace(base_url="http://model", engine="gguf")
    )
    monkeypatch.setattr(module, "_active_tool_specs", lambda: SPECS)
    runner = AsyncMock()
    monkeypatch.setattr(module, "run_tool", runner)

    async def post(self, url, json):
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": "```python\ndef square(n): return n * n\n```"}}],
        })

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(RuntimeError, match="No tools were run"):
        asyncio.run(module.Orchestrator().plan("Create src/square.py"))
    runner.assert_not_called()


def test_failed_dependency_is_reported_and_recovery_keeps_distinct_steps(monkeypatch):
    first = module._graph_from_plan(
        {
            "tasks": {
                "t1": {
                    "tool_id": "fs_write",
                    "args": {"path": "x", "content": "a"},
                    "dependencies": [],
                },
                "t2": {
                    "tool_id": "fs_write",
                    "args": {"path": "y", "content": "{t1}"},
                    "dependencies": ["t1"],
                },
            }
        },
        "goal",
        SPECS,
    )
    runs = []

    async def tool(tool_id, args):
        runs.append(args)
        if args["path"] == "x":
            raise RuntimeError("write failed")
        return "ok"

    monkeypatch.setattr(module, "run_tool", tool)
    planner = module.Orchestrator()
    monkeypatch.setattr(planner, "_persist_plan", lambda graph: None)

    async def update(graph):
        pass

    asyncio.run(planner._execute(first, update))
    assert first.tasks["t2"].status == "failed"
    assert len(runs) == 1
    recovered = module._graph_from_plan(
        {
            "tasks": {
                "t1": {
                    "tool_id": "fs_write",
                    "args": {"path": "z", "content": "ok"},
                    "dependencies": [],
                },
            }
        },
        "goal",
        SPECS,
    )

    async def replan(goal):
        return recovered

    monkeypatch.setattr(planner, "plan", replan)
    retry = asyncio.run(planner._replan(first, [first.tasks["t1"]], 1))
    assert "r1_t1" in retry.tasks
    assert "t1" in first.tasks
    asyncio.run(planner._execute(retry, update, into=first))
    assert first.tasks["r1_t1"].status == "completed"
