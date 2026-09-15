"""Cutting text into pieces a speech model can say in one breath.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Standard library only: the speech worker
imports this by path from inside an engine's own environment, which has none
of the product installed.

Most speech models have a ceiling on one generation — Bark stops near
thirteen seconds, Chatterbox near forty — and past it they do not fail, they
trail off, repeat, or hallucinate. A long script is therefore said a sentence
group at a time and joined. The cut falls between sentences, never inside a
word, because a join inside a sentence is audible and a join between them is
a pause people expect.
"""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"(?<=[.!?…。！？])[\"')\]]*\s+")
_SPEAKER = re.compile(r"^\s*Speaker\s+(\d+)\s*:", re.IGNORECASE)


def sentences(text: str) -> list[str]:
    """Split on sentence ends and on line breaks. Blank pieces are dropped."""
    out: list[str] = []
    for paragraph in text.splitlines():
        for piece in _SENTENCE_END.split(paragraph.strip()):
            if piece.strip():
                out.append(piece.strip())
    return out


def _split_long(sentence: str, limit: int) -> list[str]:
    """A single sentence longer than the limit, cut at the last comma or space
    that fits. A run with no space at all is cut hard: rare, and better than a
    model reading past its ceiling."""
    pieces: list[str] = []
    rest = sentence
    while len(rest) > limit:
        window = rest[:limit]
        cut = max(window.rfind(", "), window.rfind("; "), window.rfind(": "))
        cut = cut + 1 if cut > limit // 3 else window.rfind(" ")
        if cut <= 0:
            cut = limit
        pieces.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        pieces.append(rest)
    return pieces


def chunks(text: str, limit: int) -> list[str]:
    """Pack whole sentences into pieces of at most `limit` characters.

    A limit of 0 or less means the engine reads any length in one pass, and
    the text comes back as a single piece.
    """
    text = text.strip()
    if not text:
        return []
    if limit <= 0:
        return [text]
    out: list[str] = []
    current = ""
    for sentence in sentences(text):
        for piece in _split_long(sentence, limit):
            if current and len(current) + 1 + len(piece) > limit:
                out.append(current)
                current = piece
            else:
                current = f"{current} {piece}".strip()
    if current:
        out.append(current)
    return out


def speaker_script(text: str) -> str:
    """Label every line with a speaker, for models that read only labelled lines.

    VibeVoice's full model drops, without an error, any line that does not
    start "Speaker N:". Labelling only the first line narrated a title and
    nothing after it. A line without a label continues whoever spoke last.
    """
    speaker = "1"
    lines = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _SPEAKER.match(line)
        if match:
            speaker = match.group(1)
            lines.append(line.strip())
        else:
            lines.append(f"Speaker {speaker}: {line.strip()}")
    return "\n".join(lines)
