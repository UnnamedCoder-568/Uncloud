"""The key conversations are encrypted with.

Where the key lives is the whole security story, and it is worth being precise
about what this does and does not buy.

WHAT IT PROTECTS AGAINST. The conversation files leaving this machine while
the key does not: a Time Machine backup, a copied folder, an old drive sold on,
a synced directory, a support bundle. That is the realistic way private chat
ends up somewhere it should not be, and against it this is effective.

WHAT IT DOES NOT PROTECT AGAINST. Anything running as this user. A process
that can read the files can ask the keychain for the key, exactly as the
application does. Encryption at rest is not a sandbox and is not claimed to be.

The key is 32 random bytes, made once and kept in the OS keychain. When there
is no keychain — a headless Linux box with no secret service — the fallback is
a 0600 file, and `is_secure` says so rather than pretending. Quietly degrading
to a key sitting in plaintext beside the data it protects, while the interface
says "encrypted", would be worse than not encrypting at all.
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

from .config import CONFIG_DIR

SERVICE = "Uncloud"
ACCOUNT = "conversation-key"
KEY_BYTES = 32

_FALLBACK = CONFIG_DIR / "conversation.key"


class KeyUnavailable(RuntimeError):
    """No key could be read or made. Conversations stay in memory only."""


def _from_keychain() -> bytes | None:
    try:
        import keyring
    except ImportError:
        return None
    try:
        stored = keyring.get_password(SERVICE, ACCOUNT)
    except Exception:  # noqa: BLE001 - a locked keychain must not crash launch
        return None
    if not stored:
        return None
    try:
        return bytes.fromhex(stored)
    except ValueError:
        return None


def _to_keychain(key: bytes) -> bool:
    try:
        import keyring

        keyring.set_password(SERVICE, ACCOUNT, key.hex())
        # Read back rather than trusting the write. A keyring that accepts a
        # password and stores nothing is a real configuration, and finding out
        # at the next launch means unreadable conversations.
        return _from_keychain() == key
    except Exception:  # noqa: BLE001
        return False


def _from_file() -> bytes | None:
    if not _FALLBACK.is_file():
        return None
    try:
        raw = bytes.fromhex(_FALLBACK.read_text().strip())
    except (OSError, ValueError):
        return None
    return raw if len(raw) == KEY_BYTES else None


def _to_file(key: bytes) -> None:
    _FALLBACK.parent.mkdir(parents=True, exist_ok=True)
    # Written 0600 from the start rather than chmod-ed afterwards, so it is
    # never briefly readable by anyone else on the machine.
    fd = os.open(_FALLBACK, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                 stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as handle:
        handle.write(key.hex())


class Vault:
    """The key, and an honest account of where it ended up."""

    def __init__(self) -> None:
        self._key: bytes | None = None
        self._secure = False

    @property
    def is_secure(self) -> bool:
        """Whether the key is in the OS keychain rather than in a file."""
        self.key()
        return self._secure

    @property
    def backend(self) -> str:
        self.key()
        return "keychain" if self._secure else "file"

    def key(self) -> bytes:
        if self._key is not None:
            return self._key

        existing = _from_keychain()
        if existing and len(existing) == KEY_BYTES:
            self._key, self._secure = existing, True
            return self._key

        # A file key is used if one is already there, even when a keychain is
        # now available: migrating would strand every conversation written
        # under the old key.
        existing = _from_file()
        if existing:
            self._key, self._secure = existing, False
            return self._key

        made = secrets.token_bytes(KEY_BYTES)
        if _to_keychain(made):
            self._key, self._secure = made, True
            return self._key
        try:
            _to_file(made)
        except OSError as exc:
            raise KeyUnavailable(
                "Could not store a key for encrypting conversations."
            ) from exc
        self._key, self._secure = made, False
        return self._key


vault = Vault()
