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
from dataclasses import dataclass

from ..auth import AuthKind
from ..integrations.capabilities import Capability, stricter
from ..integrations.contract import (
    Action,
    Change,
    Integration,
    IntegrationError,
    Sensitivity,
)
from ..permission import Risk
from .client import McpError, Server, ServerConfig

#: Words that identify what a tool does, matched as whole tokens. Ordered most
#: severe first, because the first match wins and `readAndDelete` should be
#: governed as the more dangerous of the two.
#:
#: These are TOKENS, not substrings. `get` inside `widget` once classified
#: `frobnicate_the_widget` as a read, and that is the direction this must never
#: be wrong in.
_SIGNALS: tuple[tuple[Risk, tuple[str, ...]], ...] = (
    (Risk.SHELL, ("shell", "exec", "command", "bash", "sh", "zsh", "terminal",
                  "subprocess", "eval", "spawn", "process")),
    (Risk.DELETE, ("delete", "remove", "destroy", "drop", "purge", "rm",
                   "truncate", "erase", "wipe", "clear", "prune", "unlink")),
    (Risk.MESSAGE, ("send", "email", "mail", "post", "publish", "message",
                    "notify", "tweet", "slack", "sms", "reply", "broadcast",
                    "invite", "comment")),
    (Risk.INSTALL, ("install", "download", "pip", "npm", "cargo", "package",
                    "provision")),
    (Risk.NETWORK, ("fetch", "http", "https", "request", "curl", "browse",
                    "url", "scrape", "crawl", "webhook")),
    (Risk.WRITE, ("write", "create", "update", "edit", "modify", "set",
                  "insert", "append", "upload", "commit", "save", "put",
                  "patch", "rename", "move", "add", "push", "apply")),
    (Risk.READ, ("read", "get", "list", "search", "find", "query", "describe",
                 "show", "view", "lookup", "inspect", "count", "stat")),
)

#: The same words, usable as substrings — but ONLY for categories more severe
#: than the default. `deleteeverything` has no separator to tokenise on, and
#: matching `delete` inside it raises the classification, which is safe.
#: Substring matching is never applied to READ or WRITE, so it can only ever
#: make a tool more restricted than the fallback, never less.
_SUBSTRING_SIGNALS: tuple[tuple[Risk, tuple[str, ...]], ...] = tuple(
    (risk, tuple(word for word in words if len(word) >= 5))
    for risk, words in _SIGNALS
    if risk not in (Risk.READ, Risk.WRITE)
)

#: What a tool nobody could classify is treated as. Deliberately not READ: an
#: unrecognised tool from somebody else's server is not a thing to wave through
#: under the mildest policy in the system.
UNKNOWN = Risk.WRITE

_WORDS = re.compile(r"[^A-Za-z0-9]+")

#: camelCase is the other common naming style for MCP tools, and `sendMail` has
#: no separator to split on. Without this it tokenises as one word and a short
#: signal like `send` never matches — which made it a WRITE rather than a
#: MESSAGE, an under-classification.
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _tokens(text: str) -> set[str]:
    """Words, however the author separated them.

    Handles `snake_case`, `kebab-case`, `camelCase` and `HTTPRequest` — the
    last needing the second alternative in `_CAMEL`, since `HTTPRequest`
    splits between the P and the R rather than at every capital.
    """
    out: set[str] = set()
    for chunk in _WORDS.split(text):
        for word in _CAMEL.split(chunk):
            if word:
                out.add(word.lower())
    return out


@dataclass(frozen=True)
class Classification:
    """How a tool will be governed, and how that was decided.

    `why` and `certain` exist so the interface can say. An inference about
    somebody else's code that nobody can see is one nobody can disagree with,
    and the tools this gets wrong are exactly the ones a user would recognise
    at a glance.
    """

    risk: Risk
    why: str
    #: False when nothing identified the tool and the fallback was used. The
    #: interface offers to let somebody classify it themselves.
    certain: bool = True

    def to_dict(self) -> dict:
        return {"risk": self.risk.value, "why": self.why,
                "certain": self.certain}


