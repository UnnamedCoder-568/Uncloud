"""Authentication: PKCE, refresh, and the states that need different remedies.

No network anywhere. The token endpoint is a stub, which is what lets the
interesting paths — a rotated refresh token, a revoked grant, a mismatched
state parameter — be tested at all: none of them is reachable against a real
provider on demand.

The tests are mostly about refusing. An auth layer that guesses in the
permissive direction produces a connection that looks live and fails at the
moment somebody depends on it.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request

import pytest

from uncloud_engine.core.auth import (
    AuthError,
    AuthKind,
    ConnectionState,
    Flow,
    ProviderConfig,
    Tokens,
    connections,
)
from uncloud_engine.core.integrations import credentials as broker

CONFIG = ProviderConfig(
    provider="example", client_id="client-123",
    authorize_url="https://example.test/authorize",
    token_url="https://example.test/token",
    revoke_url="https://example.test/revoke")


class Response:
    def __init__(self, status: int, body: dict | None = None, text: str = "") -> None:
        self.status_code = status
        self._body = body
        self.text = text or json.dumps(body or {})

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


class Client:
    """A token endpoint that answers however the test needs it to."""

    def __init__(self, *responses: Response) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url, data=None, headers=None):
        self.calls.append(dict(data or {}))
        return self._responses.pop(0) if len(self._responses) > 1 \
            else self._responses[0]


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Never the real keychain, and never the developer's own state."""
    monkeypatch.setattr(broker, "_keyring", lambda: None)
    monkeypatch.setattr(broker, "_DIRECTORY", tmp_path)
    yield


