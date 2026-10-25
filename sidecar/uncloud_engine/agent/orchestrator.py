from __future__ import annotations

import json
import re
from collections.abc import Callable, Coroutine
from typing import Any

import httpx

from ..chat_transport import connection
from ..core import ApprovalRequired, Denied, Effort, Plan
from ..core import translate as translate_effort
from ..engines import engine_manager
from .contracts import native_tool, plan_schema, tool_contract, validate_args
from .graph import PERMISSION_STOP, ExecutionGraph, Task
from .planning_stream import completion as _completion
from .tools import TOOL_SPECS, run_tool

MAX_ACTIONS = 40

PLANNING_SYSTEM_PROMPT = {
    'task': 'plan', 'format': 'JSON', 'steps': 'minimal', 'goal_scope': 'current',
    'dependencies': 'acyclic', 'references': '{{TASK_ID}}', 'completion': 'verified_tool_result',
    'output': {'tasks': {'TASK_ID': {'description': 'string', 'tool_id': 'TOOL_ID',
                                  'args': {}, 'dependencies': ['TASK_ID']}},
               'start_node_ids': ['TASK_ID']},
}


def _tools_description(specs: list[dict] | None = None) -> str:
    return json.dumps([tool_contract(t)
                       for t in (specs if specs is not None else TOOL_SPECS)],
                      separators=(',', ':'))


def _active_tool_specs() -> list[dict]:
    """The tools this planner sees, narrowed to the configured groups.

    Left to itself the list only grows, and every entry costs prompt budget on
    a machine that may not have much to spare.
    """
    from ..config import settings
    from .tools import TOOL_SPECS, auto_groups, automation_tools, tools_for

    scope = automation_tools()
    if scope is not None:
        specs = [spec for spec in TOOL_SPECS if spec["id"] in scope]
    else:
        groups = settings.agent_tool_groups
        if groups is None:
            active = engine_manager.active
            groups = auto_groups(active.model_path if active else None)
        specs = tools_for(groups)
    # The runner persists its execution graph after every action. Letting a
    # draft overwrite that same graph creates a second, conflicting tracker.
    return [spec for spec in specs if spec['id'] not in {'plan_set', 'plan_show', 'plan_update'}]


def _extract_json(text: str) -> dict:
    # raw_decode respects braces inside quoted shell commands and document text.
    # Prefer the plan over unrelated JSON in a model's preamble.
    decoder = json.JSONDecoder()
    single = None
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "tasks" in value:
            return value
        if isinstance(value, dict) and isinstance(value.get('tool_id'), str) \
                and isinstance(value.get('args'), dict):
            single = single or value
    if single is not None:
        ident = single.get('id', 'task_1')
        return {'tasks': {ident: single}}
    raise ValueError("The model did not return a JSON task plan.")


