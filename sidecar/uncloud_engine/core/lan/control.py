"""Talking to a running server from the same machine, without a credential.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

`pair` has to mint a new code inside the process that will accept it, and
`revoke` has to reach the in-memory session table or the next write would put
the revoked device straight back. Both need a way into a running server.

The obvious way — a local admin token in a file — writes a credential to disk,
which is the one thing this feature promised never to do. A Unix socket needs
no credential at all: it lives in a 0700 directory, the socket itself is 0600,
and the kernel will not let another user connect. Filesystem permission IS the
authentication, and there is nothing to steal.

Windows has no dependable Unix socket in Python, so there the socket is simply
absent: `revoke` edits the store directly when nothing is running, and a new
code comes from the app's own Devices screen, which is authenticated the
ordinary way.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import stat
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

Handler = Callable[[dict[str, object]], dict[str, object]]

#: Requests are one line of JSON and so are answers. Anything longer is not a
#: request this protocol has.
LIMIT = 64 * 1024


#: sun_path is 104 bytes on macOS and 108 on Linux, terminator included. A
#: long home directory is enough to exceed it, and bind() then fails outright.
MAX_PATH = 100


def available() -> bool:
    return hasattr(socket, "AF_UNIX")


def socket_path(store: Path, slug: str) -> Path:
    """Where the control socket lives. The same answer for server and CLI.

    Beside the sessions file when the path fits. When it does not, a directory
    under the system temp location — which on a shared /tmp another user could
    have created first, so it is used only if it is ours and closed to others.
    """
    preferred = store / "control.sock"
    if len(os.fsencode(preferred)) <= MAX_PATH:
        return preferred

    directory = Path(tempfile.gettempdir()) / f"{slug}-lan-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise PermissionError(f"{directory} is not a private directory owned by this user")
    return directory / "control.sock"


def listen(path: Path, handler: Handler) -> Callable[[], None]:
    """Serve `handler` on a Unix socket at `path`. Returns a function to stop."""
    if not available():
        return lambda: None

    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()                              # a stale socket from a crash

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    # umask rather than chmod-after-bind, for the same reason files here are
    # created 0600: the gap between bind and chmod is a window.
    previous = os.umask(0o177)
    try:
        server.bind(str(path))
    finally:
        os.umask(previous)
    server.listen(4)
    stopping = threading.Event()

    def serve() -> None:
        while not stopping.is_set():
            try:
                connection, _ = server.accept()
            except OSError:
                return
            with connection:
                try:
                    raw = connection.makefile("rb").readline(LIMIT)
                    reply = handler(json.loads(raw or b"{}"))
                except Exception as error:  # noqa: BLE001 — the reply IS the report
                    reply = {"ok": False, "error": type(error).__name__}
                with contextlib.suppress(OSError):
                    connection.sendall(json.dumps(reply).encode() + b"\n")

    threading.Thread(target=serve, daemon=True, name="lan-control").start()

    def stop() -> None:
        stopping.set()
        server.close()
        with contextlib.suppress(FileNotFoundError):
            path.unlink()

    return stop


def ask(path: Path, request: dict[str, object], *,
        timeout: float = 5.0) -> dict[str, object] | None:
    """Send one request to a running server. None if nothing is listening."""
    if not available() or not path.exists():
        return None
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(str(path))
        client.sendall(json.dumps(request).encode() + b"\n")
        raw = client.makefile("rb").readline(LIMIT)
    except OSError:
        return None
    finally:
        client.close()
    try:
        answer = json.loads(raw)
    except ValueError:
        return None
    return answer if isinstance(answer, dict) else None