# ------------------------------------------------------------------- PKCE
def test_the_verifier_never_appears_in_the_authorisation_url() -> None:
    """The whole point of PKCE. What goes to the provider is the hash, so an
    intercepted authorisation code cannot be redeemed by whoever took it."""
    attempt = Flow(CONFIG, ("read",)).begin(port=51999)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(attempt.authorize_url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert attempt.verifier not in attempt.authorize_url
    assert query["code_challenge"][0] != attempt.verifier


def test_the_redirect_is_loopback_rather_than_a_server_of_ours() -> None:
    """A hosted callback would route somebody's authorisation code through us."""
    attempt = Flow(CONFIG, ("read",)).begin(port=51998)
    assert attempt.redirect_uri.startswith("http://127.0.0.1:")


def test_every_attempt_gets_a_fresh_verifier_and_state() -> None:
    flow = Flow(CONFIG, ("read",))
    first, second = flow.begin(port=51997), flow.begin(port=51996)
    assert first.verifier != second.verifier
    assert first.state != second.state


def test_an_unconfigured_provider_refuses_before_opening_a_browser() -> None:
    """NOT_CONFIGURED is a real state with a real remedy, and the remedy is not
    something Uncloud can do on the user's behalf."""
    with pytest.raises(AuthError) as raised:
        Flow(ProviderConfig(provider="example"), ("read",))
    assert raised.value.needs_configuration is True
    assert "cannot supply one" in raised.value.remedy


# -------------------------------------------------------------- the redirect
def _visit(url: str) -> None:
    try:
        urllib.request.urlopen(url, timeout=5).read()
    except Exception:  # noqa: BLE001 - the assertion is on the flow, not this
        pass


def test_the_code_comes_back_through_the_loopback_listener() -> None:
    flow = Flow(CONFIG, ("read",))
    attempt = flow.begin(port=51995)
    threading.Timer(0.3, _visit, args=[
        f"{attempt.redirect_uri}?code=abc123&state={attempt.state}"]).start()
    assert flow.await_redirect(attempt, timeout=10) == "abc123"


def test_a_mismatched_state_is_fatal() -> None:
    """The only thing standing between this flow and a code injected by another
    page."""
    flow = Flow(CONFIG, ("read",))
    attempt = flow.begin(port=51994)
    threading.Timer(0.3, _visit, args=[
        f"{attempt.redirect_uri}?code=abc123&state=not-the-one"]).start()
    with pytest.raises(AuthError) as raised:
        flow.await_redirect(attempt, timeout=10)
    assert "did not match" in str(raised.value)


def test_a_refusal_from_the_provider_is_reported_as_theirs() -> None:
    flow = Flow(CONFIG, ("read",))
    attempt = flow.begin(port=51993)
    threading.Timer(0.3, _visit, args=[
        f"{attempt.redirect_uri}?error=access_denied"
        f"&error_description=User+said+no&state={attempt.state}"]).start()
    with pytest.raises(AuthError) as raised:
        flow.await_redirect(attempt, timeout=10)
    assert "User said no" in str(raised.value)


# ------------------------------------------------------------------ exchange
def test_an_exchange_returns_tokens_and_records_what_was_granted() -> None:
    """What was GRANTED, not what was asked for. An integration that assumes it
    got every scope it requested fails later, confusingly."""
    flow = Flow(CONFIG, ("read", "write"))
    attempt = flow.begin(port=51992)
    client = Client(Response(200, {
        "access_token": "at", "refresh_token": "rt",
        "expires_in": 3600, "scope": "read"}))
    tokens = flow.exchange(attempt, "code", client=client)
    assert tokens.scopes == ("read",)
    assert client.calls[0]["code_verifier"] == attempt.verifier
    assert client.calls[0]["grant_type"] == "authorization_code"


def test_a_provider_that_returns_no_token_is_an_error_not_an_empty_session() -> None:
    flow = Flow(CONFIG, ("read",))
    attempt = flow.begin(port=51991)
    with pytest.raises(AuthError):
        flow.exchange(attempt, "code", client=Client(Response(200, {"ok": True})))


def test_invalid_grant_asks_for_a_person_rather_than_a_retry() -> None:
    """Telling somebody to retry a revoked token is how support tickets get
    long."""
    flow = Flow(CONFIG, ("read",))
    client = Client(Response(400, {"error": "invalid_grant",
                                   "error_description": "Token revoked"}))
    with pytest.raises(AuthError) as raised:
        flow.refresh(Tokens(access_token="a", refresh_token="r"), client=client)
    assert raised.value.needs_reauthentication is True


# ------------------------------------------------------------------- refresh
def test_a_refresh_that_returns_no_new_refresh_token_keeps_the_old_one() -> None:
    """Most providers do not rotate. Dropping it would turn a working
    connection into one that silently expires for good."""
    flow = Flow(CONFIG, ("read",))
    renewed = flow.refresh(
        Tokens(access_token="old", refresh_token="keep-me"),
        client=Client(Response(200, {"access_token": "new", "expires_in": 3600})))
    assert renewed.access_token == "new"
    assert renewed.refresh_token == "keep-me"


def test_a_token_with_no_refresh_cannot_be_renewed_silently() -> None:
    flow = Flow(CONFIG, ("read",))
    with pytest.raises(AuthError) as raised:
        flow.refresh(Tokens(access_token="a"), client=Client(Response(200, {})))
    assert raised.value.needs_reauthentication is True


def test_expiry_is_judged_early_enough_to_survive_the_request() -> None:
    """A token that expires mid-flight produces a failure that looks like a bug
    in the integration, and the provider's clock is not ours."""
    assert Tokens(access_token="a", expires_at=time.time() + 30).expired is True
    assert Tokens(access_token="a", expires_at=time.time() + 600).expired is False
    assert Tokens(access_token="a").expired is False   # no expiry stated


def test_refreshing_happens_once_when_several_callers_notice_at_the_same_time(
        monkeypatch) -> None:
    """A provider that rotates refresh tokens invalidates the first when the
    second lands — turning a working connection into a broken one under load,
    which is the worst possible time."""
    connections.configure_provider(CONFIG)
    connections._write_tokens(
        "example",
        Tokens(access_token="old", refresh_token="rt", expires_at=time.time() - 1),
        account="someone@example.test")

    refreshes = []

    def client_factory():
        refreshes.append(1)
        return Client(Response(200, {"access_token": f"new-{len(refreshes)}",
                                     "expires_in": 3600}))

    results, errors = [], []

    def call():
        try:
            results.append(connections.authorize(
                "example", AuthKind.OAUTH2_PKCE, CONFIG,
                client_factory=client_factory))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=call) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert len(refreshes) == 1, f"refreshed {len(refreshes)} times"
    assert len({tuple(sorted(r.items())) for r in results}) == 1


