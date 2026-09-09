"""OAuth 2.0 for a desktop application, done the way RFC 8252 says to.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Authorisation code with PKCE, over a loopback redirect. That combination is the
one that works without shipping a client secret, which matters here more than
usual: a desktop application's binary is on the user's disk, so any secret
inside it is not a secret. PKCE replaces it with a per-attempt challenge that
never leaves the machine.

Four decisions worth stating.

**The redirect is 127.0.0.1 on an ephemeral port.** Not a custom URL scheme,
which requires registration and behaves differently on every platform, and not
a hosted callback, which would route somebody's authorisation code through a
server of ours. The listener exists for one request and then stops.

**`state` is checked, and a mismatch is fatal.** It is the only thing standing
between this flow and a code injected by another page. Comparing it in constant
time costs nothing and the failure mode is silent.

**No secret is returned to anything upstream.** `exchange` and `refresh` hand
tokens to the caller-supplied store and return a `Connection`. As in the
credential broker, the guarantee is absence rather than redaction.

**Providers are data.** Google wants `access_type=offline`; Microsoft wants a
tenant in the path; Slack puts its scopes in a different parameter. All of that
is `ProviderConfig`, so a provider quirk never becomes a branch in this file.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import secrets
import socket
import threading
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field

from .contract import AuthError, ProviderConfig, Tokens

#: How long to wait for somebody to finish signing in before giving up. Long
#: enough for a password manager and a two-factor prompt; short enough that a
#: forgotten browser tab does not hold a socket open all afternoon.
CONSENT_TIMEOUT = 300.0


def _challenge() -> tuple[str, str]:
    """A PKCE verifier and its S256 challenge.

    The verifier never leaves this machine. What goes to the provider is its
    hash, so an authorisation code intercepted in transit cannot be redeemed by
    whoever intercepted it.
    """
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@dataclass
class Attempt:
    """One sign-in in progress.

    Held for the length of the flow and then discarded. The verifier is the
    reason it has to be held at all: it is generated before the browser opens
    and needed after the redirect comes back.
    """

    provider: str
    verifier: str
    state: str
    redirect_uri: str
    scopes: tuple[str, ...]
    authorize_url: str
    started_at: float = field(default_factory=time.time)


class _Callback(http.server.BaseHTTPRequestHandler):
    """The one request the loopback listener exists for."""

    result: dict = {}

    def do_GET(self) -> None:  # noqa: N802 - http.server's interface
        query = urllib.parse.urlparse(self.path).query
        parsed = urllib.parse.parse_qs(query)
        _Callback.result = {k: v[0] for k, v in parsed.items()}

        ok = "code" in _Callback.result
        heading = "Connected" if ok else "Not connected"
        message = ("You can close this tab and go back to Uncloud."
                   if ok else
                   "Uncloud did not receive an authorisation code. "
                   "Close this tab and try again.")
        body = (
            "<!doctype html><meta charset=utf-8><title>Uncloud</title>"
            "<style>body{font:16px system-ui;margin:0;height:100vh;display:grid;"
            "place-items:center;background:#0b0b0e;color:#e8e8ea}"
            "div{text-align:center;max-width:32ch;line-height:1.6}</style>"
            f"<div><h2>{heading}</h2><p>{message}</p></div>"
        ).encode()

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        """Silence. The default writes every request to stderr, and this one
        carries an authorisation code in its query string."""


class Flow:
    """An OAuth sign-in, from opening a browser to storing tokens."""

    def __init__(self, config: ProviderConfig, scopes: tuple[str, ...],
                 *, secret_for: Callable[[], str] | None = None) -> None:
        if not config.configured:
            raise AuthError(
                f"{config.provider} has no OAuth client configured.",
                remedy=(f"Register an application with {config.provider} and "
                        f"enter its client ID in Settings → Integrations. "
                        f"Uncloud cannot supply one: an OAuth client is issued "
                        f"to a named party under the provider's terms."),
                needs_configuration=True)
        self.config = config
        self.scopes = scopes
        # A callable rather than a value, so the secret is fetched at the
        # moment of the exchange and is not held on this object in between.
        self._secret_for = secret_for

    # ------------------------------------------------------------- step one
    def begin(self, *, port: int | None = None) -> Attempt:
        """Build the authorisation URL. Nothing has been sent yet."""
        verifier, challenge = _challenge()
        state = secrets.token_urlsafe(32)
        chosen = port or _free_port()
        redirect_uri = f"http://127.0.0.1:{chosen}/callback"

        parameters: dict[str, str] = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": " ".join(self.scopes),
            **self.config.extra_authorize,
        }
        url = (self.config.authorize_url + "?"
               + urllib.parse.urlencode(parameters, quote_via=urllib.parse.quote))
        return Attempt(provider=self.config.provider, verifier=verifier,
                       state=state, redirect_uri=redirect_uri,
                       scopes=self.scopes, authorize_url=url)

    # ------------------------------------------------------------- step two
    def await_redirect(self, attempt: Attempt, *,
                       timeout: float = CONSENT_TIMEOUT) -> str:
        """Serve exactly one request and return the authorisation code.

        The listener is created here rather than in `begin` so that a flow
        abandoned before the browser opens leaves no socket behind.
        """
        port = int(urllib.parse.urlparse(attempt.redirect_uri).port or 0)
        _Callback.result = {}
        server = http.server.HTTPServer(("127.0.0.1", port), _Callback)
        server.timeout = timeout

        done = threading.Event()

        def serve() -> None:
            server.handle_request()
            done.set()

        threading.Thread(target=serve, daemon=True).start()
        if not done.wait(timeout):
            server.server_close()
            raise AuthError(
                "Timed out waiting for sign-in to finish.",
                remedy="Try again, and complete the sign-in in the browser "
                       "window that opens.")
        server.server_close()

        result = dict(_Callback.result)
        _Callback.result = {}

        if "error" in result:
            described = result.get("error_description") or result["error"]
            raise AuthError(
                f"{self.config.provider} refused the sign-in: {described}",
                remedy="Check that the redirect URI below is registered with "
                       "the provider, and that the account has access.")
        # Constant time, because the comparison is the only thing standing
        # between this flow and a code injected by another page.
        if not secrets.compare_digest(result.get("state", ""), attempt.state):
            raise AuthError(
                "The sign-in response did not match the request.",
                remedy="Start again. If it keeps happening, something is "
                       "interfering with the callback.")
        code = result.get("code", "")
        if not code:
            raise AuthError("No authorisation code came back.",
                            remedy="Start again.")
        return code

    # ----------------------------------------------------------- step three
    def exchange(self, attempt: Attempt, code: str, *, client) -> Tokens:
        """Trade the code for tokens.

        `client` is injected rather than constructed so the exchange can be
        tested against a stub without a network, and so a product can supply
        its own timeout and proxy settings.
        """
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": attempt.redirect_uri,
            "client_id": self.config.client_id,
            "code_verifier": attempt.verifier,
        }
        if self.config.has_secret and self._secret_for is not None:
            payload["client_secret"] = self._secret_for()
        return self._token_request(payload, client=client,
                                   fallback_scopes=attempt.scopes)

    def refresh(self, tokens: Tokens, *, client) -> Tokens:
        """Renew an access token without asking anybody anything.

        A provider that returns no new refresh token has not revoked the old
        one — most do not rotate — so the existing one is carried forward. A
        refresh that dropped it would turn a working connection into one that
        silently expires for good.
        """
        if not tokens.refreshable:
            raise AuthError(
                "This connection cannot be renewed without signing in again.",
                remedy="Reconnect the integration.",
                needs_reauthentication=True)
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
            "client_id": self.config.client_id,
        }
        if self.config.has_secret and self._secret_for is not None:
            payload["client_secret"] = self._secret_for()
        renewed = self._token_request(payload, client=client,
                                      fallback_scopes=tokens.scopes)
        if not renewed.refresh_token:
            renewed.refresh_token = tokens.refresh_token
        return renewed

    # ------------------------------------------------------------- plumbing
    def _token_request(self, payload: dict, *, client,
                       fallback_scopes: tuple[str, ...]) -> Tokens:
        response = client.post(
            self.config.token_url, data=payload,
            headers={"Accept": "application/json"})
        if response.status_code >= 400:
            raise self._token_error(response)
        try:
            body = response.json()
        except ValueError as exc:
            raise AuthError(
                f"{self.config.provider} returned something that was not a "
                f"token response.",
                remedy="Check the token URL in the provider configuration.",
            ) from exc

        access = body.get("access_token")
        if not access:
            raise AuthError(
                f"{self.config.provider} did not return an access token.",
                remedy="Check the client ID and the requested scopes.")

        expires_in = body.get("expires_in")
        # Scopes come back space-delimited when the provider narrowed them.
        # What was GRANTED matters more than what was asked for: an integration
        # that assumes it got everything fails later, confusingly.
        granted = body.get("scope") or ""
        return Tokens(
            access_token=access,
            refresh_token=body.get("refresh_token") or "",
            expires_at=(time.time() + float(expires_in)) if expires_in else 0.0,
            scopes=tuple(granted.split()) if granted else fallback_scopes,
            token_type=body.get("token_type") or "Bearer")

    def _token_error(self, response) -> AuthError:
        """A provider's refusal, translated into something actionable."""
        try:
            body = response.json()
        except ValueError:
            body = {}
        code = str(body.get("error") or "")
        described = str(body.get("error_description") or "") or response.text[:300]

        # `invalid_grant` is the one that matters: the refresh token is gone,
        # revoked, or the account changed. It needs a person, and telling them
        # to retry would be wrong.
        if code in {"invalid_grant", "unauthorized_client", "invalid_client"}:
            return AuthError(
                f"{self.config.provider} rejected the credentials: "
                f"{described or code}",
                remedy="Sign in again.", needs_reauthentication=True)
        return AuthError(
            f"{self.config.provider} refused the token request "
            f"({response.status_code}): {described or code}",
            remedy="Check the provider configuration and try again.")


def revoke(config: ProviderConfig, tokens: Tokens, *, client) -> bool:
    """Tell the provider to forget these tokens.

    Best effort, and deliberately so: local state is cleared whether or not
    this succeeds. A disconnect that failed because the provider was down, and
    therefore left the connection looking live, would be worse than one that
    tidied up locally and could not reach them.
    """
    if not config.revoke_url:
        return False
    try:
        response = client.post(
            config.revoke_url,
            data={"token": tokens.refresh_token or tokens.access_token,
                  "client_id": config.client_id},
            headers={"Accept": "application/json"})
        return response.status_code < 400
    except Exception:  # noqa: BLE001 - the local disconnect happens regardless
        return False
