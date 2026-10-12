"""CPU-only regression specifications; no model loading or native generation."""

from types import SimpleNamespace

import pytest

from uncloud_engine.chat import model_payload
from uncloud_engine.mlx_server import BoundedThinkingSampler, install


class ScalarArrays:
    """Minimal array operations for testing the sampler state machine on CPU."""

    array = staticmethod(lambda value: value)
    take = staticmethod(lambda values, index: values[index])
    minimum = staticmethod(min)
    full_like = staticmethod(lambda _, value: value)
    where = staticmethod(lambda condition, yes, no: yes if condition else no)
    logical_or = staticmethod(lambda a, b: a or b)
    logical_and = staticmethod(lambda a, b: a and b)
    logical_not = staticmethod(lambda value: not value)


def active(engine="mlx", context=8192, budget=True, mechanism="template_toggle"):
    return SimpleNamespace(engine=engine, context_limit=context, inference_profile={
        "parameters": {}, "capabilities": {
            "fields": ["temperature", "max_tokens", *(["reasoning_budget"] if budget else [])],
            "reasoning": {"mechanism": mechanism,
                "levels": ["auto", "off", "low", "medium", "high", "max"],
                **({"budget": {"mechanism": "mlx_sampler" if engine == "mlx" else "llama_cpp",
                                "closing_tokens": 1}} if budget else {})},
        }})


@pytest.mark.parametrize("level,expected", [("auto", 128), ("low", 128), ("medium", 256),
                                         ("high", 512), ("max", 767)])
def test_effort_bounds_reasoning_and_leaves_answer_space(level, expected):
    payload = model_payload(active(), [], max_tokens=1024, inference={"reasoning": level})
    assert payload["thinking_budget_tokens"] == expected
    assert payload["max_tokens"] == 1024
    assert "reasoning_effort" not in payload


def test_budget_scales_with_model_runtime_and_user_reply_allowance():
    assert model_payload(active(context=4096), [], inference={"reasoning": "high"})[
        "thinking_budget_tokens"] == 512
    assert model_payload(active(context=8192), [], inference={"reasoning": "high"})[
        "thinking_budget_tokens"] == 1024
    specified = model_payload(active(), [], inference={"max_tokens": 512})
    assert specified["thinking_budget_tokens"] == 64
    explicit = model_payload(active(), [], max_tokens=512,
                             inference={"reasoning": "high", "reasoning_budget": 80})
    assert explicit["thinking_budget_tokens"] == 80


def test_auto_preserves_unbounded_native_default_without_inventing_a_reply_ceiling():
    payload = model_payload(active('gguf', context=131072), [{'role': 'user', 'content': 'hello'}])
    assert 'max_tokens' not in payload
    assert 'thinking_budget_tokens' not in payload


def test_explicit_limit_and_off_are_authoritative():
    off = model_payload(active(), [], inference={"reasoning": "off"})
    assert off["thinking_budget_tokens"] == 0
    for value in [False, -1, 1.2]:
        with pytest.raises(ValueError):
            model_payload(active(), [], inference={"reasoning_budget": value})
    with pytest.raises(ValueError, match="room"):
        model_payload(active(), [], max_tokens=128, inference={"reasoning_budget": 127})
    immediate = model_payload(active(), [], max_tokens=2, inference={"reasoning_budget": 0})
    assert immediate["thinking_budget_tokens"] == 0


def test_unsupported_backends_receive_no_fake_budget():
    payload = model_payload(active(budget=False), [])
    assert "thinking_budget_tokens" not in payload
    with pytest.raises(ValueError, match="Unsupported"):
        model_payload(active(budget=False), [], inference={"reasoning_budget": 64})


def test_budget_preserves_true_native_effort_and_uses_gguf_native_field():
    payload = model_payload(active("gguf", mechanism="template_effort"), [],
                            max_tokens=1024, inference={"reasoning": "high"})
    assert payload["chat_template_kwargs"] == {"reasoning_effort": "high"}
    assert payload["thinking_budget_tokens"] == 512


def test_always_thinking_model_gets_budget_without_an_invented_toggle():
    payload = model_payload(active(mechanism="native_fixed_or_unknown"), [],
                            max_tokens=1024, inference={"reasoning": "high"})
    assert payload["thinking_budget_tokens"] == 512
    assert "chat_template_kwargs" not in payload


