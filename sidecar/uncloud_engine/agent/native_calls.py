"""Normalize complete native function blocks left as text by a backend."""
from __future__ import annotations

import json
import re

from .contracts import tool_contract, validate_args

_BLOCK = re.compile(
    r'\s*(?:<tool_call>\s*)?<function=([A-Za-z_][A-Za-z0-9_]*)>'
    r'(.*?)</function>\s*</tool_call>', re.DOTALL)
_PARAMETER = re.compile(r'\s*<parameter=([A-Za-z_][A-Za-z0-9_]*)>(.*?)</parameter>', re.DOTALL)


def from_text(content: str, specs: list[dict], template: str) -> list[dict]:
    """No prose/fences, invented calls, partial blocks, or code interpolation.

    Only use the native XML protocol declared by the selected model's template.
    A backend may consume the opening tool delimiter while leaving a complete
    function and closing delimiter in content. Interpret the same function
    schema, then let dispatch apply the usual permission and execution checks.
    """
    if not isinstance(template, str) or '<function=' not in template \
            or '<parameter=' not in template:
        return []
    text = content.strip()
    if not text.startswith(('<tool_call>', '<function=')):
        return []
    allowed = {spec['id']: spec for spec in specs}
    calls, offset = [], 0
    while offset < len(text):
        block = _BLOCK.match(text, offset)
        if block is None or len(calls) >= 40:
            raise ValueError('Incomplete or invalid native function block.')
        name, body = block.groups()
        if name not in allowed:
            raise ValueError(f'Unknown or disabled native function: {name}')
        spec = allowed[name]
        properties = tool_contract(spec)['parameters']['properties']
        args, position = {}, 0
        while position < len(body.rstrip()):
            parameter = _PARAMETER.match(body, position)
            if parameter is None:
                raise ValueError('Invalid native function parameters.')
            key, value = parameter.groups()
            if key in args or key not in properties:
                raise ValueError(f'Unknown or duplicate native parameter: {key}')
            if value.startswith('\n'):
                value = value[1:]
            if value.endswith('\n'):
                value = value[:-1]
            kinds = properties[key]['type']
            kinds = [kinds] if isinstance(kinds, str) else kinds
            if 'string' not in kinds or ('array' in kinds and value.lstrip().startswith('[')) \
                    or ('object' in kinds and value.lstrip().startswith('{')):
                value = json.loads(value)
            args[key] = value
            position = parameter.end()
        validate_args(spec, args)
        calls.append({'type': 'function', 'function': {'name': name, 'arguments': args}})
        offset = block.end()
        if not text[offset:].strip():
            break
    return calls
