"""Request policy for the plain chat surface."""

from __future__ import annotations


def build_chat_payload(
    messages: list[dict], *, temperature: float, max_tokens: int, engine: str,
) -> dict:
    """Build a bounded, direct-answer request for a local inference server."""
    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if engine == "gguf":
        payload["chat_template_kwargs"] = {"enable_thinking": False}
        payload["thinking_budget_tokens"] = 0
        payload["reasoning_effort"] = "none"
    return payload