# --------------------------------------------------------------------- state
def test_the_five_states_are_distinguished_because_the_remedies_differ() -> None:
    defaults = ProviderConfig(provider="example")

    unconfigured = connections.status("example", AuthKind.OAUTH2_PKCE, defaults)
    assert unconfigured.state is ConnectionState.NOT_CONFIGURED
    assert "Register an OAuth application" in unconfigured.remedy

    connections.configure_provider(CONFIG)
    assert connections.status("example", AuthKind.OAUTH2_PKCE, CONFIG).state \
        is ConnectionState.NOT_CONNECTED

    connections._write_tokens("example",
                              Tokens(access_token="a", expires_at=time.time() + 999),
                              account="someone@example.test")
    live = connections.status("example", AuthKind.OAUTH2_PKCE, CONFIG)
    assert live.state is ConnectionState.CONNECTED
    assert live.account == "someone@example.test"

    connections._write_tokens("example",
                              Tokens(access_token="a", expires_at=time.time() - 1),
                              account="someone@example.test")
    stale = connections.status("example", AuthKind.OAUTH2_PKCE, CONFIG)
    assert stale.state is ConnectionState.AUTHENTICATION_REQUIRED
    assert stale.remedy == "Sign in again."


def test_asking_for_status_never_touches_the_network(monkeypatch) -> None:
    """A settings page that made a token request per row would be slow, burn
    rate limit, and refresh tokens as a side effect of being looked at."""
    def explode():
        raise AssertionError("status() built an HTTP client")

    monkeypatch.setattr(connections, "_default_client", explode)
    connections.configure_provider(CONFIG)
    connections._write_tokens("example",
                              Tokens(access_token="a", expires_at=time.time() - 1,
                                     refresh_token="r"),
                              account="someone@example.test")
    assert connections.status("example", AuthKind.OAUTH2_PKCE, CONFIG).state \
        is ConnectionState.CONNECTED


# ----------------------------------------------------------------- lifecycle
def test_a_pasted_token_connects_without_any_application_registration() -> None:
    """The reason GitHub works out of the box and Google cannot."""
    connection = connections.connect_with_token("github", "ghp_abc", account="octocat")
    assert connection.state is ConnectionState.CONNECTED
    assert connection.account == "octocat"


def test_disconnecting_clears_local_state_even_when_the_provider_is_down() -> None:
    """A disconnect that failed because the provider was unreachable, and left
    the connection looking live, would be worse than one that tidied up."""
    connections.connect_with_token("github", "ghp_abc", account="octocat")

    class Broken:
        def post(self, *a, **k):
            raise OSError("network is down")

    assert connections.disconnect("github", ProviderConfig(provider="github"),
                                  client=Broken()) is True
    assert connections.status("github", AuthKind.TOKEN,
                              ProviderConfig(provider="github")).state \
        is ConnectionState.NOT_CONNECTED


def test_reconnecting_restores_a_usable_connection() -> None:
    config = ProviderConfig(provider="github")
    connections.connect_with_token("github", "ghp_one", account="octocat")
    connections.disconnect("github", config)
    connections.connect_with_token("github", "ghp_two", account="octocat")
    assert connections.status("github", AuthKind.TOKEN, config).state \
        is ConnectionState.CONNECTED


# ------------------------------------------------------------------- secrets
def test_an_adapter_is_given_headers_rather_than_a_token() -> None:
    """The same guarantee the credential broker makes: an adapter written
    against this cannot leak a credential because it never holds one."""
    connections.connect_with_token("github", "ghp_secret_value", account="octocat")
    headers = connections.authorize("github", AuthKind.TOKEN,
                                    ProviderConfig(provider="github"))
    assert headers == {"Authorization": "Bearer ghp_secret_value"}
    assert set(headers) == {"Authorization"}


def test_the_client_id_is_readable_but_the_secret_is_not(tmp_path) -> None:
    """A client ID appears in every authorisation URL and has to be displayable;
    hiding it would mean an unlock prompt to draw a settings page. A secret is
    a secret."""
    connections.configure_provider(
        ProviderConfig(provider="example", client_id="visible-id",
                       has_secret=True, authorize_url="https://a", token_url="https://t"),
        client_secret="hidden-value")
    assert connections.provider_config("example", CONFIG).client_id == "visible-id"
    index = json.loads((tmp_path / "integrations.json").read_text())
    assert "hidden-value" not in json.dumps(index["index"])


def test_a_connection_object_carries_no_credential() -> None:
    connections.connect_with_token("github", "ghp_secret", account="octocat")
    shown = connections.status("github", AuthKind.TOKEN,
                               ProviderConfig(provider="github")).to_dict()
    assert "ghp_secret" not in json.dumps(shown)
    assert not any("token" in key for key in shown)
