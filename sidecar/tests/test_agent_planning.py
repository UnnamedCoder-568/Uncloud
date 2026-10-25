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


def test_planning_protocol_has_no_application_identity_or_date(monkeypatch):
    monkeypatch.setattr(module, '_active_tool_specs', lambda: SPECS)
    _, messages = module.planning_messages('Write a file')
    system = messages[0]['content']
    assert 'Astro' not in system and 'Today is' not in system
    assert 'fs_write' in system and 'JSON' in system


def test_runner_owns_its_plan_tracking_in_interactive_and_background_work(monkeypatch):
    from uncloud_engine.agent import tools
    from uncloud_engine.config import settings

    monkeypatch.setattr(settings, '_data', {'agent_tool_groups': ['memory', 'shell', 'files']})
    ids = {spec['id'] for spec in module._active_tool_specs()}
    assert {'ask_user', 'note_save', 'note_recall', 'shell', 'python_exec', 'fs_write'} <= ids
    assert not ids & {'plan_set', 'plan_show', 'plan_update'}
    with tools.automation_scope({'plan_set', 'plan_show', 'shell'}):
        assert [spec['id'] for spec in module._active_tool_specs()] == ['shell']


def test_verified_native_planner_exposes_schemas_without_an_application_prompt(monkeypatch):
    active = SimpleNamespace(engine='gguf', base_url='http://model', inference_profile={
        'capabilities': {'native_tools': True, 'fields': ['response_format'],
                         'reasoning': {'levels': ['auto']}}})
    monkeypatch.setattr(module.engine_manager, 'active', active)
    monkeypatch.setattr(module, '_active_tool_specs', lambda: SPECS)
    sent = []

    async def completion(client, url, json, timeout):
        sent.append(json)
        return httpx.Response(200, request=httpx.Request('POST', url), json={'choices': [{
            'message': {'content': '', 'tool_calls': [{'type': 'function', 'function': {
                'name': 'fs_write', 'arguments': '{"path":"x.txt","content":"{{literal}}"}'}}]},
            'finish_reason': 'tool_calls'}]})

    monkeypatch.setattr(module, '_completion', completion)
    graph = asyncio.run(module.Orchestrator().plan('Write a file'))
    assert sent[0]['messages'] == [{'role': 'user', 'content': 'Write a file'}]
    assert [tool['function']['name'] for tool in sent[0]['tools']] == ['fs_write']
    assert 'response_format' not in sent[0] and 'temperature' not in sent[0]
    assert graph.tasks['call_1'].literal_args
    assert graph.tasks['call_1'].args['content'] == '{{literal}}'


def test_native_tools_retain_text_encoding_and_available_runtime_modules(monkeypatch):
    from uncloud_engine.agent import tools

    specs = [spec for spec in tools.TOOL_SPECS if spec['id'] in {'fs_write', 'python_exec'}]
    monkeypatch.setattr(module, '_active_tool_specs', lambda: specs)
    active = SimpleNamespace(inference_profile={'capabilities': {'native_tools': True}})
    _, messages, definitions = module.planning_input(active, 'Create the requested documents')
    assert messages == [{'role': 'user', 'content': 'Create the requested documents'}]
    by_name = {item['function']['name']: item['function'] for item in definitions}
    text = json.loads(by_name['fs_write']['parameters']['$comment'])
    runtime = json.loads(by_name['python_exec']['parameters']['$comment'])
    assert text == {'encoding': 'utf-8', 'format': 'text'}
    assert runtime == {'runtime': 'engine_python',
                       'modules': ['reportlab', 'pypdf', 'docx', 'openpyxl', 'PIL']}
    assert all('description' not in item for item in by_name.values())


@pytest.mark.parametrize('function', [
    {'name': 'unknown_tool', 'arguments': '{}'},
    {'name': 'fs_write', 'arguments': '{"path":"x","content":7}'},
    {'name': 'fs_write', 'arguments': 'not JSON'},
])
def test_invalid_native_calls_are_rejected_before_execution(function):
    with pytest.raises(ValueError):
        module._graph_from_calls({'tool_calls': [{'function': function}]},
                                 'Write', SPECS, None, False)


