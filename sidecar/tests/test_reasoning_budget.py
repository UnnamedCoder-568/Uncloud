"""Native reasoning stays native; only explicit supported limits are forwarded."""

from types import SimpleNamespace

import pytest

from uncloud_engine.chat import model_payload
from uncloud_engine.mlx_server import install_context_limit


def active(engine="gguf", context=8192, mechanism="template_toggle"):
    return SimpleNamespace(engine=engine, model_path='/selected/model', context_limit=context,
        inference_profile={
        "parameters": {}, "capabilities": {
            "fields": ["temperature", "max_tokens", "reasoning_budget"],
            "reasoning": {"mechanism": mechanism, "levels": ["auto", "off", "high"],
                "budget": {"mechanism": "llama_cpp", "closing_tokens": 1}},
        }})


@pytest.mark.parametrize("level", ["auto", "off", "high"])
def test_native_levels_never_invent_a_token_budget_or_output_allowance(level):
    payload = model_payload(active(), [], inference={"reasoning": level})
    assert "thinking_budget_tokens" not in payload
    assert "max_tokens" not in payload
    if level == "auto":
        assert "chat_template_kwargs" not in payload
    else:
        assert payload["chat_template_kwargs"] == {"enable_thinking": level != "off"}


def test_manual_output_limit_does_not_create_a_thinking_limit():
    payload = model_payload(active(), [], inference={"max_tokens": 512, "reasoning": "high"})
    assert payload["max_tokens"] == 512
    assert "thinking_budget_tokens" not in payload


def test_explicit_native_thinking_limit_is_not_scaled():
    payload = model_payload(active(), [], inference={"max_tokens": 512, "reasoning_budget": 80})
    assert payload["thinking_budget_tokens"] == 80
    assert payload["max_tokens"] == 512
    with pytest.raises(ValueError, match="room"):
        model_payload(active(), [], inference={"max_tokens": 128, "reasoning_budget": 127})


def test_native_graded_effort_is_forwarded_without_app_formulas():
    payload = model_payload(active(mechanism="template_effort"), [],
                            inference={"reasoning": "high", "max_tokens": 1024})
    assert payload["chat_template_kwargs"] == {"reasoning_effort": "high"}
    assert payload["max_tokens"] == 1024
    assert "thinking_budget_tokens" not in payload


def test_vlm_forwards_only_its_explicit_native_budget_fields():
    model = active("mlx-vlm")
    model.inference_profile["capabilities"]["reasoning"]["budget"] = {
        "mechanism": "mlx_vlm", "native_field": "thinking_budget", "closing_tokens": 2,
        "start_sequence": "<|channel>", "end_sequence": "<channel|>",
    }
    assert "thinking_budget" not in model_payload(model, [], inference={"reasoning": "high"})
    explicit = model_payload(model, [], inference={"reasoning_budget": 80})
    assert explicit["thinking_budget"] == 80
    assert explicit["thinking_start_token"] == "<|channel>"
    assert explicit["thinking_end_token"] == "<channel|>"


def test_mlx_context_guard_uses_the_existing_native_prompt_and_sampler():
    calls = []

    class Generator:
        def _tokenize(self, tokenizer, request, args):
            calls.append(request)
            return [10, 11, 12], [[10, 11, 12]], ["assistant"], "reasoning"

    sampler = object()
    server = SimpleNamespace(ResponseGenerator=Generator, _make_sampler=sampler)
    install_context_limit(server, 10)
    args = SimpleNamespace(max_tokens=10)
    result = server.ResponseGenerator()._tokenize(None, "request", args)
    assert args.max_tokens == 7
    assert result == ([10, 11, 12], [[10, 11, 12]], ["assistant"], "reasoning")
    assert calls == ["request"]
    assert server._make_sampler is sampler
    args.max_tokens = 2
    server.ResponseGenerator()._tokenize(None, "manual", args)
    assert args.max_tokens == 2


def test_mlx_context_guard_refuses_overflow_before_prefill():
    class Generator:
        def _tokenize(self, tokenizer, request, args):
            return [1, 2, 3], [], [], "normal"

    server = SimpleNamespace(ResponseGenerator=Generator)
    install_context_limit(server, 3)
    with pytest.raises(ValueError, match="Compact"):
        server.ResponseGenerator()._tokenize(None, None, SimpleNamespace(max_tokens=100))


def test_mlx_advertises_native_toggle_without_synthetic_grades(tmp_path):
    from uncloud_engine.inference_controls import discover

    (tmp_path / "config.json").write_text('{"model_type":"test"}')
    (tmp_path / "chat_template.jinja").write_text(
        '{% if enable_thinking %}<think>reason</think>{% endif %}')
    capabilities = discover(str(tmp_path), "mlx")
    assert capabilities["reasoning"]["levels"] == ["auto", "off", "high"]
    assert "budget" not in capabilities["reasoning"]
    assert "reasoning_budget" not in capabilities["fields"]
