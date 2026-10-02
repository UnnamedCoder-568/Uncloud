"""Native plain-chat payloads and the legacy agent effort policy."""

from __future__ import annotations

from .core import Effort, ModelProfile, translate


def model_payload(active, messages: list[dict], *, overrides: dict | None = None,
                  max_tokens: int | None = None, effort: str = "") -> dict:
    """Native model recommendations with explicit request overrides.

    Balanced/default chat keeps the model's native thinking/template behavior.
    Advanced effort remains opt-in and never launches additional model passes.
    """
    from .inference_profile import for_backend

    metadata = getattr(active, "inference_profile", {})
    payload = {"messages": messages, "stream": True, "stream_options": {"include_usage": True}}
    payload.update(for_backend(metadata.get("parameters", {}), overrides or {}, active.engine))
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    elif metadata.get("max_output_tokens"):
        payload["max_tokens"] = metadata["max_output_tokens"]
    elif active.engine != "gguf" and getattr(active, "context_limit", 0):
        # Reserve a quarter of this runtime's usable window for output when
        # the model gives no recommendation. Avoid MLX's silent 512-token cap,
        # which can consume the whole answer in reasoning. User budgets win.
        payload["max_tokens"] = max(1, active.context_limit // 4)
    if effort and effort != "balanced":
        model = getattr(active, "model_profile", None)
        plan = translate(effort, model, **(
            {"base_output_tokens": max_tokens} if max_tokens is not None else {}))
        if "enable_thinking" in plan.parameters:
            payload["chat_template_kwargs"] = {
                "enable_thinking": bool(plan.parameters["enable_thinking"])}
        if max_tokens is None:
            payload["max_tokens"] = plan.max_output_tokens
    return payload


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
