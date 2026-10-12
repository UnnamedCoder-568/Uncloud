"""Visible Uncloud effort budgets, derived from this request's output allowance.

These shares are application policy, not claimed model-publisher defaults or
native reasoning grades. Explicit model/user token limits take precedence.
"""

from __future__ import annotations

# Fractions of the effective reply allowance, never a global token count.
SHARES = {"auto": (1, 8), "low": (1, 8), "medium": (1, 4),
          "high": (1, 2), "max": (3, 4)}


def bound(active, payload: dict, reasoning: str = "auto") -> dict:
    profile = getattr(active, "inference_profile", {})
    capability = profile.get("capabilities", {}).get("reasoning", {}).get("budget")
    explicit = payload.pop("reasoning_budget", None)
    if not capability:
        return payload
    native_default = profile.get("capabilities", {}).get("reasoning", {}).get("default")
    # Default-Off templates need no limiter or invented output allowance.
    if reasoning == "auto" and native_default == "off":
        return payload
    total = payload.get("max_tokens")
    if total is None:
        # An unbounded native server default is not a recommendation to reserve
        # a quarter of a large context window for every ordinary Auto reply.
        if reasoning == "auto" and explicit is None and profile.get("reasoning_budget") is None:
            return payload
        total = max(1, active.context_limit // 4)
        payload["max_tokens"] = total
    closing = capability.get("closing_tokens", 1)
    field = capability.get("native_field", "thinking_budget_tokens")
    if capability.get("mechanism") == "mlx_vlm":
        payload["thinking_start_token"] = capability["start_sequence"]
        payload["thinking_end_token"] = capability["end_sequence"]
    if reasoning == "off" or (reasoning == "auto" and native_default == "off"):
        payload[field] = 0
        return payload
    if total <= closing:
        raise ValueError("Reply budget must leave room for thinking, its boundary and an answer.")
    selected = explicit if explicit is not None else profile.get("reasoning_budget")
    if selected is not None:
        if selected + closing >= total:
            raise ValueError("Thinking limit must leave room for the boundary and an answer.")
        budget = selected
    else:
        numerator, denominator = SHARES.get(reasoning, SHARES["auto"])
        # Even Maximum leaves at least a quarter for the answer, plus the
        # tokenizer's closing delimiter. A supplied token limit remains explicit.
        budget = min(max(1, total * numerator // denominator),
                     max(1, total - closing - max(1, total // 4)))
    if budget + closing >= total:
        raise ValueError("Thinking limit must leave room for the boundary and an answer.")
    payload[field] = budget
    return payload
