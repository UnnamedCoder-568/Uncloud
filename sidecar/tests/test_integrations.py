"""Integrations: the four rules, and the ways they are normally broken.

Almost every test here asserts that something is NOT possible. That is the
shape of the feature: connecting Uncloud to somebody's mail, files and
repositories is only safe because of what the framework refuses to do, and a
refusal that is not tested is a refusal that quietly stops happening.

Nothing here touches a network. The one implemented integration is a folder on
disk, and the rest are declared-but-unbuilt — which is itself one of the things
under test.
"""

from __future__ import annotations

import ast
import asyncio
import zipfile
from pathlib import Path

import pytest

from uncloud_engine.core.integrations import (
    Action,
    Capability,
    Change,
    Integration,
    IntegrationError,
    Sensitivity,
    credentials,
    documents,
    registry,
)
from uncloud_engine.core.permission import Risk
from uncloud_engine.core.integrations.capabilities import Capability
from uncloud_engine.core.permission import Risk

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent / "uncloud_engine" / "core" / "integrations"


# ----------------------------------------------------------------- documents
def docx(path: Path, paragraphs: list[str]) -> Path:
    """A minimal Word document. Real zip, real XML, real namespace."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml",
                         f'<w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>')
    return path


def xlsx(path: Path, rows: list[list[str]]) -> Path:
    """A spreadsheet using the shared-string table, as Excel actually writes."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    words: list[str] = []
    for row in rows:
        for cell in row:
            if cell not in words:
                words.append(cell)
    shared = "".join(f"<si><t>{w}</t></si>" for w in words)
    body = ""
    for n, row in enumerate(rows, start=1):
        cells = "".join(f'<c t="s"><v>{words.index(c)}</v></c>' for c in row)
        body += f'<row r="{n}">{cells}</row>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml",
                         f'<sst xmlns="{ns}">{shared}</sst>')
        archive.writestr("xl/worksheets/sheet1.xml",
                         f'<worksheet xmlns="{ns}"><sheetData>{body}</sheetData></worksheet>')
    return path


@pytest.fixture
def folder(tmp_path, monkeypatch):
    """A connected documents folder, with nothing touching the real keychain."""
    root = tmp_path / "docs"
    root.mkdir()
    monkeypatch.setattr(credentials, "path_of",
                        lambda handle: root if handle == documents.HANDLE else None)
    return root


def test_a_word_document_is_read_as_text_not_as_markup(folder) -> None:
    """`fs_read` on a .docx returns a screenful of XML that looks enough like
    content for a model to answer from it. This is why the integration exists."""
    docx(folder / "brief.docx", ["The first paragraph.", "And the second."])
    text = documents.extract(folder / "brief.docx")
    assert "The first paragraph." in text and "And the second." in text
    assert "<w:" not in text


def test_a_spreadsheets_shared_strings_are_resolved(folder) -> None:
    """Excel stores most text once and refers to it by index. A reader that
    ignores the shared table returns numbers and blanks — which looks exactly
    like a successfully read empty file."""
    xlsx(folder / "prices.xlsx", [["Item", "Cost"], ["Widget", "4.00"]])
    text = documents.extract(folder / "prices.xlsx")
    assert "Item" in text and "Widget" in text


def test_a_damaged_office_file_says_so_rather_than_returning_nonsense(folder) -> None:
    (folder / "broken.docx").write_bytes(b"this is not a zip")
    with pytest.raises(IntegrationError) as raised:
        documents.extract(folder / "broken.docx")
    assert raised.value.remedy


def test_a_format_with_no_reader_is_refused_rather_than_mangled(folder) -> None:
    (folder / "photo.jpg").write_bytes(bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00]))
    with pytest.raises(IntegrationError):
        documents.extract(folder / "photo.jpg")


# --------------------------------------------------------------------- scope
def test_a_path_outside_the_connected_folder_is_refused(folder) -> None:
    with pytest.raises(IntegrationError) as raised:
        documents.Documents()._resolve("../secrets.txt")
    assert "outside the connected folder" in str(raised.value)


