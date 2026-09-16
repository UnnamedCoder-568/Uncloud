"""Conversations, kept between sessions and encrypted on disk.

A chat that vanishes when the window closes is a chat nobody relies on. This
keeps them, one file per conversation, each encrypted with AES-256-GCM under
the key from `vault`.

GCM rather than plain AES because it authenticates as well as encrypts: a file
altered on disk fails to open rather than decrypting into plausible nonsense
that gets shown as though the user had written it. The nonce is fresh on every
write, which is the one rule GCM cannot forgive breaking.

A file per conversation, rather than one database, for a reason worth stating:
a corrupt or unreadable file costs exactly that conversation. A single
container would put every conversation behind one successful decryption.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import CONFIG_DIR
from .vault import KeyUnavailable, vault

DIR = CONFIG_DIR / "conversations"

#: Marks the format, so a later change is detected rather than decrypted into
#: nonsense. Version lives in the file, not in a filename anybody could rename.
MAGIC = b"UNCLOUD-CONV-1\n"
NONCE_BYTES = 12

#: Long enough to recognise the conversation, short enough for a rail.
TITLE_CHARS = 60


@dataclass
class Conversation:
    id: str
    title: str
    created: float
    updated: float
    messages: list[dict] = field(default_factory=list)
    #: Which model was in play. Reopening a conversation against a different
    #: model is allowed, but it should be a visible choice rather than a
    #: surprise.
    model_path: str | None = None
    #: Desktop and every paired device have separate shelves. A phone must not
    #: discover or overwrite a conversation merely because it guessed an id.
    owner: str = "desktop"

    def summary(self) -> dict:
        return {"id": self.id, "title": self.title, "created": self.created,
                "updated": self.updated, "messages": len(self.messages),
                "model_path": self.model_path}

    def to_dict(self) -> dict:
        return {**self.summary(), "messages": self.messages}

    def storage_dict(self) -> dict:
        return {**self.to_dict(), "owner": self.owner}


def new_id() -> str:
    return secrets.token_hex(8)


def title_from(messages: list[dict]) -> str:
    """A name taken from the first thing the user asked.

    Better than "Conversation 4", and better than asking a model to summarise
    it: that costs a generation, and the first line is what the person will
    recognise anyway.
    """
    for message in messages:
        if message.get("role") != "user":
            continue
        text = " ".join(str(message.get("content", "")).split())
        if not text:
            continue
        return text[:TITLE_CHARS] + ("…" if len(text) > TITLE_CHARS else "")
    return "New conversation"


# ------------------------------------------------------------------ on disk
def _path(conversation_id: str) -> Path:
    # The id is generated here and is hex, but this is the one place a caller's
    # string becomes a filename, so it is checked rather than trusted.
    if not conversation_id or not all(c in "0123456789abcdef" for c in conversation_id):
        raise ValueError("not a conversation id")
    return DIR / f"{conversation_id}.enc"


class EncryptionUnavailable(RuntimeError):
    """The crypto library is not installed in this environment.

    Possible after an update on a machine that was offline when the new
    dependency would have been fetched. The engine still starts and everything
    else still works — conversations are the one thing that cannot, and saying
    so plainly is better than a stack trace or, worse, quietly writing them in
    the clear.
    """


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise EncryptionUnavailable(
            "Conversations are encrypted, and the library that does it is not "
            "installed. Reconnect to the internet and reopen Uncloud — it "
            "finishes setting itself up on launch."
        ) from exc
    return AESGCM


def _encrypt(payload: dict) -> bytes:
    AESGCM = _aesgcm()

    nonce = secrets.token_bytes(NONCE_BYTES)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    # The magic is authenticated but not encrypted, so a file of a future
    # version fails to open loudly instead of quietly.
    sealed = AESGCM(vault.key()).encrypt(nonce, body, MAGIC)
    return MAGIC + nonce + sealed


def _decrypt(raw: bytes) -> dict:
    AESGCM = _aesgcm()

    if not raw.startswith(MAGIC):
        raise ValueError("not an Uncloud conversation file")
    nonce = raw[len(MAGIC):len(MAGIC) + NONCE_BYTES]
    body = AESGCM(vault.key()).decrypt(nonce, raw[len(MAGIC) + NONCE_BYTES:], MAGIC)
    return json.loads(body.decode("utf-8"))


def _write(path: Path, data: bytes) -> None:
    """Write via a temporary file and rename.

    A conversation is saved after every reply. Writing in place means a crash
    mid-write leaves a truncated file, which under GCM does not decrypt at all
    — the whole conversation, lost to a badly timed quit. Rename is atomic, so
    the previous version survives until the new one is complete.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                 stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


# --------------------------------------------------------------------- API
def save(conversation: Conversation) -> Conversation:
    conversation.updated = time.time()
    if not conversation.title or conversation.title == "New conversation":
        conversation.title = title_from(conversation.messages)
    _write(_path(conversation.id), _encrypt(conversation.storage_dict()))
    return conversation


def load(conversation_id: str, *, owner: str = "desktop") -> Conversation | None:
    path = _path(conversation_id)
    if not path.is_file():
        return None
    data = _decrypt(path.read_bytes())
    stored_owner = str(data.get("owner") or "desktop")
    if stored_owner != owner:
        return None
    return Conversation(
        id=data["id"], title=data.get("title", ""),
        created=data.get("created", 0.0), updated=data.get("updated", 0.0),
        messages=data.get("messages", []), model_path=data.get("model_path"),
        owner=stored_owner,
    )


@dataclass
class Listing:
    conversations: list[dict]
    #: Files that are present and could not be read. Reported rather than
    #: hidden: a conversation the user remembers, silently missing from the
    #: list, is worse than one shown as damaged.
    unreadable: int
    secure: bool
    backend: str


def listing(*, owner: str = "desktop") -> Listing:
    if not DIR.is_dir():
        return Listing([], 0, vault.is_secure, vault.backend)
    found: list[dict] = []
    unreadable = 0
    for path in DIR.glob("*.enc"):
        try:
            data = _decrypt(path.read_bytes())
        except Exception:  # noqa: BLE001 - one bad file must not hide the rest
            unreadable += 1
            continue
        if str(data.get("owner") or "desktop") != owner:
            continue
        found.append({
            "id": data.get("id", path.stem),
            "title": data.get("title", ""),
            "created": data.get("created", 0.0),
            "updated": data.get("updated", 0.0),
            "messages": len(data.get("messages", [])),
            "model_path": data.get("model_path"),
        })
    found.sort(key=lambda c: c.get("updated", 0.0), reverse=True)
    return Listing(found, unreadable, vault.is_secure, vault.backend)


def delete(conversation_id: str, *, owner: str = "desktop") -> bool:
    path = _path(conversation_id)
    if not path.is_file():
        return False
    if load(conversation_id, owner=owner) is None:
        return False
    path.unlink()
    return True


def exists(conversation_id: str) -> bool:
    """Whether an id is already occupied, without revealing who owns it."""
    return _path(conversation_id).is_file()


def create(messages: list[dict] | None = None,
           model_path: str | None = None, *, owner: str = "desktop") -> Conversation:
    now = time.time()
    messages = messages or []
    return Conversation(id=new_id(), title=title_from(messages),
                        created=now, updated=now, messages=messages,
                        model_path=model_path, owner=owner)


__all__ = ["Conversation", "EncryptionUnavailable", "KeyUnavailable", "create",
           "delete", "exists", "listing", "load", "save", "title_from"]
