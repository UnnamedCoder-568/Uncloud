"""Typed, neutral tool contracts used by both planning and dispatch."""
from __future__ import annotations

import json
import math

_ARRAY = {'type': 'array', 'items': {'type': 'string'}}
_OPTIONAL = {
    'ask_user': {'options'}, 'capability': {'provider', 'arguments'}, 'fs_list': {'path'},
    'video_frames': {'start', 'duration', 'count'}, 'browser_console': {'level'},
    'browser_network': {'contains'}, 'browser_click_at': {'button', 'clicks'},
    'browser_scroll_at': {'dy'}, 'app_open': {'target', 'app'}, 'computer_click': {'button'},
    'shell': {'cwd'}, 'python_exec': {'cwd'},
}
_TYPES = {
    'ask_user': {'options': _ARRAY},
    'capability': {'arguments': {'type': 'object'}},
    'python_exec': {'output_paths': {'type': 'array',
                                    'items': {'type': 'string', 'format': 'path'}}},
    'document_write': {'paragraphs': _ARRAY, 'rows': {'type': 'array', 'items': {
        'type': 'array', 'items': {'type': ['string', 'number', 'boolean', 'null']}}}},
    'video_frames': {'start': {'type': 'number'}, 'duration': {'type': 'number'},
                     'count': {'type': 'integer'}},
    'browser_click_at': {'clicks': {'type': 'integer', 'minimum': 1}},
    'browser_type': {'submit': {'type': 'boolean'}},
    'browser_screenshot': {'full_page': {'type': 'boolean'}},
    'plan_set': {'steps': _ARRAY},
    'plan_update': {'n': {'type': 'integer', 'minimum': 1},
                    'status': {'type': 'string', 'enum': ['todo', 'doing', 'done', 'blocked']}},
    'computer_key': {'keys': {'type': ['string', 'array'], 'items': {'type': 'string'}}},
    'computer_scroll': {'amount': {'type': 'integer', 'minimum': -20, 'maximum': 20}},
    'generate_image': {key: {'type': 'integer'} for key in ('steps', 'width', 'height', 'seed')},
}
_TYPES['generate_image']['guidance'] = {'type': 'number'}
for _tool, _names in {
    'browser_move': ('x', 'y'), 'browser_click_at': ('x', 'y'),
    'browser_drag': ('x1', 'y1', 'x2', 'y2'), 'browser_scroll_at': ('x', 'y', 'dy'),
    'computer_move': ('x', 'y'), 'computer_click': ('x', 'y'), 'computer_drag': ('x', 'y'),
}.items():
    _TYPES.setdefault(_tool, {}).update({
        key: {'type': 'integer' if _tool.startswith('computer_') else 'number'} for key in _names})
for _tool in ('computer_click', 'browser_click_at'):
    _TYPES[_tool]['button'] = {'type': 'string', 'enum': ['left', 'right', 'middle']}


def tool_contract(spec: dict) -> dict:
    properties, required = {}, []
    for arg in spec['args']:
        name = arg.split(' ', 1)[0]
        properties[name] = _TYPES.get(spec['id'], {}).get(name, {'type': 'string'})
        if '(optional)' not in arg and name not in _OPTIONAL.get(spec['id'], set()):
            required.append(name)
    contract = {'id': spec['id'], 'parameters': {
        'type': 'object', 'properties': properties, 'required': required,
        'additionalProperties': False}}
    if spec['id'] == 'fs_write':
        contract['encoding'] = 'utf-8'
        contract['format'] = 'text'
    elif spec['id'] == 'python_exec':
        contract['runtime'] = 'engine_python'
        contract['modules'] = ['reportlab', 'pypdf', 'docx', 'openpyxl', 'PIL']
    elif spec['id'] == 'document_write':
        contract['formats'] = ['pdf', 'docx', 'xlsx']
    return contract


