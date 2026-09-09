"""What an integration is, and what it is never allowed to become.

An integration connects Uncloud to something outside it — a folder of
documents, a mail account, a repository host. The shapes here are small; the
value is in the four rules they make structural, each of which is a way this
kind of feature normally goes wrong.

**A connection is not a permission.** Connecting an account says the account
exists and Uncloud can reach it. Whether the agent may read from it right now
is a separate question, answered by the permission gate at the moment of the
action. `Action.risk` exists so that every integration action has to be
classified, and an action with no classification cannot run — the same rule the
tool layer already enforces.

**A skill inherits nothing.** A skill naming an integration action is a skill
that will prompt for it, exactly as it would for a shell command. There is no
path by which connecting an integration widens what a skill may do, because
authority is never attached to the integration in the first place.

**Credentials never enter model context.** An adapter receives a handle and
asks the broker to open a client with it. The secret is not a field on anything
here, is not returned by any method here, and is not something a model can ask
for — which is stronger than redacting it, because there is nothing to redact.

**A write is previewed before it happens.** Anything that changes something
outside Uncloud produces a `Change` first, and the change is what a person
approves. "Send the email" is not a decision anybody can make well; "send THIS
email to THESE people" is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ..auth.contract import AuthKind, Connection, ProviderConfig, Scope
from ..permission import Risk
from .capabilities import Capability, risk_of, writes


class Sensitivity(StrEnum):
    """How freely this integration's content may travel.

    Read by the one check that decides whether integration data may enter a
    remote model's context. It is a property of the SOURCE rather than of the
    content, because nothing can classify a document by reading it and being
    wrong in the permissive direction is unrecoverable.
    """

    #: Ordinary working material. Goes to a remote model if the user has one
    #: configured and the task needs it.
    NORMAL = "normal"
    #: Correspondence, private repositories, anything with other people's
    #: personal data in it. Never leaves this machine unless the user has said
    #: so for this integration specifically.
    PRIVATE = "private"


@dataclass(frozen=True)
class Action:
    """One thing an integration can do, and which capability it implements.

    `capability` is what makes the orchestrator provider-agnostic: it plans in
    terms of `email.send` and the registry finds whatever is connected and able.
    Risk and write-ness are DERIVED from it rather than declared here, so two
    providers implementing the same capability cannot end up under different
    policies — which would mean sending mail asked for approval through Gmail
    and did not through Outlook.
    """

    id: str
    summary: str
    capability: Capability
    parameters: dict[str, str] = field(default_factory=dict)
    #: Scopes this action needs, where the provider issues them per-scope. Used
    #: to explain a failure as "you did not grant this" rather than as an error.
    scopes: tuple[str, ...] = ()

    @property
    def risk(self) -> Risk:
        return risk_of(self.capability)

    @property
    def writes(self) -> bool:
        return writes(self.capability)

    def to_dict(self) -> dict:
        return {"id": self.id, "summary": self.summary,
                "capability": self.capability.value, "risk": self.risk.value,
                "writes": self.writes, "parameters": dict(self.parameters),
                "scopes": list(self.scopes)}


@dataclass(frozen=True)
class Change:
    """What a write would do, in terms a person can approve or refuse.

    Not a diff of internal state. "Send the email" is not a decision anybody can
    make well; "send this subject, to these three addresses, with this body" is.
    `reversible` is stated because it changes what a reasonable person decides,
    and stating it wrongly is worse than not stating it.
    """

    summary: str
    target: str
    detail: str = ""
    reversible: bool = True
    #: What is being written, as text, capped by the caller. Shown in the
    #: approval, never stored in the audit log — the log records that a message
    #: was sent, not what it said.
    body: str = ""

    def to_dict(self) -> dict:
        return {"summary": self.summary, "target": self.target,
                "detail": self.detail, "reversible": self.reversible,
                "body": self.body}


class IntegrationError(Exception):
    """A failure with something a person can do about it.

    Integration failures are mostly not bugs — an expired token, a file that
    moved, a service that is down, a scope nobody granted. A stack trace answers
    none of those, so every failure carries a remedy, and `retryable` says
    whether trying again is even sensible.
    """

    def __init__(self, message: str, *, remedy: str = "", retryable: bool = False,
                 needs_reconnect: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.remedy = remedy
        self.retryable = retryable
        #: The credential is gone or rejected. Distinct from a transient
        #: failure, because reconnecting is a different action from waiting.
        self.needs_reconnect = needs_reconnect

    def to_dict(self) -> dict:
        return {"error": self.message, "remedy": self.remedy,
                "retryable": self.retryable,
                "needs_reconnect": self.needs_reconnect}


@dataclass
class Integration:
    """One connectable thing, and what it can do.

    Adapters subclass this. The base is deliberately inert: an integration that
    has not been implemented still appears, still describes what it would need,
    and reports `available = False` — which is a better interface state than
    hiding it, because "we do not support that" and "that needs a key you have
    to get from Google" send somebody in completely different directions.
    """

    id: str
    name: str
    summary: str
    sensitivity: Sensitivity = Sensitivity.NORMAL
    actions: tuple[Action, ...] = ()
    #: Whether the code to do this exists in this build. False is a real,
    #: displayable state and not an error.
    available: bool = False
    #: What is missing, when it is not available. Written for the person who
    #: has to go and get it.
    needs: str = ""
    #: Whether connecting requires a secret at all. A folder on disk does not.
    needs_credential: bool = True
    #: How this provider expects to be authenticated, and what it needs to be
    #: pointed at. Both are the provider's facts, not the user's.
    auth_kind: AuthKind = AuthKind.NONE
    defaults: ProviderConfig | None = None
    #: What each scope is for, in a person's terms. `mail.google.com/gmail.send`
    #: tells nobody anything; "Send mail as you" is what a consent screen is
    #: for.
    scopes: tuple[Scope, ...] = ()
    #: Platforms this can work on. Empty means anywhere.
    platforms: tuple[str, ...] = ()

    # ------------------------------------------------------------- queries
    def capabilities(self) -> frozenset[Capability]:
        return frozenset(a.capability for a in self.actions)

    def implements(self, capability: Capability) -> Action | None:
        """The action that provides this capability, if any.

        The lookup that makes capability routing work. An integration is asked
        what it can do rather than being matched by name.
        """
        return next((a for a in self.actions if a.capability is capability), None)

    def connection(self) -> Connection:
        """This provider's authentication state.

        Default implementation asks the shared connection store, so an adapter
        gets the five states, refresh and disconnect without writing any of it.
        """
        from ..auth import status as connection_status

        return connection_status(
            self.id, self.auth_kind,
            self.defaults or ProviderConfig(provider=self.id),
            account=self.account())

    def connected(self) -> bool:
        """Whether this is usable right now."""
        return self.connection().state.usable

    def account(self) -> str:
        """A label for what is connected — an address, a folder, a username.

        Never the credential. This string is shown in the interface and can
        reach a model's context, so it must be something a person would put on
        a screenshot.
        """
        return ""

    def action(self, action_id: str) -> Action | None:
        return next((a for a in self.actions if a.id == action_id), None)

    async def preview(self, action_id: str, arguments: dict) -> Change | None:
        """What this action would change, before it changes it.

        None for a read. A write that returns None is a bug, and `run` refuses
        rather than proceeding — see `registry.perform`.
        """
        return None

    async def run(self, action_id: str, arguments: dict) -> str:
        raise IntegrationError(
            f"{self.name} is not implemented in this build.",
            remedy=self.needs or "There is nothing to do about this yet.")

    def to_dict(self) -> dict:
        connection = self.connection()
        return {
            "id": self.id, "name": self.name, "summary": self.summary,
            "sensitivity": self.sensitivity.value,
            "available": self.available, "needs": self.needs,
            "needs_credential": self.needs_credential,
            "auth_kind": self.auth_kind.value,
            "platforms": list(self.platforms),
            "connected": connection.state.usable,
            "connection": connection.to_dict(),
            "account": connection.account or self.account(),
            "capabilities": sorted(c.value for c in self.capabilities()),
            "scopes": [s.to_dict() for s in self.scopes],
            "actions": [a.to_dict() for a in self.actions],
        }