def _graph_from_plan(parsed: dict, goal: str, specs: list[dict],
                     completed: dict[str, Task] | None = None, *,
                     allow_empty: bool = False,
                     literal_tasks: set[str] | None = None) -> ExecutionGraph:
    tasks = parsed.get("tasks")
    if not isinstance(tasks, dict) or not tasks and not allow_empty:
        raise ValueError("The plan must contain at least one task.")
    if len(tasks) > MAX_ACTIONS:
        raise ValueError("The plan has too many tasks; use at most 40.")
    allowed = {spec["id"]: spec for spec in specs}
    completed = completed or {}
    literal_tasks = literal_tasks or set()
    reused = {ident for ident, raw in tasks.items() if ident in completed
              and isinstance(raw, dict) and completed[ident].status == 'completed'
              and raw.get('tool_id') == completed[ident].tool_id
              and raw.get('args') == completed[ident].args
              and isinstance(raw.get('dependencies', []), list)
              and all(isinstance(dep, str) for dep in raw.get('dependencies', []))}
    # A repeated label with the same action refers to its completed result.
    # If one of its local inputs changed, it is a new action instead.
    while True:
        changed = {ident for ident in reused if any(
            dependency in tasks and dependency not in reused
            for dependency in tasks[ident].get('dependencies', [])
        ) or any(reference in tasks and reference not in reused
                 for reference in _references(tasks[ident]['args'],
                                              tasks.keys() | completed.keys()))}
        if not changed:
            break
        reused -= changed
    if reused:
        tasks = {ident: raw for ident, raw in tasks.items() if ident not in reused}
        if not tasks:
            raise ValueError('The plan only repeats completed steps; remaining work is missing.')
    if tasks.keys() & completed.keys():
        # Labels in each model reply are local to that reply. A new t1 must
        # not overwrite a completed t1 or make an otherwise valid plan fail.
        if any(not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_]+', ident)
               or not isinstance(raw, dict) for ident, raw in tasks.items()):
            raise ValueError('Each task needs a simple identifier and an object.')
        names = _distinct_names(tasks, set(completed), 'next_')
        literal_tasks = {names.get(ident, ident) for ident in literal_tasks}
        tasks = {names[ident]: {**raw,
                 'args': (raw.get('args') if names[ident] in literal_tasks
                          else _rename_refs(raw.get('args'), names)),
                 'dependencies': [names.get(dep, dep) if isinstance(dep, str) else dep
                                  for dep in raw.get('dependencies', [])]
                 if isinstance(raw.get('dependencies', []), list) else raw['dependencies']}
                 for ident, raw in tasks.items()}
    graph = ExecutionGraph(goal=goal)
    for task_id, raw in tasks.items():
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_]+", task_id) \
                or not isinstance(raw, dict):
            raise ValueError("Each task needs a simple identifier and an object.")
        tool = raw.get("tool_id")
        args = raw.get("args")
        deps = raw.get("dependencies", [])
        if not isinstance(tool, str) or tool not in allowed:
            raise ValueError(f"Unknown or disabled tool: {tool!r}.")
        if not isinstance(args, dict):
            raise ValueError(f"Task {task_id} needs an args object.")
        validate_args(allowed[tool], args, references=task_id not in literal_tasks)
        if not isinstance(deps, list) or any(
            not isinstance(d, str) or d not in tasks and d not in completed for d in deps
        ):
            raise ValueError(f"Task {task_id} has an unknown dependency.")
        graph.add_task(
            Task(
                id=task_id,
                description=str(raw.get("description", "")),
                tool_id=tool,
                args=args,
                dependencies=deps,
                literal_args=task_id in literal_tasks,
            )
        )
    resolved: set[str] = set(completed)
    while not tasks.keys() <= resolved:
        ready = {
            t.id
            for t in graph.tasks.values()
            if t.id not in resolved and set(t.dependencies) <= resolved
        }
        if not ready:
            raise ValueError("Task dependencies contain a cycle.")
        resolved.update(ready)
    for task in graph.tasks.values():
        if task.literal_args:
            continue
        ancestors = set(task.dependencies)
        pending = list(ancestors)
        while pending:
            dependency = graph.tasks.get(pending.pop())
            if dependency:
                for parent in set(dependency.dependencies) - ancestors:
                    ancestors.add(parent)
                    pending.append(parent)
        for ref in _references(task.args, tasks.keys() | completed.keys()):
            if ref not in ancestors and ref not in completed:
                raise ValueError(f'Task {task.id} references {ref} without a completed dependency.')
    graph.start_node_ids = [t.id for t in graph.tasks.values() if not t.dependencies]
    return graph


# Accept {{t1}}, {t1}, {{ t1.output }} — models are inconsistent about brace count,
# and a miss here silently turns into a literal string being passed to a tool.
_REF = re.compile(r"\{\{\s*(\w+)(?:\.output)?\s*\}\}|(?<!\{)\{(\w+)(?:\.output)?\}(?!\})")


def _references(value: Any, known: set[str]) -> set[str]:
    if isinstance(value, str):
        # Double braces are explicit references. Single braces can also be code
        # (f"{variable}"); only treat known task ids as legacy references later.
        return {m.group(1) or m.group(2) for m in _REF.finditer(value)
                if m.group(1) or m.group(2) in known and m.group(0) == value.strip()}
    if isinstance(value, (list, dict)):
        return set().union(*(_references(v, known) for v in (
            value.values() if isinstance(value, dict) else value)))
    return set()


