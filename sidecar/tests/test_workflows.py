"""Whole workflows, through the real architecture.

The brief's example: read the latest spreadsheet, analyse it, create a
presentation, draft an email. What matters is not that those four steps can be
made to happen — anything can be made to happen with enough special-casing —
but that they happen by COMPOSING capabilities, with no step in the chain
knowing which provider will serve it.

So the tests below never name a provider when they ask for something. They ask
for `spreadsheet.read` and `presentation.create`, and assert on which adapter
the registry chose and what the gate was asked about on the way.

The models are absent on purpose. A workflow test that loaded weights would
take four minutes and prove something about the checkpoint rather than about
the architecture; the analysis step here is a plain function, and the parts
under test are discovery, routing, permission and execution.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from uncloud_engine.core.integrations import (
    Capability,
    credentials,
    documents,
    ooxml,
    registry,
)
from uncloud_engine.core.integrations.providers import GitHub, Notion
from uncloud_engine.core.permission import Risk


class Reply:
    def __init__(self, body, status: int = 200) -> None:
        self.status_code, self._body = status, body
        self.headers = {}
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.content = self.text.encode()

    def json(self):
        return self._body


class Transport:
    def __init__(self, routes: dict) -> None:
        self.routes, self.calls = dict(routes), []

    def request(self, method, url, params=None, json=None, headers=None,
                content=None, follow_redirects=False):
        self.calls.append({"method": method, "url": url, "json": json})
        for pattern, reply in self.routes.items():
            wanted, _, fragment = pattern.partition(" ")
            if method.upper() == wanted.upper() and fragment in url:
                return reply if isinstance(reply, Reply) else Reply(reply)
        return Reply({"message": f"no stub for {method} {url}"}, status=404)

    def post(self, url, data=None, headers=None):
        return self.request("POST", url, json=data, headers=headers)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A connected documents folder holding a spreadsheet somebody made."""
    root = tmp_path / "work"
    root.mkdir()
    ooxml.write_xlsx(root / "q1-sales.xlsx", [
        ["Region", "Revenue", "Deals"],
        ["North", 128000, 41],
        ["South", 94000, 33],
        ["East", 156000, 52],
    ])
    monkeypatch.setattr(credentials, "path_of",
                        lambda handle: root if handle == documents.HANDLE else None)
    monkeypatch.setattr(credentials, "_keyring", lambda: None)
    monkeypatch.setattr(credentials, "_DIRECTORY", tmp_path / "state")
    return root


@pytest.fixture
def asked(monkeypatch):
    """Record every decision the gate is asked to make, and allow it."""
    decisions: list = []

    async def allow(request):
        decisions.append(request)
        return None

    monkeypatch.setattr(registry, "_ASK", allow)
    return decisions


@pytest.fixture
def only_documents(workspace, monkeypatch):
    monkeypatch.setattr(registry, "_CACHE", [documents.Documents()])
    return workspace


# ====================================================== the brief's example
def test_a_spreadsheet_becomes_a_deck_and_a_draft(only_documents, asked,
                                                  monkeypatch) -> None:
    """Read the latest spreadsheet, analyse it, create a presentation, draft an
    email — by capability, never by provider.

    The email step uses a stand-in provider registered alongside the real
    documents folder, which is the point: the workflow does not change when the
    thing that can send mail is Gmail rather than a test double.
    """
    root = only_documents

    # ---- 1. Discover. The plan is built from capabilities, not providers.
    available = registry.capability_map()
    assert "spreadsheet.read" not in available, \
        "the folder reads files; it does not read spreadsheets by that name"
    assert "storage.file.list" in available

    listing = asyncio.run(registry.perform_capability(
        Capability.STORAGE_LIST, {}))
    assert "q1-sales.xlsx" in listing

    # ---- 2. Read it. Still no provider named.
    sheet = asyncio.run(registry.perform_capability(
        Capability.STORAGE_READ, {"path": "q1-sales.xlsx"}))
    assert "Region" in sheet and "156000" in sheet

    # ---- 3. Analyse. A plain function stands in for the model.
    rows = [line.split("\t") for line in sheet.splitlines()][1:]
    best = max(rows, key=lambda r: float(r[1]))
    total = sum(float(r[1]) for r in rows)

    # ---- 4. Create the deck, by capability.
    asyncio.run(registry.perform_capability(Capability.PRESENTATION_CREATE, {
        "path": "q1-summary.pptx",
        "slides": [
            {"title": "Q1 revenue", "bullets": [f"Total {total:,.0f}",
                                                f"Best region {best[0]}"]},
            {"title": "By region",
             "bullets": [f"{r[0]}: {r[1]}" for r in rows]},
        ]}))

    made = root / "q1-summary.pptx"
    assert made.is_file()
    assert "Best region East" in documents.extract(made)

    # ---- 5. The gate was asked about the write, and not about the reads.
    categories = {r.action: r.category for r in asked}
    assert categories["documents.write_presentation"] is Risk.WRITE
    assert categories["documents.read"] is Risk.READ
    assert categories["documents.list"] is Risk.READ


