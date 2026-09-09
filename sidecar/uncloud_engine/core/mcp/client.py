"""A Model Context Protocol client, over stdio.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

MCP is JSON-RPC 2.0 framed as newline-delimited JSON over a subprocess's stdin
and stdout. That is small enough to implement directly, and implementing it
directly is worth more than a dependency here: the security properties below
are the whole point, and they are easier to guarantee in code we own.

**A server is untrusted input, not an authority.** It describes its own tools,
and those descriptions are written by whoever wrote the server. They are data.
A tool called `read_file` that actually posts to a webhook is entirely possible,
which is why every MCP tool goes through the same permission gate as a native
one and why its declared risk is never taken from the server's own say-so.

**Nothing is trusted about the transport either.** Responses are matched to
requests by id, a reply to an id nobody sent is discarded, and every read is
bounded — a server that writes an unterminated line forever must not take the
application with it.

**The process is owned.** Started on demand, stopped explicitly, and reaped on
shutdown. A server left running after the application closed is somebody's
laptop fan at three in the morning.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field

#: A server that has not answered in this long is not going to.
TIMEOUT = 30.0

#: Longest single line accepted from a server. A megabyte of JSON is already an
#: unreasonable tool result; an unbounded read is a way to exhaust memory.
MAX_LINE = 4_000_000


class McpError(Exception):
    """A server failed, with something a person can do about it."""

    def __init__(self, message: str, *, remedy: str = "",
                 fatal: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.remedy = remedy
        #: The connection is gone rather than the call having failed.
        self.fatal = fatal

    def to_dict(self) -> dict:
        return {"error": self.message, "remedy": self.remedy,
                "fatal": self.fatal}


@dataclass(frozen=True)
class ServerConfig:
    """How to start one server.

    Shaped like the configuration files people already have for MCP, so a
    server somebody has running elsewhere can be pasted in rather than
    re-described.
    """

    id: str
    command: str
    args: tuple[str, ...] = ()
    #: Environment for the child. Kept separate from this process's own so a
    #: server cannot read Uncloud's environment by accident — a token in the
    #: parent's environment is not the server's to have.
    env: dict[str, str] = field(default_factory=dict)
    cwd: str = ""
    label: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "command": self.command, "args": list(self.args),
                "cwd": self.cwd, "label": self.label or self.id,
                # Names only. A value here would be a secret on a settings
                # screen.
                "env_keys": sorted(self.env)}


@dataclass(frozen=True)
class Tool:
    """A tool a server says it has.

    `schema` is the server's own JSON Schema for its arguments. Passed to the
    model as a description and never used to decide whether the call is
    allowed — that is the gate's job, and a server describing its tool as
    harmless does not make it so.
    """

    name: str
    description: str = ""
    schema: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description,
                "schema": dict(self.schema)}


@dataclass(frozen=True)
class Resource:
    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""

    def to_dict(self) -> dict:
        return {"uri": self.uri, "name": self.name,
                "description": self.description, "mime_type": self.mime_type}


@dataclass(frozen=True)
class Prompt:
    name: str
    description: str = ""
    arguments: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description,
                "arguments": [dict(a) for a in self.arguments]}


class Server:
    """One MCP server subprocess, and the conversation with it."""

    def __init__(self, config: ServerConfig, *, spawn=None) -> None:
        self.config = config
        self._spawn = spawn or _spawn
        self._process = None
        self._next_id = 1
        self._lock = threading.Lock()
        self.tools: tuple[Tool, ...] = ()
        self.resources: tuple[Resource, ...] = ()
        self.prompts: tuple[Prompt, ...] = ()
        self.info: dict = {}
        self.error: str = ""

    # ------------------------------------------------------------- lifecycle
    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        """Start the process and complete the MCP handshake.

        Discovery happens here rather than lazily, because a server whose tools
        are unknown cannot be offered to a model, and finding out at the moment
        of a call means failing in the middle of somebody's task.
        """
        if self.running:
            return
        try:
            self._process = self._spawn(self.config)
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            raise McpError(
                f"Could not start {self.config.label or self.config.id}: {exc}",
                remedy="Check the command and that it is installed.",
                fatal=True) from exc

        try:
            self.info = self._request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "Uncloud", "version": "1"},
            })
            self._notify("notifications/initialized")
            self._discover()
        except McpError:
            self.stop()
            raise

    def _discover(self) -> None:
        """Ask what the server has. Absence of a list is not an error.

        Many servers implement tools and nothing else, and a client that
        required all three would refuse most of the ecosystem.
        """
        self.tools = tuple(
            Tool(name=str(t.get("name", "")),
                 description=str(t.get("description", "")),
                 schema=dict(t.get("inputSchema") or {}))
            for t in self._maybe("tools/list", "tools"))
        self.resources = tuple(
            Resource(uri=str(r.get("uri", "")), name=str(r.get("name", "")),
                     description=str(r.get("description", "")),
                     mime_type=str(r.get("mimeType", "")))
            for r in self._maybe("resources/list", "resources"))
        self.prompts = tuple(
            Prompt(name=str(p.get("name", "")),
                   description=str(p.get("description", "")),
                   arguments=tuple(p.get("arguments") or ()))
            for p in self._maybe("prompts/list", "prompts"))

    def _maybe(self, method: str, key: str) -> list:
        try:
            return list(self._request(method, {}).get(key) or [])
        except McpError:
            return []

    def stop(self) -> None:
        """End the process. Politely, then not.

        A server that ignores termination still gets killed: one left running
        after the application closed is somebody's fan at three in the morning.
        """
        process, self._process = self._process, None
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:  # noqa: BLE001 - killing is the fallback
            # Already gone, or refusing to go. Either way the end state is the
            # same and there is nothing a caller could do about it.
            with contextlib.suppress(Exception):
                process.kill()
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.close()

    # -------------------------------------------------------------- protocol
    def call(self, tool: str, arguments: dict) -> str:
        """Run one tool and return its text content.

        MCP results are a list of typed content blocks. Text is what a model
        can use; anything else is described rather than dropped, so a caller
        can see that an image came back instead of silently getting nothing.
        """
        if not self.running:
            self.start()
        result = self._request("tools/call",
                               {"name": tool, "arguments": arguments or {}})

        # A server reports a tool's own failure in the result rather than as a
        # protocol error. Treating that as success would hand the model an
        # error message as though it were an answer.
        if result.get("isError"):
            raise McpError(_text_of(result) or f"{tool} failed.",
                           remedy="Check the arguments the server expects.")
        return _text_of(result)

    def read_resource(self, uri: str) -> str:
        if not self.running:
            self.start()
        result = self._request("resources/read", {"uri": uri})
        parts = []
        for entry in result.get("contents") or []:
            if entry.get("text"):
                parts.append(str(entry["text"]))
            elif entry.get("blob"):
                parts.append(f"[binary content: {entry.get('mimeType', 'unknown')}]")
        return "\n".join(parts)

    def get_prompt(self, name: str, arguments: dict | None = None) -> str:
        if not self.running:
            self.start()
        result = self._request("prompts/get",
                               {"name": name, "arguments": arguments or {}})
        lines = []
        for message in result.get("messages") or []:
            content = message.get("content") or {}
            text = content.get("text") if isinstance(content, dict) else content
            if text:
                lines.append(f"{message.get('role', 'user')}: {text}")
        return "\n".join(lines)

    # -------------------------------------------------------------- JSON-RPC
    def _request(self, method: str, params: dict) -> dict:
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            self._send({"jsonrpc": "2.0", "id": request_id,
                        "method": method, "params": params})
            return self._await(request_id, method)

    def _notify(self, method: str, params: dict | None = None) -> None:
        with self._lock:
            self._send({"jsonrpc": "2.0", "method": method,
                        "params": params or {}})

    def _send(self, message: dict) -> None:
        if self._process is None or self._process.stdin is None:
            raise McpError(f"{self.config.id} is not running.",
                           remedy="Start it and try again.", fatal=True)
        try:
            self._process.stdin.write(json.dumps(message) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            raise McpError(
                f"{self.config.label or self.config.id} stopped listening.",
                remedy="It may have crashed. Reconnect it.",
                fatal=True) from exc

    def _await(self, request_id: int, method: str) -> dict:
        """Read until the matching reply arrives, or time out.

        Notifications and replies to other ids are discarded rather than
        treated as the answer — a server is free to send them at any time, and
        taking the first line as the response is how a client returns somebody
        else's result.
        """
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            line = self._read_line(deadline)
            if line is None:
                break
            try:
                message = json.loads(line)
            except ValueError:
                continue          # not JSON; a server logging to stdout
            if not isinstance(message, dict) or message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"] or {}
                raise McpError(
                    f"{self.config.label or self.config.id} refused {method}: "
                    f"{error.get('message', 'unknown error')}",
                    remedy="Check the arguments, or the server's own logs.")
            result = message.get("result")
            return result if isinstance(result, dict) else {}

        raise McpError(
            f"{self.config.label or self.config.id} did not answer {method}.",
            remedy="It may be slow, stuck, or not an MCP server.",
            fatal=True)

    def _read_line(self, deadline: float) -> str | None:
        if self._process is None or self._process.stdout is None:
            return None
        if self._process.poll() is not None:
            stderr = ""
            # Best effort. A server that died without writing anything is still
            # reportable; the message is just shorter.
            with contextlib.suppress(Exception):
                if self._process.stderr is not None:
                    stderr = self._process.stderr.read()[:500]
            raise McpError(
                f"{self.config.label or self.config.id} exited"
                + (f": {stderr.strip()}" if stderr.strip() else "."),
                remedy="Check the command and its arguments.", fatal=True)
        line = self._process.stdout.readline(MAX_LINE)
        if time.monotonic() > deadline:
            return None
        return line if line else None


def _text_of(result: dict) -> str:
    parts = []
    for block in result.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        else:
            parts.append(f"[{block.get('type', 'content')}]")
    return "\n".join(parts).strip()


def _spawn(config: ServerConfig):
    """Start the server process.

    The environment is built rather than inherited. Uncloud's own process may
    hold API tokens, and handing them to somebody else's subprocess because it
    happened to be a child is exactly the kind of leak that is invisible until
    it matters. PATH and HOME are passed because a server that cannot find its
    own interpreter is useless.
    """
    environment = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SystemRoot",
                    "USERPROFILE", "APPDATA")
        if key in os.environ
    }
    environment.update(config.env)

    return subprocess.Popen(
        [config.command, *config.args],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1, env=environment,
        cwd=config.cwd or None)