def _resolve_refs(args: dict[str, Any], graph: ExecutionGraph,
                  tool_id: str | None = None) -> dict[str, Any]:
    """Substitute {{t1}} / {{t1.output}} in a task's arguments with what that task
    actually produced. Without this, a step can only ever use literals decided at
    planning time — which is how you end up writing '[content from t1]' to a file."""

    def sub(value: Any) -> Any:
        if isinstance(value, str):

            def replace(m: re.Match) -> str:
                if m.group(2) and m.group(0) != value.strip():
                    return m.group(0)
                name = m.group(1) or m.group(2)
                ref = graph.tasks.get(name)
                if not ref:
                    if m.group(1):
                        raise ValueError(f'Unknown task reference: {name}')
                    return m.group(0)
                if ref.status != 'completed' or ref.output is None:
                    raise ValueError(f'Task reference is not completed: {name}')
                return ref.output

            return _REF.sub(replace, value)
        if isinstance(value, list):
            return [sub(v) for v in value]
        if isinstance(value, dict):
            return {k: sub(v) for k, v in value.items()}
        return value

    resolved = {k: sub(v) for k, v in args.items()}
    spec = next((s for s in TOOL_SPECS if s['id'] == tool_id), None)
    if spec:
        properties = tool_contract(spec)['parameters']['properties']
        for key, value in resolved.items():
            if isinstance(value, str) and isinstance(args[key], str) \
                    and _REF.fullmatch(args[key]) and properties.get(key, {}).get('type') \
                    in ('object', 'array', 'integer', 'number', 'boolean'):
                resolved[key] = json.loads(value)
    return resolved


def _rename_refs(value: Any, names: dict[str, str]) -> Any:
    if isinstance(value, str):
        def rename(match: re.Match) -> str:
            # Embedded single braces are code/text, just as in _resolve_refs.
            if match.group(2) and match.group(0) != value.strip():
                return match.group(0)
            return match.group(0).replace(
                match.group(1) or match.group(2),
                names.get(match.group(1) or match.group(2), match.group(1) or match.group(2)), 1
            )

        return _REF.sub(rename, value)
    if isinstance(value, list):
        return [_rename_refs(item, names) for item in value]
    if isinstance(value, dict):
        return {key: _rename_refs(item, names) for key, item in value.items()}
    return value


def _distinct_names(identifiers, occupied: set[str], prefix: str) -> dict[str, str]:
    names = {ident: ident for ident in identifiers}
    reserved = occupied | set(names)
    for ident in names:
        if ident not in occupied:
            continue
        candidate = prefix + ident
        while candidate in reserved:
            candidate = prefix + candidate
        names[ident] = candidate
        reserved.add(candidate)
    return names


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

    return '\n\n' + json.dumps({'background': text}, ensure_ascii=False, separators=(',', ':'))


def planning_messages(goal: str, context: list[dict] | None = None, inference: dict | None = None):
    specs = _active_tool_specs()
    contract = {**PLANNING_SYSTEM_PROMPT, 'tools': json.loads(_tools_description(specs))}
    custom = (inference or {}).get("system_prompt")
    if isinstance(custom, str) and custom:
        contract['user_instructions'] = custom
    system = json.dumps(contract, ensure_ascii=False, separators=(',', ':'))
    return specs, [
        {"role": "system", "content": system},
        {"role": "user", "content": goal + _context_block(context)},
    ]


