"""Provider adapters, driven end to end against a stub transport.

The lifecycle the brief asks for — connect, discover, read, write, permission,
approval, approve, verify one execution, deny, verify none, disconnect,
reconnect, verify recovery — run here for real. What is stubbed is HTTP and
nothing else: the adapters build the same requests they would send to
api.github.com, and the assertions are on those requests.

That is a deliberate line. A suite needing somebody's GitHub account is one
that fails on every other machine and gets deleted; a suite that mocks the
ADAPTER proves nothing. So the seam is the socket.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from uncloud_engine.core.auth import AuthKind, ProviderConfig, connections
from uncloud_engine.core.integrations import credentials as broker
from uncloud_engine.core.integrations import registry
from uncloud_engine.core.integrations.providers import (
    Dropbox,
    GitHub,
    Google,
    Microsoft,
    Notion,
    Slack,
)


class Reply:
    def __init__(self, body, status: int = 200, headers: dict | None = None) -> None:
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.content = self.text.encode("utf-8")

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class Transport:
    """Records every request and answers from a routing table.

    Matching is on `method path-substring`, because asserting on a whole URL
    makes a test fail when a query parameter is added, which is not the change
    anybody wanted to be told about.
    """

    def __init__(self, routes: dict[str, object] | None = None) -> None:
        self.routes = dict(routes or {})
        self.calls: list[dict] = []

    def request(self, method, url, params=None, json=None, headers=None,
                content=None, follow_redirects=False):
        self.calls.append({"method": method, "url": url, "params": params or {},
                           "json": json, "headers": headers or {},
                           "content": content})
        for pattern, reply in self.routes.items():
            wanted_method, _, fragment = pattern.partition(" ")
            if method.upper() == wanted_method.upper() and fragment in url:
                return reply if isinstance(reply, Reply) else Reply(reply)
        return Reply({"message": f"no stub for {method} {url}"}, status=404)

    def post(self, url, data=None, headers=None):
        return self.request("POST", url, json=data, headers=headers)

    def last(self) -> dict:
        return self.calls[-1]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Never the real keychain, never the developer's own connections."""
    monkeypatch.setattr(broker, "_keyring", lambda: None)
    monkeypatch.setattr(broker, "_DIRECTORY", tmp_path)
    yield


@pytest.fixture
def approve_everything(monkeypatch):
    decisions = []

    async def allow(request):
        decisions.append(request)
        return None

    monkeypatch.setattr(registry, "_ASK", allow)
    return decisions


def connected(provider: str, token: str = "t0ken", account: str = "someone"):
    connections.connect_with_token(provider, token, account=account)


# ============================================================ GitHub
def github(routes: dict) -> tuple[GitHub, Transport]:
    transport = Transport(routes)
    connected("github", account="octocat")
    return GitHub(client_factory=lambda: transport), transport


def test_github_connects_with_a_token_and_reports_the_account() -> None:
    """No application registration anywhere in this path — the reason GitHub is
    IMPLEMENTED rather than REQUIRES EXTERNAL CONFIGURATION."""
    adapter, _ = github({"GET /user": {"login": "octocat"}})
    assert adapter.whoami() == "octocat"
    assert adapter.connection().state.value == "connected"


def test_github_sends_the_token_and_the_api_version() -> None:
    """Without the version header, response shapes drift under you over months
    rather than failing loudly."""
    adapter, transport = github({"GET /user/repos": [
        {"full_name": "octocat/Hello", "private": False, "description": "hi"}]})
    asyncio.run(adapter.run("github.repos", {}))
    headers = transport.last()["headers"]
    assert headers["Authorization"] == "Bearer t0ken"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"


def test_github_reads_a_file_and_decodes_it() -> None:
    import base64

    content = base64.b64encode(b"hello from the repo").decode()
    adapter, _ = github({"GET /repos/octocat/Hello/contents/README.md": {
        "encoding": "base64", "content": content}})
    result = asyncio.run(adapter.run("github.read_file",
                                     {"repo": "octocat/Hello",
                                      "path": "README.md"}))
    assert result == "hello from the repo"


