"""Request policy for the plain chat surface.

Two things happen here that are easy to get wrong and invisible when you do.

**Thinking is switched off explicitly, not by omission.** Thinking-capable GGUF
templates default to an unlimited private reasoning pass, and small Qwen
variants can loop there without ever emitting an answer — measured this year at
fifteen seconds producing an unterminated block and no reply. Chat is a
direct-answer surface, so Fast and Balanced say no out loud.

**Effort is translated, not forwarded.** Almost no local model takes a
reasoning parameter. What a level buys on a model that has none is a bigger
answer budget and, above this layer, more passes — see `foundation.effort`.
"""

from __future__ import annotations

from .foundation import Effort, ModelProfile, translate


def build_chat_payload(
    messages: list[dict], *, temperature: float, max_tokens: int, engine: str,
    effort: Effort | str = Effort.BALANCED, model: ModelProfile | None = None,
) -> dict:
    """Build a bounded request for a local inference server.

    `max_tokens` is the caller's own figure and effort SCALES it rather than
    replacing it. A caller that asked for 1024 gets 1024 at Fast and twice that
    at Maximum; one that asked for 8000 is never quietly cut to a default
    because somebody set the level low. Effort is a multiplier on the caller's
    intent, not a second opinion about it.
    """
    plan = translate(effort, model, base_output_tokens=max_tokens)
    payload: dict = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": plan.max_output_tokens,
        "stream": True,
    }

    thinking = bool(plan.parameters.get("enable_thinking"))
    if engine == "gguf":
        # llama.cpp takes template arguments through this envelope rather than
        # as top-level fields, and ignores anything it does not recognise —
        # which is why all three spellings are sent.
        payload["chat_template_kwargs"] = {"enable_thinking": thinking}
        payload["thinking_budget_tokens"] = plan.max_output_tokens if thinking else 0
        payload["reasoning_effort"] = plan.effort.value if thinking else "none"
    elif "enable_thinking" in plan.parameters:
        payload["chat_template_kwargs"] = {"enable_thinking": thinking}

    for name in ("reasoning_max_tokens", "reasoning_effort"):
        if name in plan.parameters:
            payload[name] = plan.parameters[name]
    return payload