def test_vlm_uses_its_native_budget_field_and_tokenizer_markers():
    model = active("mlx-vlm")
    model.inference_profile["capabilities"]["reasoning"]["budget"] = {
        "mechanism": "mlx_vlm", "native_field": "thinking_budget", "closing_tokens": 2,
        "start_sequence": "<|channel>", "end_sequence": "<channel|>",
    }
    model.inference_profile["capabilities"]["reasoning"]["default"] = "off"
    auto = model_payload(model, [], max_tokens=1024)
    assert "thinking_budget" not in auto
    assert "enable_thinking" not in auto
    high = model_payload(model, [], max_tokens=1024, inference={"reasoning": "high"})
    assert high["thinking_budget"] == 512
    assert high["enable_thinking"] is True
    assert high["thinking_start_token"] == "<|channel>"
    assert high["thinking_end_token"] == "<channel|>"
    assert "thinking_budget_tokens" not in high
    assert "chat_template_kwargs" not in high


def sampler(tokens, budget, end=(99,)):
    values = iter(tokens)
    return BoundedThinkingSampler(lambda _: next(values), end, budget, ScalarArrays)


def test_forced_boundary_then_answer_uses_the_same_sampler():
    bounded = sampler([10, 11, 12, 13, 14, 15], 2)
    assert [bounded(None) for _ in range(6)] == [10, 11, 99, 13, 14, 15]


def test_natural_boundary_is_not_delayed_or_forced_again():
    bounded = sampler([10, 99, 12, 13, 14], 2)
    assert [bounded(None) for _ in range(5)] == [10, 99, 12, 13, 14]


def test_multi_token_boundary_and_independent_requests():
    first = sampler([1, 2, 3, 4, 5], 1, end=(90, 91))
    second = sampler([8, 9, 10], 1)
    assert first(None) == 1
    assert second(None) == 8
    assert first(None) == 90
    assert second(None) == 99
    assert first(None) == 91
    assert first(None) == 4
    assert second(None) == 10


def test_zero_budget_closes_before_generating_thought():
    bounded = sampler([1, 2, 3], 0)
    assert [bounded(None) for _ in range(3)] == [99, 2, 3]


def test_reopened_thinking_uses_remaining_budget_not_a_new_allowance():
    values = iter([1, 99, 88, 2, 3, 4, 88, 5, 6])
    bounded = BoundedThinkingSampler(lambda _: next(values), (99,), 2, ScalarArrays,
                                    start_tokens=(88,))
    assert [bounded(None) for _ in range(9)] == [1, 99, 88, 2, 99, 4, 88, 99, 6]


def test_generated_thinking_start_is_bounded_without_modifying_prior_answer_tokens():
    values = iter([1, 88, 2, 3, 4])
    bounded = BoundedThinkingSampler(lambda _: next(values), (99,), 1, ScalarArrays,
                                    start_tokens=(88,), initial_thinking=False)
    assert [bounded(None) for _ in range(5)] == [1, 88, 2, 99, 4]


def test_native_request_hook_consumes_budget_and_preserves_template_cache_and_stream():
    class Generator:
        def __init__(self):
            self.model_provider = SimpleNamespace(draft_model=None)

        def _tokenize(self, tokenizer, request, args):
            return [100], [[100]], ["assistant"], "reasoning"

    class Handler:
        def handle_completion(self, request, stop_words):
            return self.chat_template_kwargs

    tokens = iter([10, 11, 12, 13])
    server = SimpleNamespace(ResponseGenerator=Generator, APIHandler=Handler,
                             _make_sampler=lambda args, tokenizer: lambda _: next(tokens))
    install(server, ScalarArrays)
    handler = Handler()
    handler.body = {"thinking_budget_tokens": 2}
    handler.chat_template_kwargs = {"enable_thinking": True}
    kwargs = handler.handle_completion(None, [])
    assert kwargs == {"enable_thinking": True, "_uncloud_thinking_budget": 2}
    args = SimpleNamespace(chat_template_kwargs=kwargs, max_tokens=100)
    tokenizer = SimpleNamespace(has_thinking=True, think_end_tokens=(99,),
                                think_start_tokens=(88,), eos_token_ids=(100,))
    prompt = server.ResponseGenerator()._tokenize(tokenizer, None, args)
    assert prompt == ([100], [[100]], ["assistant"], "reasoning")
    bounded = server._make_sampler(args, tokenizer)
    assert [bounded(None) for _ in range(4)] == [10, 11, 99, 13]


