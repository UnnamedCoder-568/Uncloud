"""Compact recognized native tool headers without changing roles or call parsing.

No model file is edited. Unrecognized templates are preserved. Cached template
adaptation changes only fixed tool-header literals, never user messages, source
material, custom instructions, reasoning prefixes, or sampling parameters.
"""
from __future__ import annotations

import ast
import json
import re
from functools import lru_cache

_LITERAL = re.compile(r'''(\{\{-?\s*)("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')(\s*-?\}\})''')
_HEADER = '# Tools\n\nYou have access to the following functions:\n\n<tools>'
_XML = ('\n<tool_call>\n<function=example_function_name>'
        '\n<parameter=example_parameter_1>\nvalue_1\n</parameter>'
        '\n<parameter=example_parameter_2>\nvalue_2\n</parameter>'
        '\n</function>\n</tool_call>')
_JSON = '\n<tool_call>{"name":"NAME","arguments":{}}</tool_call>'


@lru_cache(maxsize=32)
def compact(template: str) -> str:
    """Only adapt a known tools header with a verified native call example."""
    replacements = 0

    def replace(match):
        nonlocal replacements
        try:
            value = ast.literal_eval(match[2])
        except (SyntaxError, ValueError):
            return match[0]
        if value == _HEADER:
            replacement = '<tools>'
        elif (value.startswith('\n\nIf you choose to call a function ONLY reply')
              and '<function=example_function_name>' in value
              and '<parameter=example_parameter_1>' in value
              and value.endswith('</IMPORTANT>')):
            replacement = _XML
        elif (value.startswith('\n\nFor each function call, return a json object')
              and '<tool_call>' in value and 'arguments' in value):
            replacement = _JSON
        else:
            return match[0]
        replacements += 1
        return match[1] + json.dumps(replacement) + match[3]

    result = _LITERAL.sub(replace, template)
    return result if replacements == 2 else template


def template_kwargs(active, tools: list[dict]) -> dict:
    """MLX request/count override; both consume the same adapted template."""
    if not tools or active.engine != 'mlx':
        return {}
    original = getattr(active, 'inference_profile', {}).get('capabilities', {}).get('template', '')
    adapted = compact(original)
    return {'chat_template': adapted} if adapted != original else {}


def cache_file(template: str) -> str:
    """One runtime cache entry, never a change to the model's original file."""
    import hashlib

    from .config import CONFIG_DIR

    name = hashlib.sha256(template.encode()).hexdigest() + '.jinja'
    path = CONFIG_DIR / 'cache' / 'tool-templates' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(template)
    return str(path)


def install_vlm(server) -> None:
    """Native API generation and token counting share this one renderer."""
    render = server.apply_chat_template

    def neutral(processor, config, prompt, **kwargs):
        if kwargs.get('tools'):
            original = getattr(processor, 'chat_template', None)
            if not isinstance(original, str):
                original = getattr(getattr(processor, 'tokenizer', None), 'chat_template', None)
            if isinstance(original, str) and (adapted := compact(original)) != original:
                kwargs['chat_template'] = adapted
        return render(processor, config, prompt, **kwargs)

    server.apply_chat_template = neutral