def native_tool(spec: dict) -> dict:
    """Retain machine-readable execution metadata in the native schema."""
    contract = tool_contract(spec)
    metadata = {key: value for key, value in contract.items()
                if key not in {'id', 'parameters'}}
    parameters = dict(contract['parameters'])
    if metadata:
        parameters['$comment'] = json.dumps(metadata, separators=(',', ':'))
    return {'type': 'function', 'function': {'name': spec['id'], 'parameters': parameters}}


def plan_schema(specs: list[dict]) -> dict:
    """The same enabled tool contracts, enforced by native structured decoding."""
    def native(schema):
        if isinstance(schema, list):
            return [native(value) for value in schema]
        if not isinstance(schema, dict):
            return schema
        result = {key: native(value) for key, value in schema.items()
                  if not (key == 'format' and isinstance(value, str))}
        if result.get('type') == 'object' and 'properties' not in result:
            result.setdefault('additionalProperties', True)
        return result

    variants = [{'type': 'object', 'properties': {
        'tool_id': {'type': 'string', 'enum': [spec['id']]},
        'description': {'type': 'string'},
        'args': native(tool_contract(spec)['parameters']),
        'dependencies': {'type': 'array', 'items': {'type': 'string'}},
    }, 'required': ['tool_id', 'args'], 'additionalProperties': False} for spec in specs]
    return {'type': 'object', 'properties': {
        'tasks': {'type': 'object', 'additionalProperties': {'anyOf': variants}},
        'start_node_ids': {'type': 'array', 'items': {'type': 'string'}},
    }, 'required': ['tasks'], 'additionalProperties': False}


def _validate(value, schema: dict, path: str) -> None:
    kinds = schema.get('type', [])
    kinds = [kinds] if isinstance(kinds, str) else kinds
    matches = {
        'string': isinstance(value, str), 'object': isinstance(value, dict),
        'array': isinstance(value, list), 'boolean': isinstance(value, bool),
        'integer': isinstance(value, int) and not isinstance(value, bool),
        'number': isinstance(value, (int, float)) and not isinstance(value, bool)
                  and math.isfinite(value),
        'null': value is None,
    }
    if kinds and not any(matches.get(kind, False) for kind in kinds):
        raise ValueError(f'{path}: expected {" or ".join(kinds)}')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{path}: expected one of {schema["enum"]}')
    for bound, relation in (('minimum', lambda a, b: a < b),
                            ('maximum', lambda a, b: a > b)):
        if bound in schema and relation(value, schema[bound]):
            raise ValueError(f'{path}: outside {bound} {schema[bound]}')
    if isinstance(value, list) and 'items' in schema:
        for index, item in enumerate(value):
            _validate(item, schema['items'], f'{path}[{index}]')
    if isinstance(value, dict) and 'properties' in schema:
        missing = set(schema.get('required', [])) - value.keys()
        unknown = value.keys() - schema['properties'].keys()
        if missing or (unknown and not schema.get('additionalProperties', True)):
            raise ValueError(f'{path}: missing {sorted(missing)}, unknown {sorted(unknown)}')
        for key, item in value.items():
            if key in schema['properties']:
                _validate(item, schema['properties'][key], f'{path}.{key}')


def validate_args(spec: dict, args: dict, *, references: bool = False) -> None:
    schema = tool_contract(spec)['parameters']
    if references:
        # A full output reference may resolve to a typed value at execution time.
        import re

        schema = {**schema, 'properties': {key: (
            {} if isinstance(args.get(key), str)
            and re.fullmatch(r'\{\{\s*\w+(?:\.output)?\s*\}\}', args[key]) else value
        ) for key, value in schema['properties'].items()}}
    _validate(args, schema, spec['id'])
    if spec['id'] == 'document_write' and not references:
        from .documents import validate_document

        validate_document(args)
    if spec['id'] == 'python_exec' and (not references or '{{' not in args['code']):
        try:
            compile(args['code'], '<chisel>', 'exec')
        except SyntaxError as exc:
            raise ValueError(f'python_exec: {exc.msg} at line {exc.lineno}') from exc
