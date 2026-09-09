"""Authentication and connection state, provider-agnostic.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Three things kept apart, because conflating them is why "reconnect it" becomes
the only advice support can give:

* the OAuth client, registered by whoever publishes the build;
* this person's tokens;
* what the agent may do with them, which is the permission gate's question and
  is not answered anywhere in this package.

**Uncloud ships no provider credentials.** An OAuth client is issued to a named
party under a provider's terms, and fabricating one would be both a lie and a
violation. `NOT_CONFIGURED` is a real, displayable state, and the software's
job is to make configuring your own straightforward.
"""

from .connections import (
    authorize,
    configure_provider,
    connect_with_token,
    disconnect,
    forget_provider_config,
    provider_config,
    status,
    store_oauth_result,
)
from .contract import (
    AuthError,
    AuthKind,
    Connection,
    ConnectionState,
    ProviderConfig,
    Scope,
    Tokens,
)
from .oauth import Attempt, Flow, revoke

__all__ = [
    "Attempt", "AuthError", "AuthKind", "Connection", "ConnectionState",
    "Flow", "ProviderConfig", "Scope", "Tokens", "authorize",
    "configure_provider", "connect_with_token", "disconnect",
    "forget_provider_config", "provider_config", "revoke", "status",
    "store_oauth_result",
]
