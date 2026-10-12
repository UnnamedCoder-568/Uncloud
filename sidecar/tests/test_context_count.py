import asyncio
import json
from collections import UserDict
from types import SimpleNamespace

import httpx
import pytest

from uncloud_engine import context_count


@pytest.mark.parametrize(
    "encoded",
    [
        [1, 2, 3, 4],
        UserDict(input_ids=[1, 2, 3, 4], attention_mask=[1] * 4),
        {"input_ids": [[1, 2, 3, 4]]},
    ],
)
def test_native_template_counts_tokens_not_encoding_fields(monkeypatch, encoded):
    class Tokenizer:
        chat_template = "native"

        def apply_chat_template(self, turns, **kwargs):
            assert kwargs == {"tokenize": True, "add_generation_prompt": True}
            return encoded

    monkeypatch.setattr(context_count, "_mlx_tokenizer", lambda _: Tokenizer())
    assert context_count._count_mlx("model", [{"role": "user", "content": "hi"}]) == 4


def test_gguf_native_counter_accepts_zero_without_falling_back(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import httpx

    requests = []

    def handler(request):
        requests.append(request.url.path)
        return httpx.Response(200, json={"input_tokens": 0})

    factory = httpx.AsyncClient
    monkeypatch.setattr(
        context_count.httpx,
        "AsyncClient",
        lambda **kwargs: factory(transport=httpx.MockTransport(handler), **kwargs),
    )
    assert (
        asyncio.run(
            context_count.count(SimpleNamespace(engine="gguf", base_url="http://model"), [])
        )
        == 0
    )
    assert requests == ["/v1/chat/completions/input_tokens"]


def test_input_counter_is_independent_of_an_oversized_reply_ceiling(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert 'max_tokens' not in body
        assert body['chat_template_kwargs'] == {'enable_thinking': False}
        return httpx.Response(200, json={'input_tokens': 15})
    client = httpx.AsyncClient
    monkeypatch.setattr(context_count.httpx, 'AsyncClient',
        lambda **kw: client(transport=httpx.MockTransport(handler), **kw))
    active = SimpleNamespace(engine='gguf', base_url='http://native', context_limit=1024,
        inference_profile={'capabilities': {'fields': ['max_tokens'], 'reasoning': {
            'mechanism': 'template_toggle', 'levels': ['auto', 'off', 'high']}}})
    assert asyncio.run(context_count.count(active, [{'role': 'user', 'content': 'Hi'}],
        {'max_tokens': 4096, 'reasoning': 'off'})) == 15


def test_vlm_counts_native_prompt_and_preserves_thinking_and_images(monkeypatch):
    def handler(request):
        assert request.url.path == '/v1/responses/input_tokens'
        body = json.loads(request.content)
        assert body['enable_thinking'] is False
        assert body['input'] == [{'role': 'user', 'content': [
            {'type': 'input_text', 'text': 'Describe this'},
            {'type': 'input_image', 'image_url': 'data:image/png;base64,test'},
        ]}]
        return httpx.Response(200, json={'input_tokens': 314})
    client = httpx.AsyncClient
    monkeypatch.setattr(context_count.httpx, 'AsyncClient',
        lambda **kw: client(transport=httpx.MockTransport(handler), **kw))
    active = SimpleNamespace(engine='mlx-vlm', base_url='http://native', model_path='/model',
                             inference_profile={'capabilities': {'fields': [], 'reasoning': {
                                 'mechanism': 'template_toggle', 'levels': ['auto', 'off', 'high'],
                             }}})
    messages = [{'role': 'user', 'content': [
        {'type': 'text', 'text': 'Describe this'},
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test'}},
    ]}]
    assert asyncio.run(context_count.count(active, messages, {'reasoning': 'off'})) == 314
