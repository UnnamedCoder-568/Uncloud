"""What a connection to a provider is, and what state it can be in.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Three things are kept apart here that every integration codebase eventually
conflates, and conflating them is why "reconnect it" becomes the only advice
support can give:

* **Provider configuration** — the OAuth client. It belongs to whoever
  published the application, is registered with Google or Slack or whoever, and
  is the same for every user of that build.
* **Authentication state** — this person's tokens. Personal, expiring,
  revocable.
* **Authorisation** — what the agent may do with them right now. Not here at
  all: that is the permission gate, asked per action.

A connection being live says the provider will answer. It says nothing about
whether the agent may send an email, and nothing in this package is ever
consulted to decide that.

**No credential is a field on anything in this module.** `Connection` carries a
state, an account label and a scope list. The tokens live in the credential
broker, which hands them to a request builder and never to application code.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class AuthKind(StrEnum):
    """How a provider expects to be authenticated."""

    #: Authorisation-code with PKCE, over a loopback redirect. The right answer
    #: for a desktop application: no client secret has to be shipped, and RFC
    #: 8252 is explicit that this is the pattern for native apps.
    OAUTH2_PKCE = "oauth2_pkce"
    #: Authorisation-code with a client secret. Used where a provider does not
    #: support PKCE. The secret is the USER's, entered in Settings — never ours.
    OAUTH2_SECRET = "oauth2_secret"
    #: A token the user creates on the provider's site and pastes in. Simpler,
    #: needs no application registration at all, and is the whole reason GitHub
    #: works out of the box while Google cannot.
    TOKEN = "token"
    #: A folder, a local socket, a subprocess. Nothing to authenticate.
    NONE = "none"


class ConnectionState(StrEnum):
    """What the interface should say, and what it should offer.

    Five states rather than a boolean, because "not working" has five different
    remedies and telling somebody the wrong one wastes their afternoon.
    """

    #: The application has no OAuth client for this provider. The user has to
    #: register one — this is not something Uncloud can ship, and pretending
    #: otherwise would mean fabricating somebody else's credentials.
    NOT_CONFIGURED = "not_configured"
    #: Configured, nobody has signed in.
    NOT_CONNECTED = "not_connected"
    CONNECTED = "connected"
    #: Tokens existed and are no longer accepted — expired past refresh, or
    #: revoked at the provider. Distinct from NOT_CONNECTED because the user
    #: did connect, and the difference is the difference between "sign in" and
    #: "something changed".
    AUTHENTICATION_REQUIRED = "authentication_required"
    #: The last attempt failed for a reason that is not authentication.
    ERROR = "error"
    #: This provider cannot work on this machine at all.
    UNAVAILABLE = "unavailable"

    @property
    def usable(self) -> bool:
        return self is ConnectionState.CONNECTED


@dataclass(frozen=True)
class Scope:
    """One permission a provider grants, and what it is for in plain terms.

    Described rather than listed raw. `https://www.googleapis.com/auth/gmail.send`
    tells a person nothing; "Send mail as you" tells them what they are about
    to agree to, which is the only reason to show a consent screen at all.
    """

    id: str
    summary: str
    #: Whether the integration is useless without it. A user who wants to read
    #: mail but not send it should be able to decline the second.
    required: bool = True

    def to_dict(self) -> dict:
        return {"id": self.id, "summary": self.summary, "required": self.required}


@dataclass(frozen=True)
class ProviderConfig:
    """The OAuth client. Registered by whoever publishes this build.

    **Uncloud ships none of these and never will.** An OAuth client identifies
    an application to Google or Slack, is issued under their terms to a named
    party, and inventing one would be both a lie and a violation. What the
    software does instead is make configuring your own straightforward, and say
    clearly when it is missing — which is the `NOT_CONFIGURED` state.
    """

    provider: str
    client_id: str = ""
    #: Empty for PKCE, which is the point of PKCE. Where a provider insists on
    #: one, it is the user's own and is stored like any other secret.
    has_secret: bool = False
    authorize_url: str = ""
    token_url: str = ""
    revoke_url: str = ""
    #: Extra parameters a provider requires on the authorisation request —
    #: Google's `access_type=offline`, Microsoft's tenant. Kept as data so a
    #: provider quirk never becomes a branch in the flow.
    extra_authorize: dict[str, str] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.authorize_url and self.token_url)

    def to_dict(self) -> dict:
        return {"provider": self.provider, "client_id": self.client_id,
                "has_secret": self.has_secret, "configured": self.configured,
                "authorize_url": self.authorize_url, "token_url": self.token_url}


@dataclass
class Tokens:
    """What came back from the provider. Never leaves this package.

    Held in memory only for the length of a request build; the persistent copy
    is in the credential broker, in the OS keychain.
    """

    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0
    scopes: tuple[str, ...] = ()
    token_type: str = "Bearer"

    #: Refreshed this far before the stated expiry. A token that expires
    #: mid-request produces a failure that looks like a bug in the integration,
    #: and providers' clocks are not ours.
    SKEW = 120.0

    @property
    def expired(self) -> bool:
        if not self.expires_at:
            return False          # no expiry stated; assume long-lived
        return time.time() >= self.expires_at - self.SKEW

    @property
    def refreshable(self) -> bool:
        return bool(self.refresh_token)

    def to_storage(self) -> dict:
        return {"access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expires_at": self.expires_at, "scopes": list(self.scopes),
                "token_type": self.token_type}

    @classmethod
    def from_storage(cls, raw: dict) -> Tokens:
        return cls(access_token=str(raw.get("access_token", "")),
                   refresh_token=str(raw.get("refresh_token", "")),
                   expires_at=float(raw.get("expires_at") or 0.0),
                   scopes=tuple(raw.get("scopes") or ()),
                   token_type=str(raw.get("token_type") or "Bearer"))


@dataclass
class Connection:
    """One provider's state on this machine, as the interface may see it."""

    provider: str
    kind: AuthKind
    state: ConnectionState
    #: An address, a username, a workspace. Shown, so it must be something a
    #: person would put on a screenshot.
    account: str = ""
    scopes: tuple[str, ...] = ()
    expires_at: float = 0.0
    #: What went wrong, and what to do. Empty when nothing did.
    error: str = ""
    remedy: str = ""
    connected_at: str = ""

    def to_dict(self) -> dict:
        return {"provider": self.provider, "kind": self.kind.value,
                "state": self.state.value, "usable": self.state.usable,
                "account": self.account, "scopes": list(self.scopes),
                "expires_at": self.expires_at, "error": self.error,
                "remedy": self.remedy, "connected_at": self.connected_at}


class AuthError(Exception):
    """Authentication failed, with something a person can act on.

    `needs_reauthentication` separates "sign in again" from "wait and retry",
    which are different actions — and telling somebody to retry a revoked token
    is how support tickets get long.
    """

    def __init__(self, message: str, *, remedy: str = "",
                 needs_reauthentication: bool = False,
                 needs_configuration: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.remedy = remedy
        self.needs_reauthentication = needs_reauthentication
        self.needs_configuration = needs_configuration

    def to_dict(self) -> dict:
        return {"error": self.message, "remedy": self.remedy,
                "needs_reauthentication": self.needs_reauthentication,
                "needs_configuration": self.needs_configuration}
