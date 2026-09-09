"""Which MCP servers this machine knows about, and keeping them alive.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Configuration is stored through the same credential broker everything else
uses, which gets one property for free and it is the important one: a server's
`env` may contain an API token, and the broker already knows how to keep a
secret out of the readable index.

Servers are started on demand rather than at launch. Ten configured servers
would otherwise be ten subprocesses at start-up, most of them never used, on a
machine whose memory is already the constraint.
"""

from __future__ import annotations

import contextlib
import json
import threading

from ..integrations import credentials as broker
from .client import McpError, ServerConfig
from .integration import McpIntegration

#: Handle prefix in the credential broker.
_CONFIG = "mcp.server"

_servers: dict[str, McpIntegration] = {}
_lock = threading.Lock()


def _handle(server_id: str) -> str:
    return f"{_CONFIG}.{server_id}"


# ----------------------------------------------------------- configuration
def configure(config: ServerConfig) -> None:
    """Record a server. The environment goes where secrets go.

    Split deliberately: the command and arguments are displayable, and a
    settings screen that needed an unlock prompt to list servers would be
    unusable. The environment might hold a token, so it does not go in the
    readable index.
    """
    readable = {"id": config.id, "command": config.command,
                "args": list(config.args), "cwd": config.cwd,
                "label": config.label, "env_keys": sorted(config.env)}
    broker.remember_path(_handle(config.id), json.dumps(readable))
    if config.env:
        broker.store(f"{_handle(config.id)}.env", json.dumps(config.env),
                     label=f"{config.label or config.id} environment",
                     kind="secret")
    with _lock:
        existing = _servers.pop(config.id, None)
    if existing is not None:
        existing.disconnect()


def forget(server_id: str) -> bool:
    """Remove a server, stopping it first."""
    with _lock:
        existing = _servers.pop(server_id, None)
    if existing is not None:
        existing.disconnect()
    broker.forget(f"{_handle(server_id)}.env")
    return broker.forget(_handle(server_id))


def configured() -> list[ServerConfig]:
    out = []
    for handle in broker.describe():
        name = handle["handle"]
        if not name.startswith(f"{_CONFIG}.") or name.endswith(".env"):
            continue
        stored = broker.path_of(name)
        if stored is None:
            continue
        try:
            raw = json.loads(str(stored))
        except (TypeError, ValueError):
            continue
        out.append(ServerConfig(
            id=str(raw.get("id", "")), command=str(raw.get("command", "")),
            args=tuple(raw.get("args") or ()), cwd=str(raw.get("cwd", "")),
            label=str(raw.get("label", "")), env=_environment(raw.get("id", ""))))
    return sorted(out, key=lambda c: c.id)


def _environment(server_id: str) -> dict[str, str]:
    holder: dict = {}
    try:
        broker.open(f"{_handle(server_id)}.env",
                    lambda raw: holder.setdefault("raw", raw))
    except broker.NotConnected:
        return {}
    try:
        return dict(json.loads(holder["raw"]))
    except (KeyError, TypeError, ValueError):
        return {}


# --------------------------------------------------------------- lifecycle
def integrations() -> list[McpIntegration]:
    """Every configured server, as an integration.

    Instances are kept so a running server stays running between calls. A fresh
    object per call would spawn a subprocess per request, which is how a
    settings page ends up starting ten node processes.
    """
    with _lock:
        for config in configured():
            if config.id not in _servers:
                _servers[config.id] = McpIntegration(config)
        return list(_servers.values())


def get(server_id: str) -> McpIntegration | None:
    for integration in integrations():
        if integration.config.id == server_id:
            return integration
    return None


def connect(server_id: str) -> McpIntegration:
    """Start a server and discover what it offers."""
    integration = get(server_id)
    if integration is None:
        raise McpError(f"There is no MCP server called {server_id!r}.",
                       remedy="Add it in Settings → Integrations.")
    integration.connect()
    return integration


def disconnect(server_id: str) -> bool:
    integration = get(server_id)
    if integration is None:
        return False
    integration.disconnect()
    return True


def shutdown() -> None:
    """Stop every server. Called when the application closes.

    Without this a subprocess outlives the application that started it, which
    is invisible until somebody notices their laptop is warm.
    """
    with _lock:
        running = list(_servers.values())
        _servers.clear()
    for integration in running:
        # One server refusing to stop must not leave the rest running.
        with contextlib.suppress(Exception):
            integration.disconnect()


def describe() -> list[dict]:
    return [integration.to_dict() for integration in integrations()]
