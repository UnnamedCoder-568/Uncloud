from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

import httpx

from ..engines import engine_manager
from .graph import ExecutionGraph, Task
from .tools import TOOL_SPECS, run_tool

PLANNING_SYSTEM_PROMPT = """You are the planning module of a local AI agent named Astro. \
Break the user's goal into a small directed acyclic graph of concrete steps. \
Each step must use exactly one tool. Available tools:

{tools}

Respond with ONLY a JSON object, no prose, no markdown fences, in this exact shape:
{{
  "tasks": {{
    "t1": {{"description": "...", "tool_id": "shell", "args": {{"command": "..."}}, "dependencies": []}},
    "t2": {{"description": "...", "tool_id": "fs_write", "args": {{"path": "...", "content": "..."}}, "dependencies": ["t1"]}}
  }},
  "start_node_ids": ["t1"]
}}

To use what an earlier step produced, reference it as {{t1}} inside a later step's args —
it is replaced with that step's actual output before the step runs. Never write a
placeholder like "[content from t1]"; write {{t1}} instead. Example:
  "t1": {{"description": "Read the page", "tool_id": "web_read", "args": {{"url": "..."}}, "dependencies": []}},
  "t2": {{"description": "Save it", "tool_id": "fs_write", "args": {{"path": "out.txt", "content": "{{{{t1}}}}"}}, "dependencies": ["t1"]}}

Keep it to the minimum number of steps needed. Prefer fewer, more capable shell commands over many small steps.

Guidance:
- Do not add a shell step to slice or summarise text you already have — pass {{t1}} straight
  into the step that needs it. Shell is for running programs, not for editing strings.
- Progress is recorded automatically, so you do not need planning steps just to track state.
- Use note_save for a fact a later step depends on (a path, an ID, a finding), and note_recall to read it back rather than re-deriving it.
- To work with a web page you only need to read, use web_read. Use browser_open when the page needs JavaScript, or when a later step must click or type.
- see_image only works when a vision-capable model is loaded; pair it with screen_capture or browser_screenshot."""


def _tools_description(specs: list[dict] | None = None) -> str:
    return "\n".join(
        f"- {t['id']}: {t['description']} (args: {', '.join(t['args'])})"
        for t in (specs if specs is not None else TOOL_SPECS)
    )


