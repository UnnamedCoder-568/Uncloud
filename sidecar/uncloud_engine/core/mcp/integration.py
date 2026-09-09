"""MCP servers as integrations, so their tools are governed like any other.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

The rule this file exists to enforce: **an MCP tool is not more trusted than a
native one, and not less.** It goes into the same registry, is classified by
the same risk categories, is asked about by the same gate, and is previewed the
same way. There is no MCP-specific security model, and that is deliberate —
a second model would be a second thing to get right, and the one that gets less
attention is the one covering somebody else's code.

**Risk is inferred from the tool's NAME and schema, then rounded up.** A server
describes itself, and its description is written by whoever wrote it. So the
inference is one-directional: signals that suggest danger raise the category,
and nothing a server can say lowers it. A tool nothing matches is treated as
WRITE rather than READ, because an unclassified tool from an unknown server is
not a safe default.

**One integration per server.** Ten servers are ten integrations, each
connected or not on its own, so a broken one does not take the others with it.
"""

from __future__ import annotations

import re

from ..auth import AuthKind
from ..integrations.capabilities import Capability
from ..integrations.contract import (
    Action,
    Change,
    Integration,
    IntegrationError,
    Sensitivity,
)
from ..permission import Risk
from .client import McpError, Server, ServerConfig

#: Words that raise a tool's risk, matched against its name and then its
#: description. Only ever upward — see the module docstring.
#:
#: Ordered most severe first, because the first match wins and a tool called
#: `delete_and_email` should be governed as the more dangerous of the two.
_SIGNALS: tuple[tuple[Risk, tuple[str, ...]], ...] = (
    (Risk.SHELL, ("shell", "exec", "command", "bash", "terminal", "subprocess",
                  "eval", "spawn")),
    (Risk.DELETE, ("delete", "remove", "destroy", "drop", "purge", "rm",
                   "truncate", "erase")),
    (Risk.MESSAGE, ("send", "email", "mail", "post", "publish", "message",
                    "notify", "tweet", "slack", "sms", "reply")),
    (Risk.INSTALL, ("install", "download", "pip", "npm", "package")),
    (Risk.NETWORK, ("fetch", "http", "request", "curl", "browse", "url",
                    "scrape")),
    (Risk.WRITE, ("write", "create", "update", "edit", "modify", "set",
                  "insert", "append", "upload", "commit", "save", "put",
                  "patch", "rename", "move")),
    (Risk.READ, ("read", "get", "list", "search", "find", "query", "describe",
                 "show", "view", "lookup", "fetch")),
)

#: Below this length a word is matched only as a whole token. `get` inside
#: `widget` classified a tool called `frobnicate_the_widget` as a read, which
#: is exactly the direction this must never be wrong in.
_TOKEN_ONLY = 5

_WORDS = re.compile(r"[^A-Za-z0-9]+")

#: camelCase is the other common naming style for MCP tools, and `sendMail`
#: has no separator to split on. Without this it tokenises as one word and a
#: short signal like `send` never matches.
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    for chunk in _WORDS.split(text):
        for word in _CAMEL.split(chunk):
            if word:
                out.add(word.lower())
    return out


def _matches(word: str, text: str, tokens: set[str]) -> bool:
    if word in tokens:
        return True
    # Long words are distinctive enough that finding them anywhere is a real
    # signal — `deleteEverything` has no separator to tokenise on.
    return len(word) >= _TOKEN_ONLY and word in text


def classify(tool_name: str, description: str = "") -> Risk:
    """Which risk category an MCP tool falls under.

    Deliberately pessimistic. The name is the strongest signal because it is
    what a server author writes for a model to read, and the description is
    checked second. Anything matching nothing is WRITE — not READ — because an
    unrecognised tool from somebody else's server is not a thing to wave
    through under the mildest policy in the system.
    """
    # Tokenised from the ORIGINAL, because lowercasing first destroys the
    # camelCase boundary that `sendMail` depends on.
    name_tokens = _tokens(tool_name)
    name = tool_name.lower()
    for risk, words in _SIGNALS:
        if any(_matches(word, name, name_tokens) for word in words):
            return risk

    prose_tokens = _tokens(description)
    prose = description.lower()
    for risk, words in _SIGNALS:
        # The read signals are not trusted from prose: a description saying
        # "read" proves nothing about what the tool does, and a server that
        # wanted to be waved through would say exactly that.
        if risk is Risk.READ:
            continue
        if any(_matches(word, prose, prose_tokens) for word in words):
            return risk
    return Risk.WRITE


#: Risk to the capability an MCP tool is registered under. MCP tools do not map
#: onto the shared capability vocabulary — a server can do anything — so they
#: are grouped by what they RISK instead, which is what routing and policy
#: actually need to know.
_CAPABILITY: dict[Risk, Capability] = {
    Risk.READ: Capability.STORAGE_READ,
    Risk.WRITE: Capability.STORAGE_WRITE,
    Risk.NETWORK: Capability.STORAGE_READ,
    Risk.MESSAGE: Capability.CHAT_MESSAGE_SEND,
    Risk.DELETE: Capability.STORAGE_WRITE,
    Risk.INSTALL: Capability.STORAGE_WRITE,
    Risk.SHELL: Capability.STORAGE_WRITE,
}