def test_native_reply_without_actions_requires_a_completion_review():
    with pytest.raises(ValueError, match='at least one task'):
        module._graph_from_calls({'content': 'Done'}, 'Write', SPECS, None, False)
    assert not module._graph_from_calls({'content': 'Verified'}, 'Write', SPECS, {}, True).tasks
    with pytest.raises(ValueError, match='No native action'):
        module._graph_from_calls({'content': ''}, 'Write', SPECS, {}, True)


def test_native_workflow_uses_real_tool_results_until_completion(tmp_path, monkeypatch):
    from uncloud_engine.agent import approval, tools
    from uncloud_engine.core import Gate

    monkeypatch.setattr(tools, 'WORKSPACE_DIR', tmp_path)
    monkeypatch.setattr(tools.settings, '_data', {'agent_device_access': True})
    monkeypatch.setattr(module.Orchestrator, '_persist_plan', lambda *args: None)
    monkeypatch.setattr(module.engine_manager, 'active', SimpleNamespace(
        engine='gguf', base_url='http://model', inference_profile={
            'capabilities': {'native_tools': True, 'fields': [],
                             'reasoning': {'levels': ['auto']}}}))
    specs = [spec for spec in tools.TOOL_SPECS if spec['id'] in {
        'fs_write', 'fs_edit', 'fs_read', 'fs_list', 'python_exec'}]
    monkeypatch.setattr(module, '_active_tool_specs', lambda: specs)
    actions = [('fs_write', {'path': 'notes.txt', 'content': 'alpha'}),
               ('fs_edit', {'path': 'notes.txt', 'old': 'alpha', 'new': 'beta'}),
               ('fs_read', {'path': 'notes.txt'}), ('fs_list', {'path': '.'}),
               ('python_exec', {'code': "print(6*7); print('{{literal}}')"})]
    observed = []
    initial_turn = []

    async def completion(client, url, json, timeout):
        messages = json['messages']
        assert messages[0]['role'] == 'user'
        assert messages[0]['content'].startswith('Perform and verify the whole workflow')
        assert 'Retained handoff fact' in messages[0]['content']
        if not initial_turn:
            initial_turn.append(messages[0])
        assert messages[0] == initial_turn[0]
        outputs = [turn['content'] for turn in messages if turn['role'] == 'tool']
        observed.append(outputs)
        if len(outputs) < len(actions):
            name, args = actions[len(outputs)]
            message = {'tool_calls': [{'type': 'function', 'function': {
                'name': name, 'arguments': __import__('json').dumps(args)}}]}
        else:
            assert __import__('json').loads(outputs[-1])['stdout'] == '42\n{{literal}}\n'
            message = {'content': 'Verified.'}
        return httpx.Response(200, request=httpx.Request('POST', url), json={'choices': [{
            'message': message, 'finish_reason': 'stop'}]})

    monkeypatch.setattr(module, '_completion', completion)

    async def ask(request):
        return 'yes'

    async def exercise():
        planner = module.Orchestrator()
        graph = await planner.plan('Perform and verify the whole workflow',
                                    context=[{'role': 'user', 'content': 'Retained handoff fact'}])
        async def update(current):
            pass
        with approval.asking(ask):
            return await planner.run(graph, update)

    tools.install_gate(Gate())
    try:
        graph = asyncio.run(exercise())
    finally:
        tools.install_gate(None)
    assert not graph.failed_tasks()
    assert (tmp_path / 'notes.txt').read_text() == 'beta'
    assert len(graph.tasks) == 5
    assert [len(outputs) for outputs in observed] == list(range(6))
    assert observed[-1][2] == 'beta'
    assert all(task.literal_args for task in graph.tasks.values())
    assert graph.response == 'Verified.'
    assert graph.to_dict()['response'] == 'Verified.'