def test_a_symlink_pointing_out_of_the_folder_is_refused(folder, tmp_path) -> None:
    """The one an attacker would actually use. Checking the string the caller
    supplied catches `../` and misses this entirely."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "private.txt").write_text("not yours")
    (folder / "shortcut").symlink_to(outside)
    with pytest.raises(IntegrationError):
        documents.Documents()._resolve("shortcut/private.txt")


def test_the_connected_folder_itself_is_allowed(folder) -> None:
    assert documents.Documents()._resolve("") == folder.resolve()


# --------------------------------------------------------------- credentials
def test_no_function_in_the_broker_hands_a_secret_back_to_its_caller() -> None:
    """The guarantee the brief asked for, checked structurally rather than by
    reading carefully.

    Not "nothing touches a secret" — `store` was handed one, and reads it back
    to check the keychain actually kept it. The invariant that matters is
    narrower and stronger: no function RETURNS one. `open` passes the secret to
    a caller-supplied callback and returns what that callback made, so an
    adapter never holds a token even carelessly.

    With nothing returning a secret, no prompt, log line, tool result or error
    message above this module can leak one — which beats redaction, because
    redaction is a list of places to remember.
    """
    tree = ast.parse((PACKAGE / "credentials.py").read_text())
    for function in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(function):
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            expression = ast.unparse(node.value)
            if "secret" not in expression:
                continue
            assert function.name == "open" and expression == "build(secret)", (
                f"{function.name} returns {expression!r}, which may be a stored "
                f"credential")


def test_the_keychain_is_read_in_only_the_two_places_that_need_to() -> None:
    """`_keyring` probes with a value it invented; `store` reads back what it
    was just given, because a keychain that accepts a write and returns nothing
    has stored nothing. `open` is the only reader of somebody else's secret."""
    tree = ast.parse((PACKAGE / "credentials.py").read_text())
    readers = {
        function.name
        for function in ast.walk(tree) if isinstance(function, ast.FunctionDef)
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute) and node.attr == "get_password"
    }
    assert readers == {"_keyring", "store", "open"}, readers


def test_opening_a_connection_hands_over_a_client_not_the_credential(monkeypatch
                                                                     ) -> None:
    seen = {}

    def build(secret: str) -> str:
        seen["length"] = len(secret)
        return "a client"

    monkeypatch.setattr(credentials, "_keyring", lambda: None)
    monkeypatch.setattr(credentials, "_read_fallback",
                        lambda: {"secrets": {"h": "s3cret"}, "index": {}})
    assert credentials.open("h", build) == "a client"
    assert seen["length"] == 6


def test_what_the_interface_may_see_contains_no_secret(monkeypatch) -> None:
    monkeypatch.setattr(credentials, "_index",
                        lambda: {"github": {"label": "octocat", "kind": "token"}})
    rows = credentials.describe()
    assert rows[0]["label"] == "octocat"
    assert "secret" not in rows[0] and "token" not in str(rows[0]["label"])


def test_an_absent_credential_is_refused_rather_than_treated_as_empty(monkeypatch
                                                                      ) -> None:
    monkeypatch.setattr(credentials, "_keyring", lambda: None)
    monkeypatch.setattr(credentials, "_read_fallback", lambda: {})
    with pytest.raises(credentials.NotConnected):
        credentials.open("nothing", lambda s: s)


# ------------------------------------------------------------- classification
def test_every_action_carries_a_risk_category() -> None:
    """An action nobody has classified cannot be governed, and a default is how
    a write ends up under a read's policy."""
    for integration in registry.all_integrations():
        for action in integration.actions:
            assert isinstance(action.risk, Risk)


def test_an_action_no_integration_declares_cannot_be_performed() -> None:
    assert registry.find_action("documents.delete_everything") is None


def test_a_provider_needing_an_oauth_client_says_so_rather_than_pretending() -> None:
    """The state that replaced "not built".

    Google and Microsoft are fully implemented and cannot work until somebody
    registers an OAuth application, because an OAuth client is issued to a
    named party under the provider's terms and Uncloud will not fabricate one.
    NOT_CONFIGURED is the honest answer, and its remedy is something only the
    user can do.
    """
    for provider in ("google", "microsoft"):
        integration = registry.get(provider)
        assert integration is not None
        assert integration.available is True, "these are built"
        assert integration.actions, "and they declare real actions"
        assert integration.connection().state.value == "not_configured"
        assert "cannot supply one" in integration.needs \
            or "cannot supply" in integration.needs \
            or "belongs to whoever" in integration.needs


def test_a_provider_taking_a_user_issued_token_needs_no_registration() -> None:
    """The difference that decides IMPLEMENTED from REQUIRES EXTERNAL
    CONFIGURATION in the report: GitHub, Slack and Notion issue tokens the user
    creates for themselves."""
    for provider in ("github", "slack", "notion"):
        integration = registry.get(provider)
        assert integration is not None
        assert integration.auth_kind.value == "token"
        assert integration.connection().state.value == "not_connected"