_SAFE_ID = re.compile(r"[^a-z0-9_]+")


class McpIntegration(Integration):
    """One MCP server, exposed as an integration."""

    def __init__(self, config: ServerConfig, *, server: Server | None = None) -> None:
        self.config = config
        self.server = server or Server(config)
        ident = f"mcp.{_SAFE_ID.sub('-', config.id.lower())}"
        super().__init__(
            id=ident,
            name=config.label or config.id,
            summary=f"Tools from the {config.label or config.id} MCP server.",
            # Somebody else's code, reaching whatever it reaches. Its output
            # does not go to a remote model unless the user says so for this
            # server specifically.
            sensitivity=Sensitivity.PRIVATE,
            available=True,
            needs_credential=False,
            auth_kind=AuthKind.NONE,
            needs="",
            actions=())
        self._rebuild()

    # ------------------------------------------------------------- discovery
    def _rebuild(self) -> None:
        """Turn what the server declared into governed actions.

        Called after every successful start, because a server may legitimately
        offer different tools on a later run — a filesystem server pointed at a
        different root, say — and caching the first answer forever would make
        that invisible.
        """
        actions = []
        for tool in self.server.tools:
            risk = classify(tool.name, tool.description)
            actions.append(Action(
                id=f"{self.id}.{tool.name}",
                capability=_CAPABILITY.get(risk, Capability.STORAGE_WRITE),
                summary=tool.description or tool.name,
                parameters=_parameters(tool.schema),
                # The capability is a coarse bucket; this is the classification
                # the gate actually uses, and it can only tighten.
                at_least=risk))
        for resource in self.server.resources:
            actions.append(Action(
                id=f"{self.id}.resource:{resource.uri}",
                capability=Capability.STORAGE_READ,
                summary=resource.description or resource.name or resource.uri,
                parameters={}))
        self.actions = tuple(actions)

    def connected(self) -> bool:
        return self.server.running

    def account(self) -> str:
        return self.config.command

    def connect(self) -> None:
        self.server.start()
        self._rebuild()

    def disconnect(self) -> None:
        self.server.stop()

    # ------------------------------------------------------- risk, in the open
    def risk_of(self, tool_name: str) -> Risk:
        """What this server's tool is governed as. Shown in the interface.

        Surfaced rather than hidden because it is a guess about somebody else's
        code, and a user who disagrees should be able to see it and tighten the
        category rather than discover it by being asked at the wrong moment.
        """
        for tool in self.server.tools:
            if tool.name == tool_name:
                return classify(tool.name, tool.description)
        return Risk.WRITE

    # --------------------------------------------------------------- preview
    async def preview(self, action_id: str, arguments: dict) -> Change | None:
        action = self.action(action_id)
        if action is None or not action.writes:
            return None
        tool_name = action_id.split(".", 2)[-1]
        return Change(
            summary=f"{self.name}: {tool_name}",
            target=self.config.command,
            detail=action.summary,
            # A server's effects are outside Uncloud and unknown to it.
            # Claiming reversibility would be a guess about somebody else's
            # code, and the wrong guess is the expensive one.
            reversible=False,
            body="\n".join(f"{k}: {v}" for k, v in (arguments or {}).items())[:1000])

    # --------------------------------------------------------------- actions
    async def run(self, action_id: str, arguments: dict) -> str:
        if not self.server.running:
            self.connect()

        suffix = action_id[len(self.id) + 1:] if action_id.startswith(self.id) \
            else action_id
        try:
            if suffix.startswith("resource:"):
                return self.server.read_resource(suffix[len("resource:"):])
            return self.server.call(suffix, arguments or {})
        except McpError as exc:
            raise IntegrationError(exc.message, remedy=exc.remedy,
                                   needs_reconnect=exc.fatal) from exc

    def to_dict(self) -> dict:
        base = super().to_dict()
        base["mcp"] = {
            "config": self.config.to_dict(),
            "running": self.server.running,
            "tools": [{**t.to_dict(),
                       "risk": classify(t.name, t.description).value}
                      for t in self.server.tools],
            "resources": [r.to_dict() for r in self.server.resources],
            "prompts": [p.to_dict() for p in self.server.prompts],
            "server_info": dict(self.server.info.get("serverInfo") or {}),
        }
        return base


def _parameters(schema: dict) -> dict[str, str]:
    """A tool's arguments, described for a model.

    The server's JSON Schema flattened to name → description. Shown to the
    model as guidance and never used to validate — a server that lied about its
    schema would be caught by the call failing, not by us pretending to check.
    """
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}
    required = set(schema.get("required") or ())
    out = {}
    for name, spec in properties.items():
        if not isinstance(spec, dict):
            continue
        described = str(spec.get("description") or spec.get("type") or "")
        out[str(name)] = described + ("" if name in required else " (optional)")
    return out