def _active_tool_specs() -> list[dict]:
    """The tools this planner sees, narrowed to the configured groups.

    Left to itself the list only grows, and every entry costs prompt budget on
    a machine that may not have much to spare.
    """
    from ..config import settings
    from .tools import auto_groups, tools_for

    groups = settings.agent_tool_groups
    if groups is None:
        active = engine_manager.active
        groups = auto_groups(active.model_path if active else None)
    return tools_for(groups)


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in planner output: {text[:500]!r}")
    blob = text[start:end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        # A model that reasons past the JSON can leave trailing prose. Retry against
        # the largest balanced object starting at the first brace.
        depth = 0
        for i, ch in enumerate(blob):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(blob[: i + 1])
        raise


# Accept {{t1}}, {t1}, {{ t1.output }} — models are inconsistent about brace count,
# and a miss here silently turns into a literal string being passed to a tool.
_REF = re.compile(r"\{\{?\s*(\w+)(?:\.output)?\s*\}?\}")


def _resolve_refs(args: dict[str, Any], graph: ExecutionGraph) -> dict[str, Any]:
    """Substitute {{t1}} / {{t1.output}} in a task's arguments with what that task
    actually produced. Without this, a step can only ever use literals decided at
    planning time — which is how you end up writing '[content from t1]' to a file."""

    def sub(value: Any) -> Any:
        if isinstance(value, str):
            def replace(m: re.Match) -> str:
                ref = graph.tasks.get(m.group(1))
                return (ref.output or "") if ref else m.group(0)
            return _REF.sub(replace, value)
        if isinstance(value, list):
            return [sub(v) for v in value]
        if isinstance(value, dict):
            return {k: sub(v) for k, v in value.items()}
        return value

    return {k: sub(v) for k, v in args.items()}


#: How much of a handed-over conversation to carry into planning.
#:
#: A long chat would otherwise crowd out the tool list in a small model's
#: context window, and the planner would start inventing tools because it could
#: no longer see the real ones. The tail is what matters: the work being asked
#: for is at the end of the conversation, not the beginning.
CONTEXT_BUDGET_CHARS = 6000


def _context_block(context: list[dict] | None) -> str:
    """The conversation a goal was handed over from, as background.

    Marked as background explicitly. Without that the planner reads a
    transcript as a series of new instructions and plans the whole
    conversation again rather than the one thing that was asked for.
    """
    if not context:
        return ""
    lines: list[str] = []
    for turn in context:
        role = str(turn.get("role", "")).strip()
        content = str(turn.get("content", "")).strip()
        if not content or role not in ("user", "assistant"):
            continue
        who = "User" if role == "user" else "Assistant"
        lines.append(f"{who}: {content}")

    text = "\n\n".join(lines)
    if len(text) > CONTEXT_BUDGET_CHARS:
        text = "…\n\n" + text[-CONTEXT_BUDGET_CHARS:]
    return (
        "\n\nBACKGROUND — the conversation this was handed over from. It is "
        "context for understanding the goal, not a list of things to do. Plan "
        "only for the goal above.\n\n" + text
    )


class Orchestrator:
    async def plan(self, goal: str, context: list[dict] | None = None) -> ExecutionGraph:
        if not engine_manager.active:
            raise RuntimeError("No text model is loaded. Start one from the Chat tab first.")

        system = PLANNING_SYSTEM_PROMPT.format(tools=_tools_description(_active_tool_specs()))
        # Planning happens once per run and has a long system prompt to chew through;
        # a large model on a busy machine can legitimately take minutes.
        try:
            async with httpx.AsyncClient(timeout=900) as client:
                resp = await client.post(
                    f"{engine_manager.active.base_url}/v1/chat/completions",
                    json={
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": goal + _context_block(context)},
                        ],
                        "temperature": 0.2,
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                message = resp.json()["choices"][0]["message"]
                # Thinking models (Qwen3, and anything served with a reasoning parser)
                # split their output: the visible answer lands in `content`, the chain of
                # thought in `reasoning_content`. When a model reasons its way to the JSON
                # and stops, `content` comes back empty — so fall back to the reasoning.
                content = (message.get("content") or "").strip()
                if not content:
                    content = (message.get("reasoning_content") or "").strip()
        except httpx.TimeoutException:
            raise RuntimeError(
                "The model took too long to produce a plan. Smaller models can stall on "
                "long tool lists — try a simpler goal, or load a larger model."
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Could not reach the loaded model: {exc!r}")

        parsed = _extract_json(content)
        graph = ExecutionGraph(goal=goal)
        for task_id, raw in parsed.get("tasks", {}).items():
            graph.add_task(Task(
                id=task_id,
                description=raw.get("description", ""),
                tool_id=raw.get("tool_id", ""),
                args=raw.get("args", {}),
                dependencies=raw.get("dependencies", []),
            ))
        graph.start_node_ids = parsed.get("start_node_ids", list(graph.tasks.keys())[:1])
        return graph

    async def run(
        self, graph: ExecutionGraph, on_update: Callable[[ExecutionGraph], Coroutine[Any, Any, None]],
    ) -> ExecutionGraph:
        # Mirror the graph into durable memory as it executes. The in-flight graph
        # only lives for this run; the plan file survives, so a later session (or a
        # model that has lost the thread) can read back what was actually finished.
        self._persist_plan(graph)
        await on_update(graph)

        while not graph.all_terminal():
            ready = graph.ready_tasks()
            if not ready:
                break
            for task in ready:
                task.status = "in_progress"
            self._persist_plan(graph)
            await on_update(graph)

            for task in ready:
                try:
                    task.output = await run_tool(task.tool_id, _resolve_refs(task.args, graph))
                    task.status = "completed"
                except Exception as exc:  # noqa: BLE001 - surface tool failure on the node
                    task.status = "failed"
                    task.error = str(exc)
                self._persist_plan(graph)
                await on_update(graph)
        return graph

    @staticmethod
    def _persist_plan(graph: ExecutionGraph) -> None:
        from . import memory

        status_map = {
            "pending": "todo", "in_progress": "doing",
            "completed": "done", "failed": "blocked",
        }
        try:
            ordered = list(graph.tasks.values())
            memory.plan_set(graph.goal, [t.description or t.tool_id for t in ordered])
            for i, task in enumerate(ordered, 1):
                note = (task.error or "")[:200] if task.status == "failed" else ""
                memory.plan_update(i, status_map.get(task.status, "todo"), note)
        except Exception:  # noqa: BLE001 - memory is a convenience, never fail the run for it
            pass


orchestrator = Orchestrator()