def test_every_integration_declares_at_least_one_capability() -> None:
    """A placeholder with no actions was the previous state of this system.
    Nothing should be in the registry now that cannot do anything."""
    for integration in registry.all_integrations():
        assert integration.capabilities(), f"{integration.id} does nothing"


def test_every_scope_is_described_in_a_persons_terms() -> None:
    """`https://www.googleapis.com/auth/gmail.send` tells nobody anything.
    A consent screen exists to be understood."""
    for integration in registry.all_integrations():
        for scope in integration.scopes:
            assert scope.summary and scope.summary != scope.id, \
                f"{integration.id}: {scope.id} has no plain description"


# ----------------------------------------------------- connection ≠ permission
class _Recorder(Integration):
    """A write-capable integration that records what happened to it."""

    def __init__(self, *, preview_returns: Change | None) -> None:
        super().__init__(
            id="recorder", name="Recorder", summary="test double",
            available=True, needs_credential=False,
            # A capability rather than a risk: the policy is derived, so two
            # providers implementing the same thing cannot end up governed
            # differently.
            actions=(Action(id="recorder.send",
                            capability=Capability.CHAT_MESSAGE_SEND,
                            summary="Send something"),))
        self._preview = preview_returns
        self.ran = False

    def connected(self) -> bool:
        return True

    async def preview(self, action_id: str, arguments: dict):
        return self._preview

    async def run(self, action_id: str, arguments: dict) -> str:
        self.ran = True
        return "sent"


@pytest.fixture
def recorder(monkeypatch):
    def install(integration):
        monkeypatch.setattr(registry, "_CACHE", [integration])
        return integration
    return install


def test_a_write_that_cannot_say_what_it_would_do_is_stopped(recorder) -> None:
    """A missing preview is a bug in an adapter. Letting it through turns that
    bug into an unreviewed side effect on somebody else's account."""
    integration = recorder(_Recorder(preview_returns=None))
    with pytest.raises(IntegrationError) as raised:
        asyncio.run(registry.perform("recorder.send", {}))
    assert integration.ran is False
    assert "could not say what" in str(raised.value)


def test_the_gate_decides_every_action_however_it_was_reached(recorder,
                                                              monkeypatch) -> None:
    """Connecting an account granted nothing, and a skill calling this inherits
    nothing. The gate is asked at the moment of the action, every time."""
    integration = recorder(_Recorder(
        preview_returns=Change(summary="Send a note", target="someone")))
    asked: list[str] = []

    async def refuse(request):
        asked.append(request.action)
        raise PermissionError("declined")

    monkeypatch.setattr(registry, "_ASK", refuse)
    with pytest.raises(PermissionError):
        asyncio.run(registry.perform("recorder.send", {},
                                     origin="skill:tidy-inbox"))
    assert asked == ["recorder.send"]
    assert integration.ran is False


def test_the_approval_shows_the_change_rather_than_the_action_name(recorder,
                                                                   monkeypatch) -> None:
    """'Send the email' is not a decision anybody can make well."""
    recorder(_Recorder(preview_returns=Change(
        summary="Send 'Invoice 12'", target="ana@example.com",
        reversible=False, body="Please find attached.")))
    seen: dict = {}

    async def capture(request):
        seen["preview"] = request.preview
        seen["summary"] = request.summary

    monkeypatch.setattr(registry, "_ASK", capture)
    asyncio.run(registry.perform("recorder.send", {}))
    assert "ana@example.com" in seen["preview"]
    assert "cannot be undone" in seen["preview"]
    assert "Please find attached." in seen["preview"]


def test_an_available_integration_that_is_switched_off_says_what_it_needs(
        recorder) -> None:
    """The other refusal: built, but not usable in this build. Its `needs` is
    what a person acts on, so it has to reach them."""
    unbuilt = _Recorder(preview_returns=Change(summary="x", target="y"))
    unbuilt.available = False
    unbuilt.needs = "An OAuth client registered with the provider."
    recorder(unbuilt)
    with pytest.raises(IntegrationError) as raised:
        asyncio.run(registry.perform("recorder.send", {}))
    assert raised.value.remedy == "An OAuth client registered with the provider."


# ------------------------------------------------------- remote model traffic
def test_private_content_does_not_reach_a_remote_model_by_default() -> None:
    allowed, why = registry.may_send_to_remote_model("documents")
    assert allowed is False
    assert "stays on this machine" in why


