"""One control, translated per model.

The property worth testing is not that a level sets a parameter — it is that a
level buys something on a model that has NO reasoning parameter, which is
almost all of them, and that where it cannot the plan says so out loud.
"""

from __future__ import annotations

import pytest

from uncloud_engine.chat import build_chat_payload
from uncloud_engine.core import (
    BASE_OUTPUT_TOKENS,
    ORDER,
    Capability,
    Effort,
    ModelProfile,
    ReasoningSupport,
    describe,
    parse,
    translate,
)


def model(reasoning=ReasoningSupport.NONE, runtime="gguf", **kwargs):
    return ModelProfile(id="m", name="A Model", runtime=runtime,
                        capabilities=frozenset({Capability.TEXT_GENERATE}),
                        reasoning=reasoning, **kwargs)


# ------------------------------------------------------------------ levels
def test_the_levels_are_ordered_and_complete() -> None:
    assert ORDER == (Effort.FAST, Effort.BALANCED, Effort.DEEP, Effort.MAXIMUM)


def test_effort_rises_monotonically() -> None:
    """Each level has to be visibly more than the last, or the control is
    decoration."""
    plans = [translate(level, model()) for level in ORDER]
    assert [p.passes for p in plans] == sorted(p.passes for p in plans)
    assert [p.tool_iterations for p in plans] == sorted(p.tool_iterations for p in plans)
    assert [p.max_output_tokens for p in plans] == sorted(p.max_output_tokens for p in plans)


def test_an_unreadable_level_falls_back_rather_than_failing() -> None:
    """Effort is a preference, and a preference must never break a job."""
    assert parse("enthusiastic") is Effort.BALANCED
    assert parse(None) is Effort.BALANCED
    assert parse("") is Effort.BALANCED
    assert parse("MAXIMUM") is Effort.MAXIMUM
    assert parse(Effort.DEEP) is Effort.DEEP


# --------------------------------------------------------------- reasoning
def test_a_model_that_can_think_is_asked_to_at_the_deep_levels() -> None:
    thinker = model(reasoning=ReasoningSupport.THINKING_TOGGLE)
    assert translate(Effort.DEEP, thinker).parameters["enable_thinking"] is True
    assert translate(Effort.MAXIMUM, thinker).parameters["enable_thinking"] is True
    assert translate(Effort.DEEP, thinker).thinks is True


def test_a_model_that_can_think_is_told_not_to_at_the_fast_levels() -> None:
    """Off explicitly rather than by omission. Left alone Qwen3 thinks by
    default, which at Fast is exactly what was not asked for."""
    thinker = model(reasoning=ReasoningSupport.THINKING_TOGGLE)
    assert translate(Effort.FAST, thinker).parameters["enable_thinking"] is False
    assert translate(Effort.BALANCED, thinker).parameters["enable_thinking"] is False


def test_a_model_with_no_reasoning_control_still_gets_more_from_maximum() -> None:
    """The whole point of translating rather than forwarding."""
    plain = model()
    fast, most = translate(Effort.FAST, plain), translate(Effort.MAXIMUM, plain)
    assert most.passes > fast.passes
    assert most.candidates > fast.candidates
    assert most.reviewer and not fast.reviewer
    assert most.max_output_tokens > fast.max_output_tokens
    assert "enable_thinking" not in most.parameters


def test_a_model_that_cannot_think_says_so_rather_than_pretending() -> None:
    plan = translate(Effort.MAXIMUM, model())
    assert plan.degraded, "a level that bought no reasoning reported nothing"
    assert "no reasoning control" in plan.degraded[0]
    assert plan.thinks is False


def test_a_budget_model_gets_a_share_of_its_context() -> None:
    budgeted = model(reasoning=ReasoningSupport.BUDGET_TOKENS, context_tokens=32768)
    plan = translate(Effort.MAXIMUM, budgeted)
    assert plan.parameters["reasoning_max_tokens"] == int(32768 * 0.4)


def test_a_provider_with_its_own_levels_is_handed_the_level() -> None:
    native = model(reasoning=ReasoningSupport.EFFORT_LEVEL)
    assert translate(Effort.DEEP, native).parameters["reasoning_effort"] == "deep"