def test_github_leaves_pull_requests_out_of_the_issue_list() -> None:
    """GitHub returns PRs from the issues endpoint. Leaving them in makes
    "list the issues" quietly wrong."""
    adapter, _ = github({"GET /repos/octocat/Hello/issues": [
        {"number": 1, "title": "A bug", "state": "open"},
        {"number": 2, "title": "A change", "state": "open",
         "pull_request": {"url": "..."}}]})
    result = asyncio.run(adapter.run("github.issues", {"repo": "octocat/Hello"}))
    assert "A bug" in result and "A change" not in result


def test_github_refuses_a_repository_name_that_is_not_one() -> None:
    """And puts the fix in the remedy rather than the message, which is where
    every other failure in this layer puts it."""
    adapter, _ = github({})
    with pytest.raises(Exception) as raised:
        asyncio.run(adapter.run("github.issues", {"repo": "Hello"}))
    assert "not a repository name" in str(raised.value)
    assert "owner/name" in raised.value.remedy


def test_github_writing_a_file_looks_for_the_existing_blob_first() -> None:
    """GitHub refuses an update without the current SHA rather than clobbering.
    Looking it up is what makes "write this file" work on a file that exists."""
    adapter, transport = github({
        "GET /repos/octocat/Hello/contents/notes.md": {"sha": "abc123"},
        "PUT /repos/octocat/Hello/contents/notes.md": {
            "commit": {"html_url": "https://github.com/c/1"}}})
    asyncio.run(adapter.run("github.write_file", {
        "repo": "octocat/Hello", "path": "notes.md",
        "content": "hello", "message": "add notes"}))
    assert transport.last()["json"]["sha"] == "abc123"


def test_github_writing_a_new_file_does_not_invent_a_sha() -> None:
    adapter, transport = github({
        "PUT /repos/octocat/Hello/contents/new.md": {
            "commit": {"html_url": "https://github.com/c/2"}}})
    asyncio.run(adapter.run("github.write_file", {
        "repo": "octocat/Hello", "path": "new.md",
        "content": "hello", "message": "add"}))
    assert "sha" not in transport.last()["json"]


# ============================================================ approval
def test_a_write_is_previewed_with_what_it_would_actually_do(approve_everything,
                                                             monkeypatch) -> None:
    """"Open an issue" is not a decision anybody can make. "Open THIS issue on
    THAT repository" is."""
    adapter, _ = github({"POST /repos/octocat/Hello/issues": {
        "number": 7, "html_url": "https://github.com/octocat/Hello/issues/7"}})
    monkeypatch.setattr(registry, "_CACHE", [adapter])

    asyncio.run(registry.perform("github.create_issue", {
        "repo": "octocat/Hello", "title": "Crash on save",
        "body": "It crashes when I save."}))

    request = approve_everything[0]
    assert "octocat/Hello" in request.preview
    assert "Crash on save" in request.preview
    assert "It crashes when I save." in request.preview
    assert "cannot be undone" in request.preview


def test_approving_runs_the_action_exactly_once(monkeypatch) -> None:
    adapter, transport = github({"POST /repos/octocat/Hello/issues": {
        "number": 7, "html_url": "https://x"}})
    monkeypatch.setattr(registry, "_CACHE", [adapter])

    calls = []

    async def approve(request):
        calls.append(request.action)
        return None

    monkeypatch.setattr(registry, "_ASK", approve)
    asyncio.run(registry.perform("github.create_issue",
                                 {"repo": "octocat/Hello", "title": "x"}))

    assert calls == ["github.create_issue"]
    posts = [c for c in transport.calls if c["method"] == "POST"]
    assert len(posts) == 1, "approved once, executed once"


def test_denying_runs_nothing(monkeypatch) -> None:
    adapter, transport = github({"POST /repos/octocat/Hello/issues": {
        "number": 7, "html_url": "https://x"}})
    monkeypatch.setattr(registry, "_CACHE", [adapter])

    async def deny(request):
        raise PermissionError("the user said no")

    monkeypatch.setattr(registry, "_ASK", deny)
    with pytest.raises(PermissionError):
        asyncio.run(registry.perform("github.create_issue",
                                     {"repo": "octocat/Hello", "title": "x"}))
    assert [c for c in transport.calls if c["method"] == "POST"] == []


