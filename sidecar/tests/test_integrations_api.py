"""The integration surface over HTTP, including the six displayable states.

The states are the point. "Not working" has six different remedies here, and
an interface that collapsed them would send somebody to reconnect an account
when the real answer is that nobody has registered an OAuth client.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uncloud_engine.core.integrations import credentials as broker


class _Client:
    """A TestClient with the credential store redirected.

    Redirected because these tests WRITE connections, and a run that stored a
    token in the developer's own keychain would be both surprising and hard to
    notice.
    """

    def __init__(self, tmp_path: Path) -> None:
        self._tmp = tmp_path

    def __enter__(self):
        from fastapi.testclient import TestClient

        from uncloud_engine import main

        self.main = main
        _Client.main = main
        self._saved_dir = broker._DIRECTORY
        self._saved_ring = broker._keyring
        broker._DIRECTORY = self._tmp
        broker._keyring = lambda: None
        self._saved_policy = dict(main.gate.policy)

        self.client = TestClient(main.app)
        self.client.headers.update(
            {"Authorization": f"Bearer {main.settings.token}"})
        return self.client

    def __exit__(self, *exc):
        broker._DIRECTORY = self._saved_dir
        broker._keyring = self._saved_ring
        self.main.gate.policy.update(self._saved_policy)
        self.main.gate.forget_session()


def states(payload: dict) -> dict[str, str]:
    return {i["id"]: i["connection"]["state"] for i in payload["integrations"]}


# ------------------------------------------------------------------- listing
def test_every_integration_reports_a_state_and_its_capabilities(tmp_path) -> None:
    with _Client(tmp_path) as client:
        payload = client.get("/api/integrations").json()

    found = states(payload)
    assert {"documents", "github", "google", "microsoft", "slack", "notion",
            "dropbox"} <= set(found)
    assert payload["capabilities"]["email.send"] == ["google", "microsoft"]
    assert payload["capabilities"]["code.issue.create"] == ["github"]
    # Nothing is connected on a fresh install, so nothing is routable yet.
    assert payload["connected_capabilities"] == {}


def test_the_states_that_need_different_remedies_are_distinguished(tmp_path) -> None:
    with _Client(tmp_path) as client:
        found = states(client.get("/api/integrations").json())

    # An OAuth client nobody registered. The remedy is not something Uncloud
    # can do, and saying "not connected" would send somebody looking for a
    # sign-in button that cannot work yet.
    assert found["google"] == "not_configured"
    assert found["microsoft"] == "not_configured"
    # A token nobody has pasted. The remedy is a paste.
    assert found["github"] == "not_connected"
    # A folder nobody has chosen.
    assert found["documents"] == "not_connected"


def test_listing_never_touches_the_network(tmp_path, monkeypatch) -> None:
    """A settings page that made a token request per row would be slow, burn
    rate limit, and refresh tokens as a side effect of being looked at.

    Patched at the outbound seam rather than at httpx, because the test client
    itself speaks httpx — an earlier version of this test failed by breaking
    the thing making the request rather than the thing under test.
    """
    from uncloud_engine.core.auth import connections
    from uncloud_engine.core.integrations.providers import dropbox, microsoft

    def explode():
        raise AssertionError("listing built an outbound HTTP client")

    for module in (connections, dropbox, microsoft):
        monkeypatch.setattr(module, "_default_client", explode)

    with _Client(tmp_path) as client:
        assert client.get("/api/integrations").status_code == 200


# ---------------------------------------------------------------- connecting
def test_a_token_connects_and_the_token_never_comes_back(tmp_path) -> None:
    with _Client(tmp_path) as client:
        payload = client.post("/api/integrations/connect", json={
            "integration_id": "github", "secret": "ghp_secret_value",
            "label": "octocat"}).json()

    assert states(payload)["github"] == "connected"
    assert "ghp_secret_value" not in json.dumps(payload)


def test_a_folder_connects_without_a_credential(tmp_path) -> None:
    folder = tmp_path / "papers"
    folder.mkdir()
    with _Client(tmp_path) as client:
        payload = client.post("/api/integrations/connect", json={
            "integration_id": "documents", "label": str(folder)}).json()

    assert states(payload)["documents"] == "connected"
    assert payload["connected_capabilities"]["storage.file.read"] == ["documents"]


def test_connecting_without_what_is_needed_is_refused(tmp_path) -> None:
    with _Client(tmp_path) as client:
        assert client.post("/api/integrations/connect", json={
            "integration_id": "github"}).status_code == 400
        assert client.post("/api/integrations/connect", json={
            "integration_id": "documents"}).status_code == 400
        assert client.post("/api/integrations/connect", json={
            "integration_id": "invented"}).status_code == 404


def test_configuring_an_oauth_client_moves_it_out_of_not_configured(tmp_path) -> None:
    with _Client(tmp_path) as client:
        payload = client.post("/api/integrations/configure", json={
            "integration_id": "google", "client_id": "1234.apps.example"}).json()

    assert states(payload)["google"] == "not_connected"


def test_a_client_secret_is_not_readable_afterwards(tmp_path) -> None:
    with _Client(tmp_path) as client:
        payload = client.post("/api/integrations/configure", json={
            "integration_id": "microsoft", "client_id": "abc",
            "client_secret": "s3cret-value"}).json()

    assert "s3cret-value" not in json.dumps(payload)
    stored = json.loads((tmp_path / "integrations.json").read_text())
    assert "s3cret-value" not in json.dumps(stored["index"])


def test_configuring_something_that_does_not_use_oauth_is_refused(tmp_path) -> None:
    with _Client(tmp_path) as client:
        assert client.post("/api/integrations/configure", json={
            "integration_id": "documents", "client_id": "x"}).status_code == 404


def test_disconnecting_and_reconnecting_recovers_the_state(tmp_path) -> None:
    with _Client(tmp_path) as client:
        client.post("/api/integrations/connect", json={
            "integration_id": "github", "secret": "one", "label": "octocat"})
        payload = client.post("/api/integrations/disconnect",
                              json={"integration_id": "github"}).json()
        assert states(payload)["github"] == "not_connected"

        payload = client.post("/api/integrations/connect", json={
            "integration_id": "github", "secret": "two", "label": "octocat"}).json()
        assert states(payload)["github"] == "connected"


def test_disconnecting_can_also_forget_the_oauth_client(tmp_path) -> None:
    """Signing out and un-registering the application are different intentions,
    and doing both by default would make somebody re-enter a client ID every
    time they signed out."""
    with _Client(tmp_path) as client:
        client.post("/api/integrations/configure", json={
            "integration_id": "google", "client_id": "1234.apps.example"})

        payload = client.post("/api/integrations/disconnect",
                              json={"integration_id": "google"}).json()
        assert states(payload)["google"] == "not_connected", "still configured"

        payload = client.post("/api/integrations/disconnect", json={
            "integration_id": "google", "label": "forget-configuration"}).json()
        assert states(payload)["google"] == "not_configured"


# ----------------------------------------------------------------------- MCP
@pytest.fixture
def settings_allowed():
    """MCP configuration is a settings action, and is asked about. These tests
    are about the storage and lifecycle, so the decision is pre-granted."""
    from uncloud_engine import main
    from uncloud_engine.core import Mode, Risk

    before = main.gate.mode_for(Risk.SETTINGS)
    main.gate.set_mode(Risk.SETTINGS, Mode.ALLOW)
    yield
    main.gate.set_mode(Risk.SETTINGS, before)


def test_an_mcp_server_can_be_added_listed_and_forgotten(tmp_path,
                                                         settings_allowed) -> None:
    with _Client(tmp_path) as client:
        listed = client.post("/api/mcp", json={
            "id": "notes", "command": "/usr/bin/true", "label": "Notes"}).json()
        assert [s["mcp"]["config"]["id"] for s in listed] == ["notes"]

        after = client.request("DELETE", "/api/mcp/notes").json()
        assert after == []


def test_an_mcp_environment_variable_is_not_readable_afterwards(
        tmp_path, settings_allowed) -> None:
    with _Client(tmp_path) as client:
        listed = client.post("/api/mcp", json={
            "id": "notes", "command": "/usr/bin/true",
            "env": {"API_KEY": "sk-secret"}}).json()

    body = json.dumps(listed)
    assert "sk-secret" not in body
    assert "API_KEY" in body, "the NAME is useful and is not the secret"


def test_starting_someone_elses_program_is_a_settings_decision(tmp_path) -> None:
    """Before the process exists, not after."""
    from uncloud_engine import main
    from uncloud_engine.core import Mode, Risk

    with _Client(tmp_path) as client:
        main.gate.set_mode(Risk.SETTINGS, Mode.ALLOW)
        client.post("/api/mcp", json={"id": "notes", "command": "/usr/bin/true"})
        main.gate.set_mode(Risk.SETTINGS, Mode.ASK)
        main.gate.forget_session()
        response = client.post("/api/mcp/notes/connect")

    assert response.status_code == 428
    assert response.json()["detail"]["approval"]["category"] == "settings"


def test_connecting_an_unknown_server_is_a_404(tmp_path) -> None:
    with _Client(tmp_path) as client:
        assert client.post("/api/mcp/nope/connect").status_code == 404
