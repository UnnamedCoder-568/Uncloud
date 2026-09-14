"""Pairing secrets: one to scan, one to type.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Two shapes for the same job, because the phone in the room may or may not have
a working camera and the laptop across the desk has none at all.

The scanned one is 32 bytes of CSPRNG in a URL. The typed one is twelve
Crockford base32 characters — sixty bits, which is far beyond guessing inside a
five minute window, and typable by somebody reading it off a screen. Crockford
rather than the RFC alphabet because it was designed for exactly this: no I, no
L, no O, no U, so there is no one-versus-ell to get wrong and no accidental
obscenity to explain. Digits alone were considered and rejected — a twelve
digit numeric code is forty bits, and it looks like a PIN, which invites people
to treat it like one.
"""

from __future__ import annotations

import base64
import secrets

#: Crockford's alphabet. I, L, O and U are absent by design.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

#: Twelve symbols of five bits. Sixty bits, grouped four-four-four.
LENGTH = 12
GROUP = 4

#: What a mistyped character probably meant.
_CONFUSABLE = {"I": "1", "L": "1", "O": "0"}


def token() -> str:
    """A 32-byte secret for the QR, as URL-safe base64 with no padding."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


def code() -> str:
    """A typable twelve-character code, grouped for reading aloud."""
    raw = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
    return "-".join(raw[i:i + GROUP] for i in range(0, LENGTH, GROUP))


def normalise(entered: str) -> str:
    """What somebody typed, reduced to what it was meant to be.

    Case is irrelevant, the hyphens are a reading aid, spaces happen, and the
    three confusable letters fold onto their digits. Returns "" for anything
    that is not a well-formed code, so the caller never has to decide whether a
    malformed entry is a failed attempt — it is.
    """
    out = []
    for character in entered.upper():
        if character in ("-", " ", "\t"):
            continue
        character = _CONFUSABLE.get(character, character)
        if character not in ALPHABET:
            return ""
        out.append(character)
    return "".join(out) if len(out) == LENGTH else ""


def compact(formatted: str) -> str:
    """A generated code without its hyphens, for comparison."""
    return formatted.replace("-", "")
