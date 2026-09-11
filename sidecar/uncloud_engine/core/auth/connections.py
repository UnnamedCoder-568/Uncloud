"""Connection state: what is signed in, and keeping it that way.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

This is the layer an integration adapter actually talks to. It answers one
question — "give me a way to call this provider" — and handles everything
between that and a live access token: reading storage, noticing expiry,
refreshing, recording the result, and turning a revoked token into a state the
interface can explain.

**An adapter never sees a token.** `authorize()` returns headers. That keeps
the same guarantee the credential broker makes: there is no access token in
application code, so there is nothing for a log line, a tool result, an
exception or a model prompt to leak.

**Refresh is serialised per provider.** Two requests noticing an expiry at the
same moment would otherwise both refresh, and providers that rotate refresh
tokens invalidate the first one when the second lands — turning a working
connection into a broken one under load, which is the worst time.

**Provider configuration and user tokens are stored separately.** A client ID
is not a secret and has to be displayable; tokens are and must not be. Mixing
them means either an unlock prompt to render a settings page, or a token in a
plain JSON file.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from ..integrations import credentials as broker
from .contract import (
    AuthError,
    AuthKind,
    Connection,
    ConnectionState,
    ProviderConfig,
    Tokens,
)
from .oauth import Flow, revoke

#: Handle prefixes in the credential broker. Namespaced so a provider called
#: `documents` cannot collide with the documents folder's own connection.
_TOKENS = "auth.tokens"
_SECRET = "auth.secret"
_CONFIG = "auth.config"

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock_for(provider: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(provider, threading.RLock())


# ------------------------------------------------------------ configuration
def configure_provider(config: ProviderConfig, *, client_secret: str = "") -> None:
    """Record an OAuth client the user registered.

    The client ID goes in the readable index — it is not a secret, it appears
    in every authorisation URL, and hiding it would mean an unlock prompt to
    draw a settings screen. A client secret, where a provider insists on one,
    goes to the keychain like anything else.
    """
    broker.remember_path(f"{_CONFIG}.{config.provider}",
                         json.dumps(config.to_dict()))
    if client_secret:
        broker.store(f"{_SECRET}.{config.provider}", client_secret,
                     label=f"{config.provider} client secret", kind="secret")


def provider_config(provider: str, defaults: ProviderConfig) -> ProviderConfig:
    """What is configured for this provider, over the adapter's defaults.

    An adapter supplies the URLs — those are the provider's, not the user's —
    and the user supplies the client ID. Merging here means an adapter never
    has to know how configuration is stored.
    """
    stored = broker.path_of(f"{_CONFIG}.{provider}")
    if stored is None:
        return defaults
    try:
        raw = json.loads(str(stored))
    except (TypeError, ValueError):
        return defaults
    return ProviderConfig(
        provider=provider,
        client_id=str(raw.get("client_id") or defaults.client_id),
        has_secret=bool(raw.get("has_secret") or defaults.has_secret),
        authorize_url=str(raw.get("authorize_url") or defaults.authorize_url),
        token_url=str(raw.get("token_url") or defaults.token_url),
        revoke_url=str(raw.get("revoke_url") or defaults.revoke_url),
        extra_authorize=dict(defaults.extra_authorize))


def forget_provider_config(provider: str) -> None:
    broker.forget(f"{_CONFIG}.{provider}")
    broker.forget(f"{_SECRET}.{provider}")


# -------------------------------------------------------------------- state
def _read_tokens(provider: str) -> Tokens | None:
    holder: dict = {}
    try:
        broker.open(f"{_TOKENS}.{provider}",
                    lambda raw: holder.setdefault("raw", raw))
    except broker.NotConnected:
        return None
    try:
        return Tokens.from_storage(json.loads(holder["raw"]))
    except (KeyError, ValueError):
        return None


def _write_tokens(provider: str, tokens: Tokens, *, account: str) -> None:
    broker.store(f"{_TOKENS}.{provider}", json.dumps(tokens.to_storage()),
                 label=account or provider, kind="oauth")


def status(provider: str, kind: AuthKind, defaults: ProviderConfig,
           *, account: str = "") -> Connection:
    """What the interface should say about this provider right now.

    Deliberately does not touch the network. A settings page that made a token
    request per row would be slow, would burn rate limit, and would refresh
    tokens as a side effect of being looked at.
    """
    if kind is AuthKind.NONE:
        return Connection(provider=provider, kind=kind,
                          state=ConnectionState.CONNECTED, account=account)

    if kind is AuthKind.TOKEN:
        held = broker.held(f"{_TOKENS}.{provider}")
        if held is None:
            return Connection(provider=provider, kind=kind,
                              state=ConnectionState.NOT_CONNECTED)
        return Connection(provider=provider, kind=kind,
                          state=ConnectionState.CONNECTED,
                          account=held.label, connected_at=held.stored_at)

    config = provider_config(provider, defaults)
    if not config.configured:
        return Connection(
            provider=provider, kind=kind,
            state=ConnectionState.NOT_CONFIGURED,
            remedy=(f"Register an OAuth application with {provider} and enter "
                    f"its client ID in Settings → Integrations."))

    tokens = _read_tokens(provider)
    if tokens is None:
        return Connection(provider=provider, kind=kind,
                          state=ConnectionState.NOT_CONNECTED)

    held = broker.held(f"{_TOKENS}.{provider}")
    if tokens.expired and not tokens.refreshable:
        return Connection(
            provider=provider, kind=kind,
            state=ConnectionState.AUTHENTICATION_REQUIRED,
            account=held.label if held else "",
            scopes=tokens.scopes, expires_at=tokens.expires_at,
            error="The session has expired and cannot be renewed.",
            remedy="Sign in again.")
    return Connection(
        provider=provider, kind=kind, state=ConnectionState.CONNECTED,
        account=held.label if held else "", scopes=tokens.scopes,
        expires_at=tokens.expires_at,
        connected_at=held.stored_at if held else "")


# ---------------------------------------------------------------- lifecycle
def connect_with_token(provider: str, token: str, *, account: str) -> Connection:
    """Store a token the user pasted in.

    The reason GitHub works with no application registration at all, and worth
    offering wherever a provider supports it: a personal access token is issued
    by the user to themselves, with scopes they chose, revocable from their own
    settings page.
    """
    if not token.strip():
        raise AuthError("No token was given.",
                        remedy="Paste the token from the provider's settings.")
    broker.store(f"{_TOKENS}.{provider}",
                 json.dumps(Tokens(access_token=token.strip()).to_storage()),
                 label=account or provider, kind="token")
    return status(provider, AuthKind.TOKEN, ProviderConfig(provider=provider),
                  account=account)


def store_oauth_result(provider: str, tokens: Tokens, *, account: str) -> Connection:
    _write_tokens(provider, tokens, account=account)
    return Connection(
        provider=provider, kind=AuthKind.OAUTH2_PKCE,
        state=ConnectionState.CONNECTED, account=account,
        scopes=tokens.scopes, expires_at=tokens.expires_at,
        connected_at=datetime.now(UTC).isoformat(timespec="seconds"))


def disconnect(provider: str, defaults: ProviderConfig, *, client=None) -> bool:
    """Sign out, and tell the provider if it will listen.

    Local state is cleared whether or not revocation succeeds. A disconnect
    that failed because the provider was unreachable, and therefore left the
    connection looking live, would be worse than one that tidied up locally.
    """
    tokens = _read_tokens(provider)
    if tokens is not None and client is not None:
        revoke(provider_config(provider, defaults), tokens, client=client)
    return broker.forget(f"{_TOKENS}.{provider}")


# ------------------------------------------------------------------ calling
def authorize(provider: str, kind: AuthKind, defaults: ProviderConfig,
              *, client_factory: Callable[[], object] | None = None) -> dict:
    """Headers that will authenticate a request, refreshing first if needed.

    Returns headers rather than a token, which is the whole point: an adapter
    written against this cannot leak a credential because it never holds one.
    """
    if kind is AuthKind.NONE:
        return {}

    # Reading and refreshing share the provider lock. Credential backends can
    # briefly remove the old value while replacing it; without this outer lock,
    # another caller can observe that tiny window as "not connected". The lock
    # is re-entrant because _renew also guards direct callers.
    with _lock_for(provider):
        tokens = _read_tokens(provider)
        if tokens is None:
            raise AuthError(
                f"{provider} is not connected.",
                remedy="Connect it in Settings → Integrations.",
                needs_reauthentication=True)

        if kind is not AuthKind.TOKEN and tokens.expired:
            tokens = _renew(provider, tokens, defaults,
                            client_factory=client_factory)

    return {"Authorization": f"{tokens.token_type} {tokens.access_token}"}


def _renew(provider: str, tokens: Tokens, defaults: ProviderConfig,
           *, client_factory: Callable[[], object] | None) -> Tokens:
    """Refresh, once, under a per-provider lock.

    Serialised because two requests noticing the same expiry would otherwise
    both refresh, and a provider that rotates refresh tokens invalidates the
    first when the second lands. The second read inside the lock is what makes
    the wait worth having: whoever arrives late finds the work already done.
    """
    with _lock_for(provider):
        current = _read_tokens(provider) or tokens
        if not current.expired:
            return current
        if not current.refreshable:
            raise AuthError(
                f"{provider} needs signing in to again.",
                remedy="Reconnect it in Settings → Integrations.",
                needs_reauthentication=True)

        config = provider_config(provider, defaults)
        flow = Flow(config, current.scopes,
                    secret_for=lambda: _client_secret(provider))
        client = client_factory() if client_factory else _default_client()
        renewed = flow.refresh(current, client=client)

        held = broker.held(f"{_TOKENS}.{provider}")
        _write_tokens(provider, renewed,
                      account=held.label if held else provider)
        return renewed


def _client_secret(provider: str) -> str:
    holder: dict = {}
    try:
        broker.open(f"{_SECRET}.{provider}",
                    lambda raw: holder.setdefault("raw", raw))
    except broker.NotConnected:
        return ""
    return holder.get("raw", "")


def _default_client():
    import httpx

    return httpx.Client(timeout=30.0)
