from types import SimpleNamespace

import pytest

from uncloud_engine.chat import model_payload
from uncloud_engine.web_tools import definitions


def active(supported=True, engine='mlx-vlm'):
    return SimpleNamespace(engine=engine, model_path='/model', context_limit=8192,
        inference_profile={'capabilities': {'native_tools': supported, 'fields': [],
                                           'reasoning': {'levels': ['auto']}}})


@pytest.mark.parametrize('engine', ['mlx', 'mlx-vlm', 'gguf'])
def test_native_web_preserves_messages_and_sampling_without_instructions(engine):
    turns = [{'role': 'user', 'content': 'Who are you?'}]
    payload = model_payload(active(engine=engine), turns, web_tools=True)
    assert payload['messages'] is turns
    assert {x['function']['name'] for x in payload['tools']} == {
        'web_search', 'web_read'}
    assert 'tool_choice' not in payload  # Native optional tool use, no forced-call instructions.
    assert 'temperature' not in payload
    assert 'tools' not in model_payload(active(), turns)


def test_unsupported_native_tools_never_fall_back_to_prompt_injection():
    assert definitions(active(False), False) == []
    with pytest.raises(ValueError, match='native web tools'):
        definitions(active(False), True)


def test_native_tools_are_cached_data_without_file_or_model_access(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(Path, 'read_text',
                        lambda *a, **k: pytest.fail('No file reads on chat dispatch'))
    assert len(definitions(active(), True)) == 2


def test_tools_file_contains_only_the_two_public_web_schemas():
    import json
    from pathlib import Path

    import uncloud_engine.web_tools as web

    template = Path(web.__file__).with_name('Tools.jinja').read_text()
    schemas = json.loads(template)
    assert schemas == definitions(active(), True)
    assert [s['function']['name'] for s in schemas] == ['web_search', 'web_read']
    assert all(set(s) == {'type', 'function'} for s in schemas)
    assert all(set(s['function']) == {'name', 'description', 'parameters'} for s in schemas)
    assert 'system' not in template and 'model_info' not in template
    assert '{{' not in template and '{%' not in template
    assert all(s['function']['parameters']['additionalProperties'] is False for s in schemas)
