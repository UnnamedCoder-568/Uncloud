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
