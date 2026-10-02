from collections import UserDict

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