def planning_input(active, goal: str, context: list[dict] | None = None,
                   inference: dict | None = None, completed: dict[str, Task] | None = None):
    """Verified native function calling; retain the legacy protocol for other backends."""
    if not getattr(active, 'inference_profile', {}).get('capabilities', {}).get('native_tools'):
        specs, messages = planning_messages(goal, context, inference)
        return specs, messages, None
    specs = _active_tool_specs()
    definitions = [native_tool(spec) for spec in specs]
    observations = list((completed or {}).values())
    if completed is not None:
        try:
            request = json.loads(goal)
        except ValueError:
            request = None
        if isinstance(request, dict) and isinstance(request.get('goal'), str) \
                and request.get('task') in {'continue_plan', 'verify_completion', 'recover'}:
            goal = request['goal']
            if request['task'] == 'recover':
                observations += [Task(**{key: value for key, value in raw.items()
                                         if key in Task.__dataclass_fields__})
                                 for raw in request.get('failures', [])]
    messages = []
    custom = (inference or {}).get('system_prompt')
    if isinstance(custom, str) and custom:
        messages.append({'role': 'system', 'content': custom})
    messages.append({'role': 'user', 'content': goal + _context_block(context)})
    history = ExecutionGraph(goal=goal, tasks=dict(completed or {}))
    for index, task in enumerate(observations):
        args = task.args if task.literal_args else _resolve_refs(task.args, history, task.tool_id)
        ident = f'observed_{index}'
        messages.append({'role': 'assistant', 'content': '', 'tool_calls': [{
            'id': ident, 'type': 'function', 'function': {
                'name': task.tool_id, 'arguments': json.dumps(args, ensure_ascii=False)}}]})
        output = (task.output if task.status == 'completed'
                  else json.dumps({'error': task.error}, ensure_ascii=False))
        messages.append({'role': 'tool', 'tool_call_id': ident, 'content': output or ''})
    return specs, messages, definitions


def _graph_from_calls(message: dict, goal: str, specs: list[dict],
                      completed: dict[str, Task] | None, allow_empty: bool,
                      template: str = '') -> ExecutionGraph:
    calls = message.get('tool_calls') or []
    if not calls and isinstance(message.get('content'), str):
        from .native_calls import from_text

        calls = from_text(message['content'], specs, template)
    if not isinstance(calls, list):
        raise ValueError('The model returned invalid native tool calls.')
    if not calls and allow_empty and not (isinstance(message.get('content'), str)
                                          and message['content'].strip()):
        raise ValueError('No native action or completion response returned.')
    tasks = {}
    occupied = set(completed or {})
    previous = None
    for index, call in enumerate(calls, start=len(occupied) + 1):
        if not isinstance(call, dict) or call.get('type', 'function') != 'function' \
                or not isinstance(call.get('function'), dict):
            raise ValueError('The model returned an invalid native function call.')
        function = call.get('function', {})
        args = function.get('arguments')
        if isinstance(args, str):
            args = json.loads(args)
        ident = _distinct_names([f'call_{index}'], occupied, 'next_')[f'call_{index}']
        occupied.add(ident)
        tasks[ident] = {'tool_id': function.get('name'), 'args': args,
                        'dependencies': [previous] if previous else []}
        previous = ident
    graph = _graph_from_plan({'tasks': tasks}, goal, specs, completed,
                             allow_empty=allow_empty, literal_tasks=set(tasks))
    if not tasks and isinstance(message.get('content'), str):
        graph.response = message['content']
    return graph