def test_reading_and_writing_are_governed_differently(monkeypatch) -> None:
    """The point of deriving risk from the capability."""
    adapter, _ = github({})
    monkeypatch.setattr(registry, "_CACHE", [adapter])
    assert adapter.action("github.issues").risk.value == "read"
    assert adapter.action("github.create_issue").risk.value == "message"


# ============================================================ lifecycle
def test_disconnecting_and_reconnecting_recovers_the_connection() -> None:
    config = ProviderConfig(provider="github")
    connected("github", "first", account="octocat")
    assert connections.status("github", AuthKind.TOKEN, config).state.value \
        == "connected"

    connections.disconnect("github", config)
    assert connections.status("github", AuthKind.TOKEN, config).state.value \
        == "not_connected"

    connected("github", "second", account="octocat")
    status = connections.status("github", AuthKind.TOKEN, config)
    assert status.state.value == "connected"
    assert status.account == "octocat"


def test_an_expired_token_is_reported_as_needing_a_person() -> None:
    adapter, _ = github({"GET /user": Reply(
        {"message": "Bad credentials"}, status=401)})
    with pytest.raises(Exception) as raised:
        adapter.whoami()
    assert getattr(raised.value, "needs_reconnect", False) is True


def test_a_missing_scope_is_not_reported_as_sign_in_again() -> None:
    """401 and 403 have different remedies, and telling somebody to reconnect
    when the answer is "ask your admin" wastes an afternoon."""
    adapter, _ = github({"GET /user": Reply(
        {"message": "Resource not accessible by personal access token"},
        status=403)})
    with pytest.raises(Exception) as raised:
        adapter.whoami()
    assert getattr(raised.value, "needs_reconnect", False) is False
    assert "not granted" in raised.value.remedy


# ============================================================ Slack
def test_slack_treats_its_own_failure_as_a_failure() -> None:
    """Slack answers `{"ok": false}` with HTTP 200. An adapter trusting the
    status hands the model an empty result and no reason."""
    connected("slack", "xoxb-1", account="bot")
    transport = Transport({"GET /conversations.list": {
        "ok": False, "error": "missing_scope"}})
    adapter = Slack(client_factory=lambda: transport)
    with pytest.raises(Exception) as raised:
        asyncio.run(adapter.run("slack.channels", {}))
    assert "permission" in str(raised.value).lower()


def test_slack_accepts_a_channel_name_rather_than_only_an_id() -> None:
    """A model that has read a channel list will say #general, and so will a
    person."""
    connected("slack", "xoxb-1", account="bot")
    transport = Transport({
        "GET /conversations.list": {"ok": True, "channels": [
            {"id": "C123", "name": "general"}]},
        "POST /chat.postMessage": {"ok": True, "ts": "1.2"}})
    adapter = Slack(client_factory=lambda: transport)
    asyncio.run(adapter.run("slack.post", {"channel": "#general", "text": "hi"}))
    assert transport.last()["json"]["channel"] == "C123"


def test_slack_history_reads_oldest_first() -> None:
    """Slack returns newest first, and a conversation read backwards is one the
    model summarises backwards."""
    connected("slack", "xoxb-1", account="bot")
    transport = Transport({
        "GET /conversations.list": {"ok": True, "channels": [
            {"id": "C1", "name": "general"}]},
        "GET /conversations.history": {"ok": True, "messages": [
            {"ts": "3", "user": "U", "text": "third"},
            {"ts": "1", "user": "U", "text": "first"}]}})
    adapter = Slack(client_factory=lambda: transport)
    result = asyncio.run(adapter.run("slack.history", {"channel": "general"}))
    assert result.index("first") < result.index("third")


def test_slack_explains_a_bot_token_cannot_search() -> None:
    connected("slack", "xoxb-1", account="bot")
    transport = Transport({"GET /search.messages": {
        "ok": False, "error": "not_allowed_token_type"}})
    adapter = Slack(client_factory=lambda: transport)
    with pytest.raises(Exception) as raised:
        asyncio.run(adapter.run("slack.search", {"query": "x"}))
    assert "user token" in str(raised.value)


# ============================================================ Notion
def test_notion_accepts_a_pasted_page_url() -> None:
    """People paste URLs. Requiring the bare 32-character id would fail on the
    thing everybody actually has to hand."""
    adapter = Notion()
    assert adapter._identifier(
        "https://www.notion.so/Some-Page-1234567890abcdef1234567890abcdef"
    ) == "1234567890abcdef1234567890abcdef"


