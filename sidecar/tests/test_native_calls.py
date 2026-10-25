import pytest

from uncloud_engine.agent.native_calls import from_text
from uncloud_engine.agent.orchestrator import _graph_from_calls

TEMPLATE = '<tool_call>\n<function=NAME>\n<parameter=ARG>value</parameter>'
SPECS = [{'id': 'fs_read', 'args': ['path']},
         {'id': 'python_exec', 'args': ['code', 'output_paths (optional)']},
         {'id': 'computer_key', 'args': ['keys']}]


def function(name, parameters, opening=True):
    return ('<tool_call>\n' if opening else '') + f'<function={name}>\n' + parameters \
        + '\n</function>\n</tool_call>'


@pytest.mark.parametrize('opening', [False, True])
def test_complete_native_function_survives_a_consumed_opening_wrapper(opening):
    text = function('fs_read', '<parameter=path>\ninventory.json\n</parameter>', opening)
    calls = from_text(text, SPECS, TEMPLATE)
    assert calls == [{'type': 'function', 'function': {
        'name': 'fs_read', 'arguments': {'path': 'inventory.json'}}}]
    graph = _graph_from_calls({'content': text}, 'Read inventory', SPECS, None, False, TEMPLATE)
    assert graph.tasks['call_1'].literal_args


def test_native_code_and_json_arguments_are_preserved_without_interpolation():
    code = "print('{{literal}}')\nif 1 < 2:\n    print('unchanged')"
    text = function('python_exec', '<parameter=code>\n' + code + '\n</parameter>\n'
                    '<parameter=output_paths>\n[]\n</parameter>')
    args = from_text(text, SPECS, TEMPLATE)[0]['function']['arguments']
    assert args == {'code': code, 'output_paths': []}


def test_multiple_native_blocks_preserve_order_and_union_parameter_types():
    text = function('computer_key', '<parameter=keys>["ctrl", "a"]</parameter>')
    text += '\n' + function('computer_key', '<parameter=keys>1</parameter>')
    assert [call['function']['arguments']['keys'] for call in from_text(text, SPECS, TEMPLATE)] \
        == [['ctrl', 'a'], '1']


@pytest.mark.parametrize('text', [
    'Example: ' + function('fs_read', '<parameter=path>x</parameter>'),
    '```xml\n' + function('fs_read', '<parameter=path>x</parameter>') + '\n```',
    '<!DOCTYPE example>' + function('fs_read', '<parameter=path>x</parameter>'),
])
def test_prose_fences_and_other_document_content_do_not_become_actions(text):
    assert from_text(text, SPECS, TEMPLATE) == []


@pytest.mark.parametrize('text', [
    function('fs_read', '<parameter=path>x</parameter>') + '\nOther content',
    '<function=fs_read><parameter=path>x</parameter></function>',
    function('fs_read', '<parameter=path>x</parameter><parameter=path>y</parameter>'),
    function('unknown', '<parameter=path>x</parameter>'),
    function('fs_read', '<parameter=extra>x</parameter>'),
    function('python_exec', '<parameter=code>if :</parameter>'),
    function('python_exec', '<parameter=code>pass</parameter>'
             '<parameter=output_paths>"not an array"</parameter>'),
])
def test_partial_unknown_and_malformed_native_calls_fail_before_execution(text):
    with pytest.raises(ValueError):
        from_text(text, SPECS, TEMPLATE)


def test_only_the_protocol_declared_by_the_selected_template_is_parsed():
    text = function('fs_read', '<parameter=path>x</parameter>')
    assert from_text(text, SPECS, 'Unrecognized native format') == []
