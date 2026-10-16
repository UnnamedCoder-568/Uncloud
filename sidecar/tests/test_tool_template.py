import json
from types import SimpleNamespace

from uncloud_engine.chat import model_payload
from uncloud_engine.tool_template import compact, install_vlm

HEADER = '# Tools\n\nYou have access to the following functions:\n\n<tools>'
PROTOCOL = ('\n\nIf you choose to call a function ONLY reply '
            'in the following format with NO suffix:'
            '\n<tool_call><function=example_function_name><parameter=example_parameter_1>'
            'value</parameter></function></tool_call>\n<IMPORTANT>native rules</IMPORTANT>')
TEMPLATE = ('{% if tools %}<|im_start|>system\n{{ ' + repr(HEADER) + ' }}'
            '{% for tool in tools %}{{ tool | tojson }}{% endfor %}'
            '</tools>{{ ' + repr(PROTOCOL) + ' }}<|im_end|>\n{% endif %}'
            '{% for m in messages %}<|im_start|>{{ m.role }}\n'
            '{{ m.content }}<|im_end|>\n{% endfor %}'
            '<|im_start|>assistant\n{% if enable_thinking %}<think>\n'
            '{% else %}<think>\n\n</think>\n\n{% endif %}')


def test_native_header_is_compact_but_conversation_and_thinking_tokens_are_unchanged():
    from jinja2 import Environment

    changed = compact(TEMPLATE)
    assert changed != TEMPLATE
    for enabled in (False, True):
        args = {'messages': [{'role': 'user', 'content': 'User-authored text stays exact.'}],
                'tools': [], 'enable_thinking': enabled}
        before = Environment().from_string(TEMPLATE).render(**args)
        after = Environment().from_string(changed).render(**args)
        assert after == before  # No template change with tools off.
        args['tools'] = [{'type': 'function', 'function': {'name': 'web_read'}}]
        rendered = Environment().from_string(changed).render(**args)
        assert 'User-authored text stays exact.' in rendered
        protocol = ('<tool_call>\n<function=example_function_name>'
                    '\n<parameter=example_parameter_1>\nvalue_1\n</parameter>'
                    '\n<parameter=example_parameter_2>\nvalue_2\n</parameter>'
                    '\n</function>\n</tool_call>')
        assert protocol in rendered
        assert 'You have access' not in rendered and '<IMPORTANT>' not in rendered
        assert rendered.endswith(after[after.index('<|im_start|>assistant'):])


def test_unknown_native_template_is_never_partly_rewritten():
    assert compact('unrecognized template') == 'unrecognized template'
    partial = '{{ ' + repr(HEADER) + ' }}'
    assert compact(partial) == partial


def test_vlm_override_is_per_render_and_never_mutates_the_processor_or_messages():
    requests = []
    server = SimpleNamespace(apply_chat_template=lambda *args, **kwargs:
                             requests.append((args, kwargs)))
    processor = SimpleNamespace(chat_template=TEMPLATE)
    messages = [{'role': 'user', 'content': 'test'}]
    install_vlm(server)
    server.apply_chat_template(processor, {}, messages, tools=[{'type': 'function'}])
    server.apply_chat_template(processor, {}, messages, tools=None)
    assert requests[0][1]['chat_template'] == compact(TEMPLATE)
    assert 'chat_template' not in requests[1][1]
    assert processor.chat_template == TEMPLATE and requests[0][0][2] is messages


def test_mlx_payload_keeps_user_thinking_toggle_with_the_same_compact_template():
    active = SimpleNamespace(engine='mlx', context_limit=8192, inference_profile={
        'capabilities': {'native_tools': True, 'fields': [], 'template': TEMPLATE,
                         'reasoning': {'levels': ['auto', 'off'], 'mechanism': 'template_toggle'}}})
    messages = [{'role': 'user', 'content': 'question'}]
    payload = model_payload(active, messages, web_tools=True, inference={'reasoning': 'off'})
    assert payload['chat_template_kwargs'] == {
        'enable_thinking': False, 'chat_template': compact(TEMPLATE)}
    assert payload['messages'] is messages
    assert 'chat_template_kwargs' not in model_payload(active, messages)


def test_compaction_uses_a_data_contract_and_not_a_persona_instruction():
    from uncloud_engine.compaction import INSTRUCTION, summary_messages

    assert json.loads(INSTRUCTION)['task'] == 'summarize'
    turns = summary_messages('new transcript', 'prior memory')
    assert json.loads(turns[1]['content']) == {
        'memory': 'prior memory', 'transcript': 'new transcript'}