def test_off_mode_does_not_add_a_sampler_or_change_tokens():
    class Generator:
        def __init__(self):
            self.model_provider = SimpleNamespace(draft_model=None)

        def _tokenize(self, tokenizer, request, args):
            return [], [[]], ["assistant"], "normal"

    class Handler:
        def handle_completion(self, request, stop_words):
            return self.chat_template_kwargs

    native_sampler = lambda _: 42  # noqa: E731
    server = SimpleNamespace(ResponseGenerator=Generator, APIHandler=Handler,
                             _make_sampler=lambda args, tokenizer: native_sampler)
    install(server, ScalarArrays)
    args = SimpleNamespace(chat_template_kwargs={"_uncloud_thinking_budget": 0,
                                                "enable_thinking": False}, max_tokens=10)
    generator = server.ResponseGenerator()
    generator._tokenize(None, None, args)
    assert server._make_sampler(args, None) is native_sampler


@pytest.mark.parametrize("failure", ["draft", "boundary", "eos", "room"])
def test_invalid_budget_fails_inside_native_tokenization_error_guard(failure):
    class Generator:
        model_provider = SimpleNamespace(draft_model=None)

        def _tokenize(self, tokenizer, request, args):
            return [], [[]], ["assistant"], "reasoning"

    class Handler:
        def handle_completion(self, request, stop_words):
            return None

    server = SimpleNamespace(ResponseGenerator=Generator, APIHandler=Handler,
                             _make_sampler=lambda args, tokenizer: lambda _: 42)
    install(server, ScalarArrays)
    args = SimpleNamespace(chat_template_kwargs={"_uncloud_thinking_budget": 2}, max_tokens=10)
    tokenizer = SimpleNamespace(has_thinking=True, think_end_tokens=(99,),
                                think_start_tokens=(88,), eos_token_ids=(100,))
    generator = Generator()
    if failure == "draft":
        generator.model_provider = SimpleNamespace(draft_model=object())
    elif failure == "boundary":
        tokenizer.think_end_tokens = ()
    elif failure == "eos":
        tokenizer.eos_token_ids = (99,)
    else:
        args.max_tokens = 3
    with pytest.raises(ValueError):
        generator._tokenize(tokenizer, None, args)


def test_vlm_budget_discovery_requires_native_support_and_declared_tokens(tmp_path, monkeypatch):
    import json

    from uncloud_engine import inference_controls

    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text('{"model_type":"gemma4_unified"}')
    config = {"chat_template": "enable_thinking | default(false) <|channel> <channel|>",
              "added_tokens_decoder": {"1": {"content": "<|channel>", "special": True},
                                       "2": {"content": "<channel|>", "special": True}}}
    (model / "tokenizer_config.json").write_text(json.dumps(config))
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    for name, contents in {
        "schemas.py": 'temperature: float; max_tokens: int',
        "generation.py": 'def _make_thinking_budget_criteria kw["thinking_budget"] '
                         '"temperature" "max_tokens"',
        "request_normalization.py": 'getattr(request, "thinking_budget")',
    }.items():
        (runtime / name).write_text(contents)
    monkeypatch.setattr(inference_controls.importlib.metadata, "distribution",
                        lambda _: SimpleNamespace(version="test", locate_file=lambda path:
                                                  runtime / path.rsplit("/", 1)[-1]))
    discovered = inference_controls.discover(str(model), "mlx-vlm")
    assert discovered["reasoning"]["default"] == "off"
    assert discovered["reasoning"]["budget"]["native_field"] == "thinking_budget"
    assert discovered["reasoning"]["levels"] == ["auto", "off", "low", "medium", "high", "max"]
    config["added_tokens_decoder"] = {}
    (model / "tokenizer_config.json").write_text(json.dumps(config))
    assert "budget" not in inference_controls.discover(str(model), "mlx-vlm")["reasoning"]
    (runtime / "generation.py").write_text('"temperature" "max_tokens"')
    assert "reasoning_budget" not in inference_controls.discover(str(model), "mlx-vlm")["fields"]
