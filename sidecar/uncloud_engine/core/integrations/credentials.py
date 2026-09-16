"""Where integration secrets live, and why a model can never see one.

The brief was specific: do not store passwords in plaintext, do not ask models
to handle or remember credentials, and keep credentials out of model context
wherever possible. "Wherever possible" is doing no work here — it is possible
everywhere, and this module is how.

**The secret is never a return value anybody upstream receives.** `open()`
hands a caller a live client, built inside this module. `describe()` hands the
interface a label and a boolean. There is no function here that returns a token
to application code, so there is nothing for a prompt, a log line, a tool
result or an error message to leak. That is a stronger guarantee than redaction,
because redaction is a list of places to remember and this is the absence of
the value.

**Storage is the OS keychain, and it says so when it is not.** The same bargain
`vault.py` already makes for the conversation key: a keychain when there is
one, a 0600 file when there is not, and `secure` reporting which — because
quietly degrading to a secret in plaintext while the interface says "stored
securely" is worse than refusing to store it.

**A handle is not authority.** Holding a handle means a credential exists under
that name. Whether an action may run is the permission gate's question, asked
at the moment of the action, every time.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

SERVICE = "Uncloud Integrations"

#: Where the fallback index lives. Core does not know which application is
#: running it, so the product says — `configure()` at start-up. The default is
#: deliberately a Core-owned directory rather than either product's, so a
#: misconfigured build writes somewhere harmless and obvious instead of
#: silently into the wrong application's state.
_DIRECTORY = Path.home() / ".uncloud-core"


def configure(directory: Path | str) -> None:
    """Point the store at this application's own data directory."""
    global _DIRECTORY
    _DIRECTORY = Path(directory)


def _fallback_path() -> Path:
    return _DIRECTORY / "integrations.json"

#: Everything the interface is allowed to know about a stored credential.
#: Deliberately not the credential.
@dataclass(frozen=True)
class Held:
    handle: str
    #: An address, a username, a folder — something a person would recognise
    #: and would not mind appearing in a screenshot.
    label: str
    kind: str = "token"
    stored_at: str = ""
    #: False when this fell back to a file because no keychain was available.
    secure: bool = True

    def to_dict(self) -> dict:
        return {"handle": self.handle, "label": self.label, "kind": self.kind,
                "stored_at": self.stored_at, "secure": self.secure}


class NotConnected(Exception):
    """No credential is stored under that handle."""


def _keyring():
    try:
        import keyring
    except ImportError:
        return None
    try:
        # A backend that raises on read is not a backend. Discovering that at
        # first use rather than at store time would mean a credential that
        # appears saved and is not.
        keyring.get_password(SERVICE, "__probe__")
    except Exception:  # noqa: BLE001 - any backend failure means no keychain
        return None
    return keyring


def _read_fallback() -> dict:
    path = _fallback_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_fallback(data: dict) -> None:
    path = _fallback_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def secure() -> bool:
    """Whether secrets are going into a real keychain.

    Surfaced in the interface. Somebody on a headless Linux box with no secret
    service should be told that, and get to decide, rather than find out later.
    """
    return _keyring() is not None


# The index of what exists. Labels and handles only — never a secret — so it
# can be read freely by anything that needs to render a list.
def _index() -> dict:
    raw = _read_fallback().get("index")
    return raw if isinstance(raw, dict) else {}


def _save_index(index: dict) -> None:
    data = _read_fallback()
    data["index"] = index
    _write_fallback(data)


def store(handle: str, secret: str, *, label: str, kind: str = "token") -> Held:
    """Keep a credential under a handle.

    The secret goes to the keychain and the index records only that something
    exists under this name. Nothing returns the secret; the caller gets back
    what it is allowed to display.
    """
    from datetime import UTC, datetime

    if not handle or not secret:
        raise ValueError("a credential needs both a handle and a secret")

    ring = _keyring()
    if ring is not None:
        ring.set_password(SERVICE, handle, secret)
        # Read back rather than trusting the write: a keychain that accepts a
        # write and returns nothing has stored nothing, and the failure would
        # otherwise surface as a mysterious disconnection later.
        if ring.get_password(SERVICE, handle) != secret:
            raise RuntimeError("the keychain accepted the credential but did "
                               "not return it; nothing was stored")
    else:
        data = _read_fallback()
        secrets_map = data.get("secrets")
        data["secrets"] = {**(secrets_map if isinstance(secrets_map, dict) else {}),
                           handle: secret}
        _write_fallback(data)

    held = Held(handle=handle, label=label, kind=kind,
                stored_at=datetime.now(UTC).isoformat(timespec="seconds"),
                secure=ring is not None)
    index = _index()
    index[handle] = {k: v for k, v in held.to_dict().items() if k != "handle"}
    _save_index(index)
    return held