def test_the_draft_step_routes_to_whatever_can_send_mail(workspace, asked,
                                                          monkeypatch) -> None:
    """The fourth step of the same workflow, with a mail provider present.

    Nothing in the calling code names it. Swapping the stand-in for Gmail is a
    registry change and nothing else, which is the property the whole capability
    layer exists to provide.
    """
    from uncloud_engine.core.integrations import Action, Change, Integration

    class Mailer(Integration):
        def __init__(self) -> None:
            super().__init__(
                id="stand-in-mail", name="Stand-in Mail", summary="",
                available=True, needs_credential=False,
                actions=(Action(id="stand-in-mail.draft",
                                capability=Capability.EMAIL_DRAFT,
                                summary="Save a draft"),))
            self.drafted: dict = {}

        def ready(self) -> bool:
            return True

        async def preview(self, action_id, arguments):
            return Change(summary="Draft a message",
                          target=str(arguments.get("to", "")),
                          reversible=True,
                          body=str(arguments.get("body", "")))

        async def run(self, action_id, arguments):
            self.drafted = dict(arguments)
            return "draft saved"

    mailer = Mailer()
    monkeypatch.setattr(registry, "_CACHE", [documents.Documents(), mailer])

    asyncio.run(registry.perform_capability(Capability.EMAIL_DRAFT, {
        "to": "team@example.test", "subject": "Q1 summary",
        "body": "The deck is attached."}))

    assert mailer.drafted["to"] == "team@example.test"
    # A draft is reversible and is governed as a write, not a message.
    assert asked[-1].category is Risk.WRITE
    assert "team@example.test" in asked[-1].preview


def test_a_denied_step_stops_the_workflow_without_a_partial_result(
        only_documents, monkeypatch) -> None:
    """The property that makes approval worth having: refusing the write leaves
    no half-made file behind."""
    root = only_documents

    async def deny(request):
        if request.category is Risk.READ:
            return None
        raise PermissionError("the user said no")

    monkeypatch.setattr(registry, "_ASK", deny)

    sheet = asyncio.run(registry.perform_capability(
        Capability.STORAGE_READ, {"path": "q1-sales.xlsx"}))
    assert "Region" in sheet

    with pytest.raises(PermissionError):
        asyncio.run(registry.perform_capability(Capability.PRESENTATION_CREATE, {
            "path": "q1-summary.pptx",
            "slides": [{"title": "x", "bullets": []}]}))

    assert not (root / "q1-summary.pptx").exists()


# ================================================= issue to page, unnamed
def test_an_issue_becomes_a_page_without_either_side_being_named(asked,
                                                                  monkeypatch,
                                                                  tmp_path) -> None:
    """The brief's third example. Two providers, one workflow, and the code
    that runs it names neither."""
    monkeypatch.setattr(credentials, "_keyring", lambda: None)
    monkeypatch.setattr(credentials, "_DIRECTORY", tmp_path)

    from uncloud_engine.core.auth import connect_with_token

    connect_with_token("github", "ghp_x", account="octocat")
    connect_with_token("notion", "secret_x", account="workspace")

    github = GitHub(client_factory=lambda: Transport({
        "GET /repos/acme/app/issues/12": {
            "number": 12, "title": "Login fails on Safari", "state": "open",
            "body": "Steps: open, log in, nothing happens."}}))
    notion = Notion(client_factory=lambda: Transport({
        "POST /pages": {"id": "p1", "url": "https://notion.so/p1"}}))
    monkeypatch.setattr(registry, "_CACHE", [github, notion])

    issue = asyncio.run(registry.perform_capability(
        Capability.CODE_ISSUE_READ, {"repo": "acme/app", "number": 12}))
    assert "Login fails on Safari" in issue

    summary = issue.splitlines()[0]
    asyncio.run(registry.perform_capability(Capability.NOTES_PAGE_CREATE, {
        "parent_id": "1234567890abcdef1234567890abcdef",
        "title": "Bug triage", "content": summary}))

    actions = [r.action for r in asked]
    assert actions == ["github.issues", "notion.create_page"]
    # Reading an issue is a read; creating a page is not.
    assert asked[0].category is Risk.READ
    assert asked[1].category is Risk.WRITE


def test_the_workflow_says_what_to_connect_when_nothing_can(monkeypatch,
                                                            tmp_path) -> None:
    """The failure a person can act on. "No connected integration can send
    email — connect Google Workspace or Microsoft 365" beats a stack trace, and
    beats "action not found" by more."""
    monkeypatch.setattr(credentials, "_keyring", lambda: None)
    monkeypatch.setattr(credentials, "_DIRECTORY", tmp_path)
    monkeypatch.setattr(registry, "_CACHE", None)

    with pytest.raises(Exception) as raised:
        asyncio.run(registry.perform_capability(Capability.EMAIL_SEND, {}))
    assert "No connected integration" in str(raised.value)
    assert "Google Workspace" in raised.value.remedy
    assert "Microsoft 365" in raised.value.remedy


# ============================================== reached through the agent
def test_the_agent_can_use_a_capability_without_naming_a_provider(only_documents,
                                                                   asked) -> None:
    """`run_tool` is the only way the agent does anything, so the capability
    tool has to work through it — and be governed by the resolved action's
    category rather than by a category of its own."""
    from uncloud_engine.agent import tools

    result = asyncio.run(tools.run_tool("capability", {
        "capability": "storage.file.list", "arguments": {}}))
    assert "q1-sales.xlsx" in result
    assert asked[-1].action == "documents.list"
    assert asked[-1].category is Risk.READ


def test_an_invented_capability_is_refused_with_the_real_list(only_documents) -> None:
    from uncloud_engine.agent import tools

    with pytest.raises(ValueError) as raised:
        asyncio.run(tools.run_tool("capability", {"capability": "email.telepathy"}))
    assert "email.send" in str(raised.value)


def test_the_agent_is_told_which_capabilities_would_actually_run(only_documents) -> None:
    """Written capability-first, because that is how the model should plan."""
    from uncloud_engine.agent.tools import _integrations

    text = _integrations()
    assert "Capabilities available right now" in text
    assert "storage.file.list" in text
    assert "Google Workspace — needs configuring" in text, \
        "and it must not be told to sign in to something with no OAuth client"