def test_notion_explains_the_sharing_step_when_nothing_is_found() -> None:
    """An integration sees nothing until each page is shared with it, and the
    symptom is an empty list rather than an error."""
    connected("notion", "secret_1", account="workspace")
    transport = Transport({"POST /search": {"results": []}})
    adapter = Notion(client_factory=lambda: transport)
    result = asyncio.run(adapter.run("notion.search", {"query": "x"}))
    assert "shared with it" in result


def test_notion_flattens_a_block_tree_into_readable_text() -> None:
    connected("notion", "secret_1", account="workspace")
    transport = Transport({
        "GET /pages/": {"properties": {"Name": {
            "type": "title", "title": [{"plain_text": "Roadmap"}]}}},
        "GET /blocks/": {"results": [
            {"type": "heading_1",
             "heading_1": {"rich_text": [{"plain_text": "Q1"}]}},
            {"type": "bulleted_list_item",
             "bulleted_list_item": {"rich_text": [{"plain_text": "Ship it"}]}},
            {"type": "unsupported_embed", "unsupported_embed": {}}]}})
    adapter = Notion(client_factory=lambda: transport)
    result = asyncio.run(adapter.run(
        "notion.read_page",
        {"page_id": "1234567890abcdef1234567890abcdef"}))
    assert "# Roadmap" in result
    assert "# Q1" in result
    assert "- Ship it" in result
    assert "unsupported" not in result


def test_notion_pins_the_api_version() -> None:
    connected("notion", "secret_1", account="w")
    transport = Transport({"POST /search": {"results": []}})
    adapter = Notion(client_factory=lambda: transport)
    asyncio.run(adapter.run("notion.search", {"query": "x"}))
    assert transport.last()["headers"]["Notion-Version"] == "2022-06-28"


# ============================================================ Dropbox
def test_dropbox_uses_the_empty_string_for_the_root() -> None:
    """The one piece of this API that catches everybody: the root is "", not
    "/", and passing "/" produces an error mentioning neither."""
    adapter = Dropbox()
    assert adapter._path("/", allow_root=True) == ""
    assert adapter._path("Reports/q1.txt") == "/Reports/q1.txt"


def test_dropbox_asks_for_a_refresh_token() -> None:
    """Without token_access_type=offline Dropbox issues a four-hour token and
    nothing to renew it with."""
    from uncloud_engine.core.integrations.providers.dropbox import DEFAULTS

    assert DEFAULTS.extra_authorize["token_access_type"] == "offline"


def test_dropbox_puts_its_arguments_in_a_header_for_content_calls() -> None:
    """Metadata is JSON to one host; content is a header plus bytes to
    another. That is not a wrapper detail."""
    connections.store_oauth_result(
        "dropbox",
        __import__("uncloud_engine.core.auth", fromlist=["Tokens"]).Tokens(
            access_token="dbx"),
        account="someone")
    transport = Transport({"POST /files/upload": {"path_display": "/a.txt"}})
    adapter = Dropbox(client_factory=lambda: transport)
    asyncio.run(adapter.run("dropbox.write", {"path": "/a.txt",
                                              "content": "hello"}))
    call = transport.last()
    assert json.loads(call["headers"]["Dropbox-API-Arg"])["path"] == "/a.txt"
    assert call["content"] == b"hello"


# ============================================================ Google
def test_google_asks_for_offline_access_and_forces_consent() -> None:
    """Without access_type=offline there is no refresh token and the connection
    dies in an hour with nothing to renew it."""
    from uncloud_engine.core.integrations.providers.google import DEFAULTS

    assert DEFAULTS.extra_authorize["access_type"] == "offline"
    assert DEFAULTS.extra_authorize["prompt"] == "consent"


def test_google_finds_the_body_buried_in_a_mime_tree() -> None:
    """A reader that only checked payload.body returns empty strings for most
    real mail."""
    payload = {"mimeType": "multipart/alternative", "body": {}, "parts": [
        {"mimeType": "text/html", "body": {"data": "PGI-aGk8L2I-"}},
        {"mimeType": "multipart/related", "parts": [
            {"mimeType": "text/plain",
             "body": {"data": "aGVsbG8gZnJvbSBhIG5lc3RlZCBwYXJ0"}}]}]}
    assert "hello from a nested part" in Google._body_of(payload)


