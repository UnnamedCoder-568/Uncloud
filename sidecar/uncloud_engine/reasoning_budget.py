"""Pass an explicit thinking limit to backends that actually support one."""

from __future__ import annotations


def bound(active, payload: dict, reasoning: str = "auto") -> dict:
    profile = getattr(active, "inference_profile", {})
    capability = profile.get("capabilities", {}).get("reasoning", {}).get("budget")
    explicit = payload.pop("reasoning_budget", None)
    if not capability:
        return payload
    selected = explicit if explicit is not None else profile.get("reasoning_budget")
    if selected is None or reasoning == "off":
        return payload
    total = payload.get("max_tokens", active.context_limit)
    closing = capability.get("closing_tokens", 1)
    field = capability.get("native_field", "thinking_budget_tokens")
    if capability.get("mechanism") == "mlx_vlm":
        payload["thinking_start_token"] = capability["start_sequence"]
        payload["thinking_end_token"] = capability["end_sequence"]
    if total <= closing:
        raise ValueError("Reply budget must leave room for thinking, its boundary and an answer.")
    budget = selected
    if budget + closing >= total:
        raise ValueError("Thinking limit must leave room for the boundary and an answer.")
    payload[field] = budget
    return payload