def test_the_user_can_allow_one_integration_without_allowing_all() -> None:
    assert registry.may_send_to_remote_model("documents", allowed={"documents"})[0]
    assert registry.may_send_to_remote_model("github", allowed={"documents"})[0] is False


def test_an_unknown_integration_is_a_no_rather_than_a_shrug() -> None:
    assert registry.may_send_to_remote_model("whatever")[0] is False


# -------------------------------------------------------------------- errors
def test_a_failure_carries_something_a_person_can_do() -> None:
    """Integration failures are mostly not bugs — an expired token, a moved
    file, a scope nobody granted. A stack trace answers none of those."""
    error = IntegrationError("The token expired.",
                             remedy="Reconnect it in Settings.",
                             needs_reconnect=True)
    assert error.to_dict() == {
        "error": "The token expired.", "remedy": "Reconnect it in Settings.",
        "retryable": False, "needs_reconnect": True}


def test_reconnecting_is_distinguished_from_waiting() -> None:
    """Different problems, different actions. Collapsing them tells somebody to
    try again when the answer is that their credential is gone."""
    transient = IntegrationError("The service is down.", retryable=True)
    assert transient.retryable and not transient.needs_reconnect


# ---------------------------------------------------------------- boundaries
def test_the_integration_layer_never_reads_a_credential_into_its_own_code() -> None:
    """Adapters must go through `credentials.open`. One that reached for the
    keychain itself would be holding a secret in a scope nothing audits."""
    for path in PACKAGE.glob("*.py"):
        if path.name == "credentials.py":
            continue
        text = path.read_text()
        assert "keyring" not in text, f"{path.name} reaches for the keychain itself"
        assert "get_password" not in text, f"{path.name} reads a secret directly"


# --------------------------------------------------- reached through the agent
def test_an_integration_action_called_as_a_tool_still_passes_the_gate(recorder,
                                                                      monkeypatch) -> None:
    """`run_tool` is the only way the agent runs anything, and integration
    actions arrive there like everything else. They are not in TOOL_RISK — they
    carry their own category — so the check that they are still governed has to
    be explicit."""
    from uncloud_engine.agent import tools

    integration = recorder(_Recorder(
        preview_returns=Change(summary="Send a note", target="someone")))
    asked: list[str] = []

    async def refuse(request):
        asked.append(request.action)
        raise PermissionError("declined")

    monkeypatch.setattr(registry, "_ASK", refuse)
    with pytest.raises(PermissionError):
        asyncio.run(tools.run_tool("recorder.send", {}))
    assert asked == ["recorder.send"]
    assert integration.ran is False


def test_an_unknown_dotted_name_is_still_an_unknown_tool() -> None:
    """The namespace check must not become a hole: a dotted name that no
    integration claims falls through to the ordinary refusal rather than being
    treated as an integration and waved past."""
    from uncloud_engine.agent import tools

    with pytest.raises(ValueError):
        asyncio.run(tools.run_tool("something.invented", {}))


def test_a_stored_credential_never_appears_in_what_the_model_reads(monkeypatch,
                                                                   tmp_path) -> None:
    """The discovery tool's output goes straight into model context, so it is
    the obvious place for a secret to escape. It cannot: the index holds labels
    and the keychain holds the value, and nothing joins them."""
    from uncloud_engine.agent.tools import _integrations

    monkeypatch.setattr(credentials, "_keyring", lambda: None)
    monkeypatch.setattr(credentials, "_read_fallback",
                        lambda: {"secrets": {"documents": "ghp_TOPSECRET123"},
                                 "index": {"documents": {"label": str(tmp_path)}}})
    monkeypatch.setattr(credentials, "path_of", lambda handle: tmp_path)

    text = _integrations()
    assert str(tmp_path) in text, "the label is what a person recognises"
    assert "ghp_TOPSECRET123" not in text


def test_core_refuses_rather_than_allows_when_no_approver_was_installed(recorder,
                                                                        monkeypatch) -> None:
    """The failure this seam could have had. An integration framework whose
    approval hook was never wired would execute everything silently, and it
    would look exactly like the system working."""
    integration = recorder(_Recorder(
        preview_returns=Change(summary="Send a note", target="someone")))
    monkeypatch.setattr(registry, "_ASK", None)
    with pytest.raises(registry.Ungoverned):
        asyncio.run(registry.perform("recorder.send", {}))
    assert integration.ran is False