def test_google_prefers_plain_text_over_html() -> None:
    payload = {"parts": [
        {"mimeType": "text/html", "body": {"data": "PGI-aWdub3JlPC9iPg"}},
        {"mimeType": "text/plain", "body": {"data": "cGxhaW4gdGV4dA"}}]}
    assert Google._body_of(payload).strip() == "plain text"


def test_google_sends_rfc_2822_because_there_is_no_other_endpoint() -> None:
    import base64

    connections.store_oauth_result(
        "google",
        __import__("uncloud_engine.core.auth", fromlist=["Tokens"]).Tokens(
            access_token="ya29"),
        account="someone@example.test")
    transport = Transport({"POST /users/me/messages/send": {"id": "m1"}})
    adapter = Google(client_factory=lambda: transport)
    asyncio.run(adapter.run("google.mail_send", {
        "to": "ana@example.test", "subject": "Hello", "body": "Hi there"}))
    raw = transport.last()["json"]["raw"]
    decoded = base64.urlsafe_b64decode(raw + "===").decode()
    assert "To: ana@example.test" in decoded
    assert "Subject: Hello" in decoded
    assert "Hi there" in decoded


def test_google_previews_a_send_with_its_recipients(monkeypatch) -> None:
    adapter = Google()
    change = asyncio.run(adapter.preview("google.mail_send", {
        "to": "ana@example.test", "cc": "sam@example.test",
        "subject": "Q1", "body": "See attached."}))
    assert "ana@example.test" in change.target
    assert "sam@example.test" in change.target
    assert change.reversible is False


def test_google_preview_says_a_draft_is_not_sent() -> None:
    adapter = Google()
    change = asyncio.run(adapter.preview("google.mail_draft",
                                         {"to": "ana@example.test"}))
    assert change.reversible is True
    assert "not sent" in change.detail


# ============================================================ Microsoft
def test_microsoft_addresses_a_file_the_way_graph_wants() -> None:
    """The colons are not a typo; they are how Graph separates a path from the
    action, and getting them wrong is a 400 that mentions neither."""
    assert Microsoft._drive_item("/Reports/q1.xlsx") \
        == "/me/drive/root:/Reports/q1.xlsx:"


def test_microsoft_does_not_combine_search_with_ordering() -> None:
    """Graph rejects $search with $orderby, and says nothing useful about it."""
    connections.store_oauth_result(
        "microsoft",
        __import__("uncloud_engine.core.auth", fromlist=["Tokens"]).Tokens(
            access_token="eyJ"),
        account="someone@example.test")
    transport = Transport({"GET /me/messages": {"value": []}})
    adapter = Microsoft(client_factory=lambda: transport)

    asyncio.run(adapter.run("microsoft.mail_search", {"query": "invoice"}))
    params = transport.last()["params"]
    assert "$search" in params and "$orderby" not in params

    asyncio.run(adapter.run("microsoft.mail_search", {}))
    params = transport.last()["params"]
    assert "$orderby" in params and "$search" not in params


def test_microsoft_reads_word_by_downloading_and_parsing_it(tmp_path) -> None:
    """Graph has no content API for Word. The reader this package already had
    is what makes that a two-line path rather than a dependency."""
    from uncloud_engine.core.integrations import ooxml

    local = ooxml.write_docx(tmp_path / "a.docx", ["First line.", "Second."])
    connections.store_oauth_result(
        "microsoft",
        __import__("uncloud_engine.core.auth", fromlist=["Tokens"]).Tokens(
            access_token="eyJ"),
        account="someone@example.test")
    transport = Transport({"GET /content": Reply(
        local.read_bytes().decode("latin-1"))})
    # The stub returns text; give it real bytes instead.
    transport.routes["GET /content"].content = local.read_bytes()

    adapter = Microsoft(client_factory=lambda: transport)
    result = asyncio.run(adapter.run("microsoft.word_read",
                                     {"path": "/Reports/a.docx"}))
    assert "First line." in result and "Second." in result