class Orchestrator:
    async def plan(
        self,
        goal: str,
        context: list[dict] | None = None,
        *,
        effort: Effort | str = Effort.BALANCED,
        inference: dict | None = None,
        completed: dict[str, Task] | None = None,
        allow_empty: bool = False,
    ) -> ExecutionGraph:
        if not engine_manager.active:
            raise RuntimeError("No text model is loaded. Start one from the Chat tab first.")

        active = engine_manager.active

        specs, messages, native_tools = planning_input(active, goal, context, inference, completed)
        if not specs:
            raise RuntimeError('No executable tools are enabled for this task. No tools ran.')
        from ..chat import model_payload
        tool_options = {'native_tools': native_tools} if native_tools is not None else {}
        payload = model_payload(active, messages, inference=inference, **tool_options)
        payload["stream"] = True
        payload.pop("stream_options", None)
        # Keep native reasoning and samplers; structured-output enforcement is
        # used only when the running backend actually supports it.
        fields = getattr(active, "inference_profile", {}).get("capabilities", {}).get("fields", [])
        if native_tools is None and 'response_format' in fields \
                and not (payload.get('response_format') or payload.get('grammar')):
            payload['response_format'] = {'type': 'json_object'}
            if active.engine == 'gguf' and getattr(active, 'runtime', {}).get('executable'):
                # Native llama-server constrains decoding with this schema;
                # it is not additional text in the model's prompt.
                payload['response_format']['schema'] = plan_schema(specs)
        try:
            async with connection() as client:
                for attempt in range(2):
                    if getattr(active, "context_limit", 0):
                        from ..context_count import count

                        used = await count(active, messages, inference,
                                           **({'native_tools': native_tools}
                                              if native_tools is not None else {}))
                        if used is None:
                            raise RuntimeError(
                                "Native context accounting is unavailable. No tools ran."
                            )
                        available = active.context_limit - used
                        if available <= 0:
                            raise RuntimeError(
                                f"Planning needs {used} input tokens, "
                                f"but this runtime allows {active.context_limit}. Compact the "
                                "handoff or enable fewer tools. No tools ran."
                            )
                        # A reply ceiling is a maximum, not a reservation.
                        # Fit this request without changing saved manual values.
                        payload["max_tokens"] = min(
                            payload.get("max_tokens") or available, available)
                    content = ''
                    try:
                        resp = await _completion(
                            client, f"{active.base_url}/v1/chat/completions",
                            json={**payload, "messages": messages}, timeout=900,
                        )
                        resp.raise_for_status()
                        choice = resp.json()["choices"][0]
                        content = (choice["message"].get("content") or "").strip()
                        if choice.get("finish_reason") == "length":
                            raise ValueError("The plan was cut off. Use fewer, shorter steps.")
                        graph = (_graph_from_calls(choice['message'], goal, specs, completed,
                            allow_empty, getattr(active, 'inference_profile', {}).get(
                                'capabilities', {}).get('template', ''))
                                 if native_tools is not None else
                                 _graph_from_plan(_extract_json(content), goal, specs, completed,
                                                   allow_empty=allow_empty))
                        if native_tools is not None and not graph.tasks \
                                and choice.get('finish_reason') == 'tool_calls':
                            raise ValueError('The backend reported a tool call without an action.')
                        graph.inference = dict(inference or {})
                        graph.context = list(context or [])
                        return graph
                    except ValueError as exc:
                        if attempt:
                            raise RuntimeError(
                                "The model could not produce a usable plan after two attempts. "
                                f"No tools were run. Last issue: {exc}"
                            ) from exc
                        # Keep the original goal and background. Repair formatting before
                        # any side effect, without treating private reasoning as a plan.
                        messages += [
                            {"role": "assistant", "content": content[:4000] or "No plan returned."},
                            {
                                "role": "user",
                                "content": json.dumps({'task': 'repair_plan', 'error': str(exc)},
                                                      separators=(',', ':')),
                            },
                        ]

        except httpx.TimeoutException as exc:
            raise RuntimeError(
                "The model took too long to produce a plan. No tools were run. "
                "Try a shorter goal or another planning model."
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Could not reach the loaded model: {exc!r}") from exc
        raise RuntimeError("No usable plan was returned.")

    async def run(
        self,
        graph: ExecutionGraph,
        on_update: Callable[[ExecutionGraph], Coroutine[Any, Any, None]],
        *,
        effort: Effort | str = Effort.BALANCED,
    ) -> ExecutionGraph:
        """Execute a plan, and — above Fast — re-plan when part of it fails.

        Additive on purpose. Fast is exactly what this did before: one pass,
        no recovery, whatever happened is the answer. Higher levels wrap that
        same loop rather than replacing it, so the path that has been working
        stays the path that runs.

        Recovery re-plans the OUTSTANDING work rather than the whole goal.
        Re-planning from the top would redo everything that succeeded, which on
        a task that writes files is not merely wasteful.
        """
        budget = translate_effort(effort)
        observations = 0
        actions = 0

        def before_action(current: ExecutionGraph):
            nonlocal actions
            if actions >= MAX_ACTIONS:
                current.halt_reason = ('The action limit was reached. Review saved progress '
                                       'before continuing; no later actions ran.')
                raise RuntimeError(current.halt_reason)
            actions += 1

        async def observe(current: ExecutionGraph):
            nonlocal observations
            observations += 1
            await self._continue(current, observations, effort)

        await self._execute(graph, on_update, observe=observe, before_action=before_action)

        for attempt in range(1, budget.passes):
            if graph.halt_reason:
                break
            failed = graph.failed_tasks()
            if not failed:
                break
            recovered = await self._replan(graph, failed, attempt)
            if recovered is None or not recovered.tasks:
                self._persist_plan(graph)
                await on_update(graph)
                break
            await self._execute(recovered, on_update, into=graph, observe=observe,
                                before_action=before_action)
            replacements = [t.id for t in recovered.tasks.values() if t.id not in {
                old.id for old in failed} and t.status == 'completed']
            if replacements and not recovered.failed_tasks():
                for task in failed:
                    task.recovered_by = replacements
                self._persist_plan(graph)
                await on_update(graph)
        return graph

    async def _execute(
        self,
        graph: ExecutionGraph,
        on_update: Callable[[ExecutionGraph], Coroutine[Any, Any, None]],
        *,
        into: ExecutionGraph | None = None,
        observe: Callable[[ExecutionGraph], Coroutine[Any, Any, None]] | None = None,
        before_action: Callable[[ExecutionGraph], None] | None = None,
    ) -> ExecutionGraph:
        # Mirror the graph into durable memory as it executes. The in-flight graph
        # only lives for this run; the plan file survives, so a later session (or a
        # model that has lost the thread) can read back what was actually finished.
        self._persist_plan(graph)
        await on_update(graph)

        while not graph.all_terminal() and not graph.halt_reason:
            # Actions are sequential. Mark only the task actually executing as
            # in progress; future steps can change after a tool observation.
            ready = graph.ready_tasks()[:1]
            if not ready:
                for task in graph.tasks.values():
                    if task.status == "pending":
                        task.status = "failed"
                        task.error = "A required earlier step did not complete."
                self._persist_plan(graph)
                await on_update(graph)
                break
            for task in ready:
                task.status = "in_progress"
            self._persist_plan(graph)
            await on_update(graph)

            for task in ready:
                try:
                    if before_action:
                        before_action(graph)
                    task.output = await run_tool(task.tool_id, task.args if task.literal_args
                                                else _resolve_refs(task.args, graph, task.tool_id))
                    task.status = "completed"
                except (Denied, ApprovalRequired) as exc:
                    task.status = 'failed'
                    task.error = str(exc)
                    graph.halt_reason = str(exc)
                    for pending in graph.tasks.values():
                        if pending.status == 'pending':
                            pending.status = 'failed'
                            pending.error = PERMISSION_STOP
                except Exception as exc:  # noqa: BLE001 - surface tool failure on the node
                    task.status = "failed"
                    task.error = str(exc)
                    for pending in graph.tasks.values():
                        if pending.status == 'pending':
                            pending.status = 'failed'
                            pending.error = 'Earlier execution failed. Awaiting a revised plan.'
                self._persist_plan(graph)
                await on_update(graph)
                if observe and task.status == 'completed':
                    try:
                        await observe(graph)
                    except Exception as exc:
                        # A draft made before an observation cannot safely
                        # stand in for a plan that uses its actual result.
                        pending = [t for t in graph.tasks.values() if t.status == 'pending']
                        error = f'Could not plan from tool results: {exc}'
                        if not pending:
                            # A completed draft is not proof that the whole goal
                            # was satisfied. Keep a failed final check visible.
                            ident = _distinct_names(['completion_check'], set(graph.tasks),
                                                    'next_')['completion_check']
                            graph.add_task(Task(id=ident, description='Verify goal completion',
                                                tool_id='completion_check', args={},
                                                status='failed', error=error))
                        for pending_task in pending:
                            pending_task.status = 'failed'
                            pending_task.error = error
                    self._persist_plan(graph)
                    await on_update(graph)
        if into is not None and into is not graph:
            # Fold a recovery plan back into the original, so the interface
            # shows one account of the work rather than two graphs.
            for task_id, task in graph.tasks.items():
                into.tasks.setdefault(task_id, task)
            if graph.halt_reason:
                into.halt_reason = graph.halt_reason
            into.response = graph.response
            self._persist_plan(into)
            await on_update(into)
        return graph

    async def _continue(self, graph: ExecutionGraph, attempt: int,
                        effort: Effort | str) -> None:
        done = {t.id: t for t in graph.tasks.values() if t.status == 'completed'}
        pending = [t for t in graph.tasks.values() if t.status == 'pending']
        request = {'task': 'continue_plan' if pending else 'verify_completion',
                   'goal': graph.goal,
                   'observations': [task.to_dict() for task in done.values()],
                   'remaining': [task.to_dict() for task in pending],
                   'repeat_completed': False}
        if not pending:
            request['complete_output'] = {'tasks': {}}
        revised = await self.plan(json.dumps(request, ensure_ascii=False, separators=(',', ':')),
                                  context=graph.context, effort=effort,
                                  inference=graph.inference, completed=done,
                                  allow_empty=not pending)
        names = _distinct_names(revised.tasks, {
            ident for ident, task in graph.tasks.items() if task.status != 'pending'
        }, f'o{attempt}_')
        for task in revised.tasks.values():
            task.id = names[task.id]
            task.dependencies = [names.get(dep, dep) for dep in task.dependencies]
            if not task.literal_args:
                task.args = _rename_refs(task.args, names)
        graph.tasks = {ident: task for ident, task in graph.tasks.items()
                       if task.status != 'pending'}
        graph.tasks.update({task.id: task for task in revised.tasks.values()})
        graph.response = revised.response
        graph.start_node_ids = [task.id for task in graph.tasks.values() if not task.dependencies]

    async def _replan(
        self, graph: ExecutionGraph, failed: list[Task], attempt: int
    ) -> ExecutionGraph | None:
        """Ask for a new plan for what is left. Never raises.

        A recovery attempt that fails is not worse than not attempting one, so
        anything going wrong here ends the loop quietly and leaves the original
        result standing.
        """
        done = [t for t in graph.tasks.values() if t.status == "completed"]
        report = {'failed': [task.to_dict() for task in failed],
                  'completed': [task.to_dict() for task in done]}
        try:
            recovered = await self.plan(
                json.dumps({'task': 'recover', 'goal': graph.goal, 'report': report,
                            'failures': [task.to_dict() for task in failed]}, ensure_ascii=False),
                context=graph.context,
                **({"inference": graph.inference} if graph.inference else {}),
                completed={task.id: task for task in done},
            )
            # A new plan normally starts at t1 again. Keep its identity distinct
            # from the first attempt so completed recovery work is visible and
            # cannot be mistaken for an earlier successful task.
            names = _distinct_names(recovered.tasks, set(graph.tasks), f'r{attempt}_')
            for task in recovered.tasks.values():
                task.id = names[task.id]
                task.dependencies = [names.get(dep, dep) for dep in task.dependencies]
                if not task.literal_args:
                    task.args = _rename_refs(task.args, names)
            recovered.tasks = {task.id: task for task in recovered.tasks.values()}
            recovered.start_node_ids = [
                names.get(task_id, task_id) for task_id in recovered.start_node_ids
            ]
            for task in graph.tasks.values():
                if task.status == "completed":
                    recovered.tasks[task.id] = task
            recovered.goal = graph.goal
            return recovered
        except Exception as exc:  # noqa: BLE001 - keep the original failure and explain recovery
            for task in failed:
                task.error = f'{task.error or "Task failed"}\nRecovery planning failed: {exc}'
            return None

    @staticmethod
    def _persist_plan(graph: ExecutionGraph) -> None:
        from . import memory

        status_map = {
            "pending": "todo",
            "in_progress": "doing",
            "completed": "done",
            "failed": "blocked",
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


def _planning_parameters(plan: Plan) -> dict:
    """The effort plan's parameters, in the shape a chat completion takes.

    Only what the server will recognise. `enable_thinking` travels inside
    `chat_template_kwargs` because that is where llama.cpp and mlx-lm both look
    for template arguments; sending it at the top level does nothing anywhere.
    """
    out: dict = {"max_tokens": plan.max_output_tokens}
    if "enable_thinking" in plan.parameters:
        out["chat_template_kwargs"] = {"enable_thinking": plan.parameters["enable_thinking"]}
    for name in ("reasoning_max_tokens", "reasoning_effort"):
        if name in plan.parameters:
            out[name] = plan.parameters[name]
    return out


def _active_profile():
    """The loaded model in the shared vocabulary, or None if nothing is up."""
    active = engine_manager.active
    return getattr(active, "model_profile", None)
