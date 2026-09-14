"""Paired devices, and what makes them stay paired.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

A pairing code is a one-time thing that expires in five minutes. A session is
the opposite: it survives restarts, because a phone that has to be re-paired
every time the desktop app reopens is a phone nobody uses. Those two lifetimes
are the whole design, and keeping them separate is why the code can rotate on
every launch without logging anybody out.

**Nothing here is stored in the clear.** The file on disk holds a SHA-256 of
each session secret, never the secret. Read the file and you learn which
devices are paired and when they last called; you do not learn how to be one of
them. A plain SHA-256 is the right primitive rather than a password hash: the
input is 32 bytes of CSPRNG, so there is no dictionary to run and no work
factor worth paying on every request.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

#: How long a browser is told to keep the cookie. Long, deliberately: expiring
#: it is what re-pairing is for, and a silent logout is indistinguishable from
#: a bug.
LIFETIME = 365 * 24 * 60 * 60

#: `last_seen` is written at most this often. Every request would otherwise
#: rewrite the file, which on a phone polling for job events is a write per
#: second for no information anybody wants at that resolution.
SEEN_RESOLUTION = 60.0


@dataclass(frozen=True)
class Session:
    """One paired device, as the interface should describe it."""

    id: str
    label: str
    created: float
    last_seen: float
    agent: str

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "created": self.created,
            "last_seen": self.last_seen,
            "agent": self.agent,
        }


def describe(user_agent: str | None) -> str:
    """A coarse device name from a User-Agent, and nothing finer.

    Enough to tell two paired devices apart in a list; not a fingerprint. The
    full string is never stored — it is the most identifying thing a browser
    sends, and a list of paired devices does not need it.
    """
    ua = (user_agent or "").lower()
    for needle, name in (("ipad", "iPad"), ("iphone", "iPhone"), ("android", "Android"),
                         ("macintosh", "Mac"), ("windows", "Windows"), ("linux", "Linux")):
        if needle in ua:
            return name
    return "Unknown device"


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class Sessions:
    """The paired-device store. Safe to share across threads."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._by_id: dict[str, Session] = {}
        self._hash: dict[str, str] = {}          # session id -> secret digest
        self._load()

    # ------------------------------------------------------------ persistence

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        for entry in raw.get("sessions", []):
            try:
                session = Session(
                    id=str(entry["id"]),
                    label=str(entry.get("label") or "Paired device"),
                    created=float(entry.get("created") or 0.0),
                    last_seen=float(entry.get("last_seen") or 0.0),
                    agent=str(entry.get("agent") or "Unknown device"),
                )
            except (KeyError, TypeError, ValueError):
                continue                          # one bad row is not a reason to lose the rest
            self._by_id[session.id] = session
            self._hash[session.id] = str(entry.get("digest") or "")

    def _save(self) -> None:
        payload = {
            "version": 1,
            "sessions": [
                {**session.public(), "digest": self._hash.get(session.id, "")}
                for session in self._by_id.values()
            ],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        # Opened 0600 rather than chmod-ed afterwards: between creat and chmod
        # there is a window where the file is world-readable, and this file is
        # the list of everything that may talk to the engine.
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump(payload, handle)
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary, self.path)

    # ----------------------------------------------------------------- issuing

    def issue(self, *, label: str, agent: str) -> tuple[str, Session]:
        """A new session. Returns (cookie value, session).

        The cookie value is the only time the secret exists outside the
        browser; it is not stored, not logged, and not recoverable.
        """
        secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
        now = time.time()
        session = Session(id=secrets.token_hex(8), label=label,
                          created=now, last_seen=now, agent=agent)
        with self._lock:
            self._by_id[session.id] = session
            self._hash[session.id] = _digest(secret)
            self._save()
        return f"{session.id}.{secret}", session

    # ---------------------------------------------------------------- checking

    def verify(self, cookie: str | None) -> Session | None:
        """The session this cookie names, or None. Constant-time on the secret."""
        if not cookie or "." not in cookie:
            return None
        session_id, _, secret = cookie.partition(".")
        with self._lock:
            expected = self._hash.get(session_id)
            session = self._by_id.get(session_id)
            if not expected or session is None:
                # Still compare, so a wrong id and a wrong secret take the same
                # time. The comparison is against a value of the right shape.
                secrets.compare_digest(_digest(secret), "0" * 64)
                return None
            if not secrets.compare_digest(_digest(secret), expected):
                return None
            if time.time() - session.created > LIFETIME:
                del self._by_id[session_id]
                del self._hash[session_id]
                self._save()
                return None

            now = time.time()
            if now - session.last_seen > SEEN_RESOLUTION:
                session = replace(session, last_seen=now)
                self._by_id[session_id] = session
                self._save()
            return session

    # ---------------------------------------------------------------- revoking

    def revoke(self, session_id: str) -> bool:
        with self._lock:
            if session_id not in self._by_id:
                return False
            del self._by_id[session_id]
            self._hash.pop(session_id, None)
            self._save()
            return True

    def revoke_all(self) -> int:
        with self._lock:
            count = len(self._by_id)
            self._by_id.clear()
            self._hash.clear()
            self._save()
            return count

    def rename(self, session_id: str, label: str) -> bool:
        with self._lock:
            session = self._by_id.get(session_id)
            if session is None:
                return False
            self._by_id[session_id] = replace(session, label=label)
            self._save()
            return True

    def all(self) -> list[Session]:
        with self._lock:
            return sorted(self._by_id.values(), key=lambda s: s.created)
