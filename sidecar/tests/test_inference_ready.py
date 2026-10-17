import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from uncloud_engine import chat_transport, context_count, inference_ready


@pytest.mark.parametrize('engine', ['mlx', 'mlx-vlm'])
@pytest.mark.parametrize('adapter', [None, '/adapter'])
def test_initialization_is_one_token_without_persona_tools_or_saved_answers(
    monkeypatch, engine, adapter,
):
    sent = []

    def handle(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': 'discarded'}}]})

    factory = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: factory(
        transport=httpx.MockTransport(handle), **kw))
    counter = AsyncMock(return_value=5)
    monkeypatch.setattr(context_count, 'count', counter)
    active = SimpleNamespace(engine=engine, model_path='/checkpoint',
                             adapter_path=adapter, base_url='http://native')
    result = asyncio.run(inference_ready.prepare(active))
    assert result['ready'] is True
    assert sent == [{**({'model': '/checkpoint'} if engine == 'mlx-vlm' else {}),
                     **({'adapter_path': adapter} if engine == 'mlx-vlm' and adapter else {}),
                     'messages': [{'role': 'user', 'content': '.'}],
                     'stream': False, 'max_tokens': 1, 'temperature': 0}]
    assert 'discarded' not in str(result)
    assert counter.await_count == (1 if engine == 'mlx' else 0)


def test_native_warmup_is_not_repeated_for_gguf():
    assert asyncio.run(inference_ready.prepare(SimpleNamespace(engine='gguf'))) == {
        'source': 'native runtime'}


def test_minimal_input_rejection_is_reported_without_retrying_or_blocking_the_model(monkeypatch):
    post = AsyncMock(side_effect=httpx.ConnectError('native failed'))

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['trust_env'] is False
        yield SimpleNamespace(post=post)

    monkeypatch.setattr(httpx, 'AsyncClient', client)
    active = SimpleNamespace(engine='mlx-vlm', model_path='/checkpoint',
                             adapter_path='/adapter', base_url='http://native')
    result = asyncio.run(inference_ready.prepare(active))
    assert result['ready'] is False and result['error'] == 'ConnectError'
    assert post.await_count == 1
    assert post.call_args.kwargs['json']['adapter_path'] == '/adapter'


def test_chat_context_and_chisel_borrow_the_same_pool_without_closing_it(monkeypatch):
    client = SimpleNamespace(is_closed=False)
    monkeypatch.setattr(chat_transport, '_client', client)

    async def check():
        async with (chat_transport.connection() as first,
                    chat_transport.connection() as second):
            assert first is second is chat_transport.client() is client
        assert client.is_closed is False
    asyncio.run(check())
