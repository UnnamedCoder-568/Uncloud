import asyncio
import json

import httpx
import pytest

from uncloud_engine.agent.planning_stream import completion, repeated_reasoning


class Stream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield ('data: ' + json.dumps(chunk) + '\n\n').encode()
        yield b'data: [DONE]\n\n'

    async def aclose(self):
        self.closed = True


def chunk(**delta):
    return {'choices': [{'delta': delta, 'finish_reason': None}]}


def read(chunks):
    stream = Stream(chunks)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={'content-type': 'text/event-stream'},
                                           stream=stream))) as client:
            response = await completion(client, 'http://local/v1/chat/completions',
                                        json={'stream': True}, timeout=5)
            return response.json()
    return stream, exercise


def test_streamed_plans_keep_only_answer_content_and_close_transport():
    stream, exercise = read([
        chunk(reasoning_content='Private model reasoning, not a task plan.'),
        chunk(content='{"tasks":'), chunk(content='{}}'),
        {'choices': [{'delta': {}, 'finish_reason': 'stop'}]},
    ])
    result = asyncio.run(exercise())
    assert result['choices'][0]['message'] == {'content': '{"tasks":{}}'}
    assert 'Private' not in json.dumps(result)
    assert stream.closed


@pytest.mark.parametrize('field', ['reasoning_content', 'reasoning'])
def test_repeated_reasoning_aborts_and_closes_without_returning_a_plan(field):
    loop = 'Reconsidering the same unsupported approach without any new result. '
    stream, exercise = read([chunk(**{field: loop * 8})])
    with pytest.raises(ValueError, match='Repeated reasoning'):
        asyncio.run(exercise())
    assert stream.closed


def test_native_tool_call_fragments_preserve_arguments_and_order():
    stream, exercise = read([
        chunk(tool_calls=[{'index': 1, 'id': 'second', 'function': {
            'name': 'fs_read', 'arguments': '{"path":"other.txt"}'}}]),
        chunk(tool_calls=[{'index': 0, 'id': 'first', 'function': {
            'name': 'python_exec', 'arguments': '{"code":"print('}}]),
        chunk(tool_calls=[{'index': 0, 'function': {'arguments': "42)\"}"}}]),
        {'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}]},
    ])
    message = asyncio.run(exercise())['choices'][0]['message']
    assert [call['id'] for call in message['tool_calls']] == ['first', 'second']
    assert json.loads(message['tool_calls'][0]['function']['arguments']) == {'code': 'print(42)'}
    assert stream.closed


def test_legitimate_repeated_answer_text_is_not_treated_as_a_reasoning_loop():
    text = 'repeated output data ' * 80
    _, exercise = read([chunk(content=text),
                       {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}])
    assert asyncio.run(exercise())['choices'][0]['message']['content'] == text
    assert not repeated_reasoning(' ' * 5000)
    assert not repeated_reasoning(''.join(f'Checking distinct result {i}. ' for i in range(100)))


def test_truncated_stream_is_not_a_completed_plan():
    stream, exercise = read([chunk(content='{"tasks":')])
    with pytest.raises(ValueError, match='before a complete response'):
        asyncio.run(exercise())
    assert stream.closed


def test_nonstreaming_json_backend_remains_supported():
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={'choices': [{
                'message': {'content': '{"tasks":{}}'}, 'finish_reason': 'stop'}]}))) as client:
            response = await completion(client, 'http://local/v1/chat/completions',
                                        json={'stream': True}, timeout=5)
            return response.json()
    assert asyncio.run(exercise())['choices'][0]['finish_reason'] == 'stop'
