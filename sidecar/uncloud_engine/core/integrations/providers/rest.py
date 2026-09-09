"""What every REST provider adapter needs, so no adapter reinvents it.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Seven providers, one HTTP story. Without this each adapter grows its own idea
of what a 401 means, whether to retry a 429, and how to say "you did not grant
that scope" — and they diverge in exactly the ways that matter when something
fails at four in the afternoon.

**The client is injected.** Every adapter takes a factory, so the whole set is
testable against a stub without a network. That is not a convenience: the
interesting paths — an expired token, a rate limit, a revoked scope — are not
reachable against a real provider on demand.

**Errors are translated once, here.** A provider's 403 becomes either "you did
not grant this permission" or "that account cannot see this", because those
have different remedies and the raw status has neither.

**Nothing here holds a token.** Headers come from the connection layer at the
moment of the request, which is also when a refresh happens if one is due.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ...auth import AuthError, AuthKind, ProviderConfig, authorize
from ..contract import IntegrationError

#: How many times to retry a rate limit before giving up. Deliberately small:
#: an agent waiting two minutes on a retry loop has stopped being interactive,
#: and the honest answer is to say the provider is throttling.
MAX_RETRIES = 2

#: Longest to honour a Retry-After. Beyond this, telling the user is better
#: than blocking.
MAX_BACKOFF = 20.0


class Rest:
    """One provider's HTTP surface, with its failures already translated."""

    def __init__(self, provider: str, base_url: str, *,
                 kind: AuthKind = AuthKind.TOKEN,
                 defaults: ProviderConfig | None = None,
                 client_factory=None,
                 extra_headers: dict[str, str] | None = None) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.kind = kind
        self.defaults = defaults or ProviderConfig(provider=provider)
        self._client_factory = client_factory
        self._extra = dict(extra_headers or {})

    # ------------------------------------------------------------- plumbing
    def _client(self):
        if self._client_factory is not None:
            return self._client_factory()
        import httpx

        return httpx.Client(timeout=60.0)

    def _headers(self) -> dict[str, str]:
        """Authorisation for this request, refreshing first if it is due.

        Fetched per request rather than cached on the adapter, which is what
        makes an hour-old agent session keep working: the refresh happens here,
        invisibly, and nothing above ever holds a token.
        """
        try:
            headers = dict(authorize(self.provider, self.kind, self.defaults))
        except AuthError as exc:
            raise IntegrationError(
                exc.message, remedy=exc.remedy,
                needs_reconnect=exc.needs_reauthentication) from exc
        headers.setdefault("Accept", "application/json")
        headers.update(self._extra)
        return headers

    def request(self, method: str, path: str, *, params: dict | None = None,
                json_body: Any = None, expect_json: bool = True,
                absolute: bool = False) -> Any:
        """One call, with rate limits honoured and failures explained."""
        url = path if absolute else f"{self.base_url}/{path.lstrip('/')}"
        client = self._client()
        headers = self._headers()

        for attempt in range(MAX_RETRIES + 1):
            response = client.request(method, url, params=params,
                                      json=json_body, headers=headers)
            if response.status_code == 429 and attempt < MAX_RETRIES:
                delay = _retry_after(response)
                if delay <= MAX_BACKOFF:
                    time.sleep(delay)
                    continue
            if response.status_code >= 400:
                raise self._explain(response)
            if not expect_json or response.status_code == 204:
                return response.text
            try:
                return response.json()
            except ValueError:
                return response.text
        raise IntegrationError(
            f"{self.provider} is rate limiting and did not settle.",
            remedy="Wait a minute and try again.", retryable=True)

    def get(self, path: str, **kwargs) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> Any:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs) -> Any:
        return self.request("PATCH", path, **kwargs)

    def put(self, path: str, **kwargs) -> Any:
        return self.request("PUT", path, **kwargs)

    # --------------------------------------------------------------- errors
    def _explain(self, response) -> IntegrationError:
        """A status code turned into something a person can act on.

        The distinction that matters most is 401 against 403. One means sign in
        again; the other means you are signed in and this account cannot do
        that — often a scope nobody granted. Telling somebody to reconnect when
        the real answer is "ask your admin" wastes an afternoon.
        """
        detail = _detail(response)
        status = response.status_code

        if status == 401:
            return IntegrationError(
                f"{self.provider} did not accept the credentials. {detail}".strip(),
                remedy="Reconnect it in Settings → Integrations.",
                needs_reconnect=True)
        if status == 403:
            return IntegrationError(
                f"{self.provider} refused: {detail or 'access denied'}",
                remedy="This usually means a permission that was not granted "
                       "when you connected, or an account without access. "
                       "Reconnecting and approving the missing scope may fix "
                       "it; otherwise it is a permission on their side.")
        if status == 404:
            return IntegrationError(
                f"{self.provider} has nothing at that address. {detail}".strip(),
                remedy="Check the name or identifier.")
        if status == 429:
            return IntegrationError(
                f"{self.provider} is rate limiting.",
                remedy="Wait a minute and try again.", retryable=True)
        if status >= 500:
            return IntegrationError(
                f"{self.provider} had a server error ({status}).",
                remedy="Not something on this machine. Try again shortly.",
                retryable=True)
        return IntegrationError(
            f"{self.provider} refused the request ({status}): {detail}",
            remedy="Check the arguments.")


def _retry_after(response) -> float:
    raw = response.headers.get("Retry-After", "")
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 1.0


def _detail(response) -> str:
    """The useful sentence out of a provider's error body.

    Every one of them nests it somewhere different, and a raw JSON blob in a
    permission prompt or a chat reply is noise.
    """
    try:
        body = response.json()
    except (ValueError, AttributeError):
        return (getattr(response, "text", "") or "")[:200]

    if isinstance(body, dict):
        for key in ("message", "error_description", "error_summary", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value[:300]
        error = body.get("error")
        if isinstance(error, dict):
            for key in ("message", "status", "code"):
                value = error.get(key)
                if isinstance(value, str) and value:
                    return value[:300]
        elif isinstance(error, str) and error:
            return error[:300]
        if "errors" in body:
            return json.dumps(body["errors"])[:300]
    return json.dumps(body)[:300] if body else ""