# ----------------------------------------------------------------- runtime
def test_a_runtime_that_takes_no_output_limit_says_so() -> None:
    """mflux draws pictures. Sending it a token budget would do nothing, and
    silently doing nothing is the failure mode this whole layer avoids."""
    plan = translate(Effort.MAXIMUM, model(runtime="mflux"))
    assert "max_tokens" not in plan.parameters
    assert any("output limit" in d for d in plan.degraded)


def test_a_model_ceiling_is_never_exceeded() -> None:
    small = model(max_output_tokens=512)
    assert translate(Effort.MAXIMUM, small).max_output_tokens == 512


def test_translation_works_with_no_model_at_all() -> None:
    """Nothing is loaded on a fresh install, and the orchestration half of a
    plan is still valid."""
    plan = translate(Effort.DEEP, None)
    assert plan.passes == 3 and plan.reviewer is True


# ------------------------------------------------------------------- chat
def test_chat_switches_thinking_off_at_the_fast_levels() -> None:
    payload = build_chat_payload([], temperature=0.7, max_tokens=1024,
                                 engine="gguf", effort=Effort.FAST)
    assert payload["chat_template_kwargs"]["enable_thinking"] is False
    assert payload["thinking_budget_tokens"] == 0
    assert payload["reasoning_effort"] == "none"


def test_chat_switches_thinking_on_when_the_model_can_and_the_level_asks() -> None:
    thinker = model(reasoning=ReasoningSupport.THINKING_TOGGLE)
    payload = build_chat_payload([], temperature=0.7, max_tokens=1024,
                                 engine="gguf", effort=Effort.DEEP, model=thinker)
    assert payload["chat_template_kwargs"]["enable_thinking"] is True
    assert payload["thinking_budget_tokens"] > 0
    assert payload["reasoning_effort"] == "deep"


def test_effort_scales_the_callers_ceiling_rather_than_replacing_it() -> None:
    """A caller that asked for 8000 is never quietly cut to a default because
    somebody set the level low. Effort is a multiplier on their intent, not a
    second opinion about it."""
    fast = build_chat_payload([], temperature=0.7, max_tokens=8000,
                              engine="gguf", effort=Effort.FAST)
    assert fast["max_tokens"] == 8000


def test_chat_raises_the_ceiling_at_the_deep_levels() -> None:
    fast = build_chat_payload([], temperature=0.7, max_tokens=1024,
                              engine="gguf", effort=Effort.FAST)
    most = build_chat_payload([], temperature=0.7, max_tokens=1024,
                              engine="gguf", effort=Effort.MAXIMUM)
    assert fast["max_tokens"] == 1024
    assert most["max_tokens"] == 2048


def test_the_shared_default_is_only_used_when_nobody_asked() -> None:
    assert translate(Effort.FAST, None).max_output_tokens == BASE_OUTPUT_TOKENS


# -------------------------------------------------------------- describing
def test_every_level_is_described_for_the_loaded_model() -> None:
    levels = describe(model())
    assert [entry["id"] for entry in levels] == [e.value for e in ORDER]
    assert all(entry["blurb"] for entry in levels)
    # And the levels that buy nothing extra say what they buy instead.
    assert any(entry["degraded"] for entry in levels)


def test_describing_with_a_thinking_model_marks_which_levels_think() -> None:
    levels = describe(model(reasoning=ReasoningSupport.THINKING_TOGGLE))
    thinking = [entry["id"] for entry in levels if entry["thinks"]]
    assert thinking == ["deep", "maximum"]


# -------------------------------------------------------------- over HTTP
def test_the_effort_route_reports_the_selection_and_the_levels() -> None:
    from fastapi.testclient import TestClient

    from uncloud_engine import main

    client = TestClient(main.app)
    client.headers.update({"Authorization": f"Bearer {main.settings.token}"})

    body = client.get("/api/effort").json()
    assert [entry["id"] for entry in body["levels"]] == [e.value for e in ORDER]

    was = body["selected"]
    try:
        assert client.post("/api/effort", json={"effort": "deep"}).json()["selected"] \
            == "deep"
        # An unreadable value settles rather than failing.
        assert client.post("/api/effort", json={"effort": "???"}).json()["selected"] \
            == "balanced"
    finally:
        client.post("/api/effort", json={"effort": was})