def test_native_planning_enforces_only_enabled_tool_shapes_without_extra_prompt(monkeypatch):
    monkeypatch.setattr(module.engine_manager, 'active', SimpleNamespace(
        base_url='http://model', engine='gguf', runtime={'executable': '/native/llama-server'},
        inference_profile={'capabilities': {'fields': ['response_format'],
                                            'reasoning': {'levels': ['auto']}}}))
    monkeypatch.setattr(module, '_active_tool_specs', lambda: SPECS)
    sent = []

    async def post(self, url, json, timeout):
        sent.append(json)
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'choices': [{'message': {'content': __import__('json').dumps(PLAN)}}]})

    monkeypatch.setattr(module, '_completion', post)
    asyncio.run(module.Orchestrator().plan('Write a file'))
    variants = sent[0]['response_format']['schema']['properties']['tasks'][
        'additionalProperties']['anyOf']
    assert len(variants) == 1
    assert variants[0]['properties']['tool_id']['enum'] == ['fs_write']
    assert variants[0]['properties']['args']['additionalProperties'] is False
    assert set(variants[0]['properties']['args']['properties']) == {'path', 'content'}
    assert sent[0]['messages'] == module.planning_messages('Write a file')[1]
    assert 'temperature' not in sent[0] and 'chat_template_kwargs' not in sent[0]


def test_planning_reply_ceiling_fits_the_native_context_without_mutating_preferences(monkeypatch):
    from uncloud_engine import context_count
    active = SimpleNamespace(base_url='http://model', engine='gguf', context_limit=1024,
                             inference_profile={'capabilities': {'fields': ['max_tokens'],
                                 'reasoning': {'levels': ['auto']}}})
    monkeypatch.setattr(module.engine_manager, 'active', active)
    monkeypatch.setattr(module, '_active_tool_specs', lambda: SPECS)
    monkeypatch.setattr(context_count, 'count', AsyncMock(return_value=200))
    sent = []

    async def post(self, url, json, timeout):
        assert timeout == 900
        sent.append(json)
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'choices': [{'message': {'content': __import__('json').dumps(PLAN)}}],
        })

    monkeypatch.setattr(module, '_completion', post)
    preferences = {'max_tokens': 4096}
    asyncio.run(module.Orchestrator().plan('Write a file', inference=preferences))
    assert sent[0]['max_tokens'] == 824
    assert preferences == {'max_tokens': 4096}


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

    async def post(self, url, json, timeout):
        assert timeout == 900
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

    monkeypatch.setattr(module, "_completion", post)
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

    async def post(self, url, json, timeout):
        assert timeout == 900
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

    monkeypatch.setattr(module, "_completion", post)
    with pytest.raises(RuntimeError, match="No tools were run"):
        asyncio.run(module.Orchestrator().plan("goal"))


def test_repeated_reasoning_retries_without_changing_defaults_or_running_tools(monkeypatch):
    monkeypatch.setattr(module.engine_manager, 'active',
                        SimpleNamespace(base_url='http://model', engine='gguf'))
    monkeypatch.setattr(module, '_active_tool_specs', lambda: SPECS)
    sent = []

    async def complete(client, url, json, timeout):
        sent.append(json)
        if len(sent) == 1:
            raise ValueError('Repeated reasoning detected. No usable plan returned.')
        return httpx.Response(200, request=httpx.Request('POST', url), json={
            'choices': [{'message': {'content': __import__('json').dumps(PLAN)},
                         'finish_reason': 'stop'}]})

    monkeypatch.setattr(module, '_completion', complete)
    runner = AsyncMock()
    monkeypatch.setattr(module, 'run_tool', runner)
    graph = asyncio.run(module.Orchestrator().plan('Write a file'))
    assert graph.tasks['t1'].args['path'] == 'x.txt'
    assert len(sent) == 2
    assert all(body['stream'] is True for body in sent)
    assert all('chat_template_kwargs' not in body and 'temperature' not in body for body in sent)
    runner.assert_not_called()


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

    async def post(self, url, json, timeout):
        assert timeout == 900
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": __import__("json").dumps(plan)}}],
        })

    monkeypatch.setattr(module, "_completion", post)
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

    async def post(self, url, json, timeout):
        assert timeout == 900
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": {"content": "```python\ndef square(n): return n * n\n```"}}],
        })

    monkeypatch.setattr(module, "_completion", post)
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

    async def replan(goal, **kwargs):
        return recovered

    monkeypatch.setattr(planner, "plan", replan)
    retry = asyncio.run(planner._replan(first, [first.tasks["t1"]], 1))
    assert "r1_t1" in retry.tasks
    assert "t1" in first.tasks
    asyncio.run(planner._execute(retry, update, into=first))
    assert first.tasks["r1_t1"].status == "completed"
