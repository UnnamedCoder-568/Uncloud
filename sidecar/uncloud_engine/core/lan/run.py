"""Serving: loopback for the desktop shell, and — only when asked — the LAN.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Two listeners in one process, sharing one application. The loopback one is
exactly what the desktop shell has always talked to: plain HTTP on 127.0.0.1,
bearer token, unchanged. The LAN one exists only with `--lan`, speaks only
HTTPS, binds only the addresses it printed a QR for, and sits behind the Host
fence. Nothing about starting the desktop app puts anything on the network.

Binding the listed addresses rather than 0.0.0.0 is deliberate. A wildcard bind
also answers on the Docker bridge, the VPN, and whatever interface appears
after startup — addresses nobody was shown and nobody chose.

This module also holds the command-line verbs, `pair`, `revoke` and `devices`,
so both products spell them identically.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import control
from .service import Lan
from .sessions import Sessions
from .web import Fence

#: Stable by default so a bookmark on a phone keeps working. Each product picks
#: its own, and falls back to a free port when its choice is taken.
DEFAULT_PORTS = {"uncloud": 8765, "studio": 8766}


def lan_requested(argv: list[str]) -> bool:
    return "--lan" in argv


def option(argv: list[str], name: str) -> str | None:
    prefix = f"--{name}="
    return next((a[len(prefix):] for a in argv if a.startswith(prefix)), None)


def _bind(address: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((address, port))
    sock.set_inheritable(True)
    return sock


def lan_port(slug: str, requested: str | None, addresses: list[str]) -> int:
    """The requested port, else this product's default, else any free one."""
    for candidate in ([int(requested)] if requested else []) + [DEFAULT_PORTS.get(slug, 0)]:
        if not candidate:
            continue
        try:
            for address in addresses or ["0.0.0.0"]:
                _bind(address, candidate).close()
            return candidate
        except OSError:
            continue
    with socket.socket() as probe:
        probe.bind((addresses[0] if addresses else "0.0.0.0", 0))
        return int(probe.getsockname()[1])


class _Quiet:
    """A uvicorn server that leaves signals to the one beside it."""

    def __init__(self, server: Any) -> None:
        self.server = server

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        yield


def serve(app: Any, *, port: int, lan: Lan | None, log_level: str = "warning") -> None:
    """Run loopback, and the LAN listener if there is one, until interrupted."""
    import uvicorn

    local = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                          log_level=log_level))
    if lan is None:
        local.run()
        return

    addresses = [i.address for i in lan.interfaces]
    sockets = [_bind(address, lan.port) for address in addresses]
    remote = uvicorn.Server(uvicorn.Config(
        Fence(app, lan),
        log_level=log_level,
        # The pairing token is in a query string. An access log would write a
        # working credential to disk; see web.py.
        access_log=False,
        ssl_certfile=str(lan.material.certificate),
        ssl_keyfile=str(lan.material.key),
    ))
    remote.capture_signals = _Quiet(remote).capture_signals  # type: ignore[method-assign]

    try:
        stop_control = control.listen(_control_path(lan), _handler(lan))
    except OSError as error:
        # The control channel is a convenience for `pair` and `revoke`. Losing
        # it must not take the LAN listener down with it.
        print(f"Pairing from another terminal is unavailable ({error}). Codes are "
              "still available from the app.", file=sys.stderr)
        stop_control = lambda: None  # noqa: E731

    async def both() -> None:
        lan_task = asyncio.create_task(remote.serve(sockets=sockets))
        try:
            await local.serve()
        finally:
            remote.should_exit = True
            await lan_task

    try:
        asyncio.run(both())
    finally:
        stop_control()
        for sock in sockets:
            with contextlib.suppress(OSError):
                sock.close()


def _control_path(lan: Lan) -> Path:
    return control.socket_path(lan.sessions.path.parent, lan.slug)


def _handler(lan: Lan) -> control.Handler:
    def handle(request: dict[str, object]) -> dict[str, object]:
        verb = request.get("verb")
        if verb == "pair":
            offer = lan.offer()
            return {"ok": True, "banner": lan.banner(offer, colour=bool(request.get("colour")))}
        if verb == "revoke":
            target = str(request.get("device") or "")
            if target == "--all":
                return {"ok": True, "revoked": lan.sessions.revoke_all()}
            revoked = lan.sessions.revoke(target)
            return {"ok": revoked, "revoked": int(revoked)}
        if verb == "devices":
            return {"ok": True, "devices": [s.public() for s in lan.sessions.all()]}
        return {"ok": False, "error": "unknown verb"}
    return handle


# -------------------------------------------------------------------- the CLI

def command(argv: list[str], *, config_dir: Path, product: str, slug: str) -> int | None:
    """Handle `pair`, `revoke` or `devices`. None means "not a CLI verb; serve"."""
    if not argv or argv[0] not in ("pair", "revoke", "devices"):
        return None
    verb, rest = argv[0], argv[1:]
    store = config_dir / "lan"
    try:
        sock = control.socket_path(store, slug)
    except OSError:
        sock = store / "control.sock"          # ask() will find nothing there
    out = sys.stdout

    if verb == "pair":
        reply = control.ask(sock, {"verb": "pair", "colour": out.isatty()})
        if reply is None:
            print(f"{product} is not running with --lan on this machine. Start it with "
                  "--lan; the pairing code is printed on start.", file=sys.stderr)
            return 1
        print(reply.get("banner", ""))
        return 0

    if verb == "devices":
        reply = control.ask(sock, {"verb": "devices"})
        devices = (reply or {}).get("devices") if reply else [
            s.public() for s in Sessions(store / "sessions.json").all()]
        if not devices:
            print("No paired devices.")
            return 0
        for d in devices:  # type: ignore[union-attr]
            print(f"  {d['id']}  {d['label']:<24} {d['agent']}")
        return 0

    # revoke
    if not rest or (rest[0] != "--all" and rest[0].startswith("-")):
        print("usage: revoke --all | revoke <device id>   (see: devices)", file=sys.stderr)
        return 2
    target = rest[0]
    reply = control.ask(sock, {"verb": "revoke", "device": target})
    if reply is None:
        # Nothing running, so nothing holds the table in memory; edit the file.
        sessions = Sessions(store / "sessions.json")
        count = sessions.revoke_all() if target == "--all" else int(sessions.revoke(target))
    else:
        count = int(reply.get("revoked") or 0)
    if not count:
        print(f"No paired device called {target}.", file=sys.stderr)
        return 1
    print(f"Revoked {count} device{'s' if count != 1 else ''}.")
    return 0
