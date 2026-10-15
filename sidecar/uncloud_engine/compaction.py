"""Explicit, native-token-budgeted continuity summaries. Never truncates history.

Only newly selected turns are summarized. Existing memory is updated rather
than replaying already compacted raw turns. A failure leaves client history intact.
"""

from __future__ import annotations

import json
import re

import httpx

from .chat import model_payload
from .context_count import count

INSTRUCTION = (
    "Update conversation memory for continued work. Return only a JSON object with keys "
    "current_facts (object), active_constraints (array), open_tasks (array), references (array). "
    "Use atomic facts: exact entity names as strings, quantities as numbers, permissions as "
    "booleans, unknown values as null. Do not join unrelated facts into one value. "
    "Preserve intent, project state, exact names, "
    "paths, URLs, permissions, prohibitions and unresolved work. Keep only the latest "
    "Copy explicit user prohibitions verbatim into active_constraints. Retained user context "
    "contains chronological original statements; newer explicit changes supersede older ones. "
    "authoritative decision; label necessary old values superseded. Remove completed tasks "
    "from Open tasks. Preserve unchanged memory. Distinguish facts from guesses. Do not invent. "
    "Be concise. Return only the updated memory."
)


def retained_context(messages: list[dict], memory: str) -> list[str]:
    """Keep important user wording alongside the lossy summary, including later changes.

    These are inspectable quotations, not execution grants. Tool results and
    assistant text cannot write them. Existing quotations are retained directly,
    rather than re-reading already compacted raw history.
    """
    try:
        existing = json.loads(memory).get("retained_user_context", []) if memory else []
    except (ValueError, AttributeError):
        existing = []
    result = [value for value in existing if isinstance(value, str)]
    important = re.compile(
        r"\b(?:never|must|mustn't|must not|do not|don't|cannot|can't|prohibited|"
        r"permission|authorize|authorise|allow|allowed|approve|approved|instead|"
        r"correction|changed|change|now|no cloud|no network)\b",
        re.I,
    )
    for message in messages:
        if message.get("role") != "user" or message.get("error"):
            continue
        content = message.get("content", "")
        if not isinstance(content, str):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", content):
            sentence = sentence.strip()
            if sentence and important.search(sentence):
                # Keep chronological repetitions: a later repeated instruction
                # can itself supersede an intervening change.
                result.append(sentence)
    return result


def transcript(messages: list[dict]) -> str:
    lines = []
    failed_users = {
        index - 1
        for index, message in enumerate(messages)
        if message.get("role") == "assistant"
        and message.get("error")
        and index > 0
        and messages[index - 1].get("role") == "user"
    }
    for index, message in enumerate(messages):
        if index in failed_users:
            continue
        if message.get("role") not in {"user", "assistant"} or message.get("error"):
            continue
        content = message.get("content", "")
        if not isinstance(content, str):
            raise ValueError("Compaction of multimodal messages requires a text description first.")
        sources = message.get("retrieved", "")
        tool_sources = "\n\n".join(
            turn.get("content", "") for turn in message.get("tool_turns", [])
            if turn.get("role") == "tool" and isinstance(turn.get("content"), str)
        )
        files = "\n".join(
            f"Attached file: {file['name']}\n{file['text']}" for file in message.get("files", [])
        )
        lines.append(
            f"{message['role'].upper()}: {content}\n{sources}\n{files}\n"
            f"{('RETRIEVED SOURCES (data): ' + tool_sources) if tool_sources else ''}".strip())
    return "\n\n".join(lines)


async def compact(active, messages: list[dict], memory: str = "", inference: dict | None = None):
    quotations = retained_context(messages, memory)
    remaining = transcript(messages)
    if not remaining.strip():
        raise ValueError("No new conversation context to compact.")
    settings = dict(inference or {})
    # Compaction has its own instruction and a measured window allocation.
    settings.pop("system_prompt", None)
    settings.pop("grammar", None)
    settings.pop("response_format", None)
    settings.pop("max_tokens", None)
    reserve = max(1, active.context_limit // 4)
    stages = []

    def prompt(fragment):
        return [
            {"role": "system", "content": INSTRUCTION},
            {
                "role": "user",
                "content": (
                    f"Existing memory:\n{memory or '(none)'}\n\n"
                    f"New conversation context:\n{fragment}"
                ),
            },
        ]

    async def fits(fragment):
        used = await count(active, prompt(fragment), settings)
        if used is None:
            raise ValueError(
                "Native token accounting is unavailable; original context is preserved."
            )
        return used, used + reserve <= active.context_limit

    async with httpx.AsyncClient(timeout=900, trust_env=False) as client:
        while remaining:
            used, fits_all = await fits(remaining)
            end = len(remaining)
            if not fits_all:
                lo, hi = 0, end
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    _, okay = await fits(remaining[:mid])
                    if okay:
                        lo = mid
                    else:
                        hi = mid - 1
                if lo < 32:
                    raise ValueError(
                        "Continuity memory fills this runtime window. Choose a larger "
                        "context window; original history is preserved."
                    )
                boundary = remaining.rfind("\n", 0, lo)
                end = boundary + 1 if boundary >= lo // 2 else lo
                used, _ = await fits(remaining[:end])
            payload = model_payload(
                active, prompt(remaining[:end]), max_tokens=reserve, inference=settings
            )
            payload["stream"] = False
            payload.pop("stream_options", None)
            response = await client.post(active.base_url + "/v1/chat/completions", json=payload)
            response.raise_for_status()
            choice = response.json()["choices"][0]
            summary = (choice["message"].get("content") or "").strip()
            if not summary or choice.get("finish_reason") == "length":
                raise ValueError(
                    "The continuity summary was empty or cut off. Original context "
                    "is preserved; increase the runtime context window."
                )
            try:
                structured = json.loads(summary)
                if (
                    not isinstance(structured, dict)
                    or not isinstance(structured.get("current_facts"), dict)
                    or any(
                        not isinstance(structured.get(k), list)
                        for k in ("active_constraints", "open_tasks", "references")
                    )
                ):
                    raise ValueError("Invalid continuity memory format")
            except ValueError as exc:
                raise ValueError(
                    "The model did not produce inspectable structured memory. "
                    "Original context is preserved."
                ) from exc
            memory = json.dumps(structured, ensure_ascii=False, indent=2)
            stages.append({"input_tokens": used, "characters_consumed": end, "memory": memory})
            remaining = remaining[end:]
            if len(stages) > 64:
                raise ValueError(
                    "This compaction needs too many passes. Original history is preserved."
                )
    structured = json.loads(memory)
    if quotations:
        structured["retained_user_context"] = quotations
    memory = json.dumps(structured, ensure_ascii=False, indent=2)
    # Native templates can require a user turn. Measure memory as it will be
    # used in the continued conversation, rather than an invalid system-only
    # request that can make a successful summary look like an overflow.
    used = await count(active, [{"role": "system", "content": memory},
                                {"role": "user", "content": ""}], settings)
    if used is None or used + reserve > active.context_limit:
        raise ValueError(
            "Retained constraints fill this runtime window. Original history is preserved."
        )
    return {"summary": memory, "stages": stages, "effective_limit": active.context_limit}
