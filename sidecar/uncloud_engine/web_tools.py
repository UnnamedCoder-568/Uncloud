"""Neutral native tool definitions, formatted by the model's own chat template."""
from __future__ import annotations

import json
from pathlib import Path

# Static template: only function schemas, no Jinja substitutions or prompt prose.
# Read once at startup and pass as API data. The model's original chat_template
# owns formatting; this file is never appended to a message or substituted for it.
_TOOLS = json.loads(Path(__file__).with_name('Tools.jinja').read_text(encoding='utf-8'))
WEB_TOOLS = [tool for tool in _TOOLS if tool['function']['name'].startswith('web_')]
HISTORY_TOOLS = [tool for tool in _TOOLS if tool['function']['name'] == 'conversation_search']
CHART_TOOLS = [tool for tool in _TOOLS if tool['function']['name'] == 'render_bar_chart']


def definitions(active, enabled: bool = False, history: bool = False,
                charts: bool = False) -> list[dict]:
    if not enabled and not history and not charts:
        return []
    if not getattr(active, 'inference_profile', {}).get('capabilities', {}).get('native_tools'):
        raise ValueError('This model/backend does not expose verified native tools.')
    return ((WEB_TOOLS if enabled else []) + (HISTORY_TOOLS if history else [])
            + (CHART_TOOLS if charts else []))


def chat_turns(messages: list[dict]) -> list[dict]:
    """Use the same tool-call grouping in Chat and Responses input accounting."""
    if not any(m.get('tool_calls') for m in messages):
        return messages
    result = []
    for message in messages:
        calls = message.get('tool_calls')
        if not calls:
            result.append(message)
            continue
        if message.get('content'):
            result.append({'role': 'assistant', 'content': message['content']})
        result.extend({'role': 'assistant', 'content': '', 'tool_calls': [call]} for call in calls)
    return result