def _from_annotations(annotations: dict) -> Risk | None:
    """What the server's own hints justify, and only ever upward.

    The MCP specification lets a server describe its tool as destructive, or as
    reaching the open world. Those are admissions against interest and can be
    believed. `readOnlyHint` is the opposite — a server wanting to be waved
    through would set exactly that — so it is never acted on. A tool claiming
    to be read-only is classified on its name like any other.
    """
    if annotations.get("destructiveHint") is True:
        return Risk.DELETE
    if annotations.get("openWorldHint") is True:
        return Risk.NETWORK
    return None


def classify(tool_name: str, description: str = "", *,
             annotations: dict | None = None,
             declared: Risk | None = None) -> Classification:
    """How to govern one MCP tool.

    Four sources, in this order, and the order is the design:

    1. **A person's own classification.** The user is the authority on their
       own machine, and this is the only input that may LOWER a category —
       which is what makes "require explicit classification rather than
       guessing" a real option rather than advice.
    2. **The server's admissions against interest.** Destructive and
       open-world hints raise; a read-only hint is ignored.
    3. **The tool's name**, as whole tokens, most severe signal first.
    4. **Its description**, for everything except READ. A description saying
       "read" proves nothing, and a server that wanted to be waved through
       would say exactly that.

    Anything unidentified is `UNKNOWN` — a write — and is marked uncertain so
    somebody can be asked.
    """
    if declared is not None:
        return Classification(declared, "you classified this tool")

    hinted = _from_annotations(annotations or {})

    name_tokens = _tokens(tool_name)
    for risk, words in _SIGNALS:
        if name_tokens & set(words):
            inferred = Classification(risk, f"its name says {risk.value}")
            return _at_least(inferred, hinted)

    lowered = tool_name.lower()
    for risk, words in _SUBSTRING_SIGNALS:
        if any(word in lowered for word in words):
            return _at_least(
                Classification(risk, f"its name contains {risk.value}"), hinted)

    prose = _tokens(description)
    for risk, words in _SIGNALS:
        if risk is Risk.READ:
            continue
        if prose & set(words):
            return _at_least(
                Classification(risk, f"its description says {risk.value}"),
                hinted)

    if hinted is not None:
        return Classification(hinted, f"the server declares it {hinted.value}")
    return Classification(
        UNKNOWN,
        "nothing identified this tool, so it is treated as a write",
        certain=False)


def _at_least(inferred: Classification, hinted: Risk | None) -> Classification:
    """Take whichever of the two is harder to undo.

    The server's hint can raise the inference and can never lower it, so a tool
    named `get_page` that admits to being destructive is governed as a delete.
    """
    if hinted is None:
        return inferred
    combined = stricter(inferred.risk, hinted)
    if combined is inferred.risk:
        return inferred
    return Classification(combined, f"the server declares it {hinted.value}")


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
        overrides = self.overrides()
        for tool in self.server.tools:
            decided = classify(tool.name, tool.description,
                               annotations=tool.annotations,
                               declared=overrides.get(tool.name))
            actions.append(Action(
                id=f"{self.id}.{tool.name}",
                capability=_CAPABILITY.get(decided.risk,
                                           Capability.STORAGE_WRITE),
                summary=tool.description or tool.name,
                parameters=_parameters(tool.schema),
                # The capability is a coarse bucket; this is the classification
                # the gate actually uses, and it can only tighten.
                at_least=decided.risk))
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
    def overrides(self) -> dict[str, Risk]:
        """Classifications a person set themselves, by tool name.

        The only input that may LOWER a category. The user is the authority on
        their own machine; the server is not, which is why its hints can only
        raise.
        """
        from . import manager

        return manager.overrides_for(self.config.id)

    def classification(self, tool_name: str) -> Classification:
        """How this tool is governed, and how that was decided.

        Surfaced rather than hidden because it is an inference about somebody
        else's code. A user who disagrees should be able to see it and correct
        it, rather than discover it by being asked at the wrong moment — or
        worse, by not being asked.
        """
        overrides = self.overrides()
        for tool in self.server.tools:
            if tool.name == tool_name:
                return classify(tool.name, tool.description,
                                annotations=tool.annotations,
                                declared=overrides.get(tool_name))
        return Classification(UNKNOWN, "no such tool", certain=False)

    def risk_of(self, tool_name: str) -> Risk:
        return self.classification(tool_name).risk

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
                       **self.classification(t.name).to_dict()}
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
