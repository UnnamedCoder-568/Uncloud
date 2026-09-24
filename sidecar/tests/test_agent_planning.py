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
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert requests[0]["chat_template_kwargs"]["enable_thinking"] is False
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