def remember_path(handle: str, location: str) -> Held:
    """Record a connection that has no secret — a folder on this machine.

    Kept out of the keychain deliberately. A directory is not a credential, it
    has to be displayable, and putting it behind the keychain would mean an
    unlock prompt every time a list is rendered.
    """
    from datetime import UTC, datetime

    if not handle or not location:
        raise ValueError("a folder connection needs both a handle and a path")
    held_now = Held(handle=handle, label=location, kind="path",
                    stored_at=datetime.now(UTC).isoformat(timespec="seconds"),
                    secure=True)
    index = _index()
    index[handle] = {k: v for k, v in held_now.to_dict().items() if k != "handle"}
    _save_index(index)
    return held_now


def remember_value(handle: str, value: str, *, kind: str = "metadata") -> Held:
    """Record readable application metadata without treating it as a path.

    JSON and URLs passed through :class:`Path` are silently rewritten on
    Windows.  Keep non-secret configuration byte-for-byte instead.
    """
    from datetime import UTC, datetime

    if not handle or not value:
        raise ValueError("metadata needs both a handle and a value")
    held_now = Held(handle=handle, label=value, kind=kind,
                    stored_at=datetime.now(UTC).isoformat(timespec="seconds"),
                    secure=True)
    index = _index()
    index[handle] = {k: v for k, v in held_now.to_dict().items() if k != "handle"}
    _save_index(index)
    return held_now


def forget(handle: str) -> bool:
    """Remove a credential. Returns whether there was one."""
    ring = _keyring()
    existed = handle in _index()
    if ring is not None:
        # Absent is the desired end state, so a backend that has never heard of
        # this handle is a success rather than something to report.
        with contextlib.suppress(Exception):
            ring.delete_password(SERVICE, handle)
    data = _read_fallback()
    secrets_map = data.get("secrets")
    if isinstance(secrets_map, dict) and handle in secrets_map:
        del secrets_map[handle]
        data["secrets"] = secrets_map
        _write_fallback(data)
    index = _index()
    index.pop(handle, None)
    _save_index(index)
    return existed


def held(handle: str) -> Held | None:
    """What is stored under a handle, minus the secret."""
    row = _index().get(handle)
    if not isinstance(row, dict):
        return None
    return Held(handle=handle, label=str(row.get("label", "")),
                kind=str(row.get("kind", "token")),
                stored_at=str(row.get("stored_at", "")),
                secure=bool(row.get("secure", True)))


def describe() -> list[dict]:
    """Every stored credential, as the interface may see it."""
    return sorted((h.to_dict() for handle in _index()
                   if (h := held(handle)) is not None),
                  key=lambda row: row["handle"])


def connected(handle: str) -> bool:
    return handle in _index()


def open(handle: str, build: Callable[[str], object]) -> object:  # noqa: A001
    """Build a client from a stored credential, without handing it over.

    The one function that touches a secret on behalf of a caller, and it never
    gives it to them: `build` receives the secret, returns whatever client it
    needs, and the secret goes out of scope with the call. An adapter written
    against this cannot leak a token even carelessly, because it never holds
    one.
    """
    ring = _keyring()
    secret = None
    if ring is not None:
        secret = ring.get_password(SERVICE, handle)
    if secret is None:
        secrets_map = _read_fallback().get("secrets")
        if isinstance(secrets_map, dict):
            secret = secrets_map.get(handle)
    if secret is None:
        raise NotConnected(f"nothing is connected as {handle!r}")
    return build(secret)


def path_of(handle: str) -> Path | None:
    """The folder a filesystem integration was connected to.

    Paths are stored in the index rather than the keychain: a directory is not
    a secret, it has to be displayable, and putting it behind the keychain
    would mean an unlock prompt to render a list.
    """
    row = _index().get(handle)
    if not isinstance(row, dict):
        return None
    location = row.get("label", "")
    return Path(location) if location else None


def value_of(handle: str) -> str | None:
    """Return readable non-secret metadata exactly as it was stored."""
    item = held(handle)
    return item.label if item and item.label else None
