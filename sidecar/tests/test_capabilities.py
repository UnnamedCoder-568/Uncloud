"""Capability routing, and the Office writers the workflows depend on.

The routing tests are about one property: nothing above the registry knows a
provider's name. The orchestrator asks for `email.send`; adding Fastmail should
be an adapter and nothing else. Everything here tries to prove that boundary is
real rather than aspirational.
"""

from __future__ import annotations

import asyncio
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from uncloud_engine.core.integrations import (
    Action,
    Capability,
    Change,
    Integration,
    IntegrationError,
    documents,
    ooxml,
    registry,
)
from uncloud_engine.core.integrations.capabilities import RISK, WRITES, risk_of
from uncloud_engine.core.permission import Risk


class Stub(Integration):
    """A provider that can do whatever the test says it can."""

    def __init__(self, ident: str, capabilities: tuple[Capability, ...], *,
                 live: bool = True, available: bool = True) -> None:
        super().__init__(
            id=ident, name=ident.title(), summary="test double",
            available=available, needs_credential=False,
            actions=tuple(
                Action(id=f"{ident}.{c.value}", capability=c, summary=c.value)
                for c in capabilities))
        self._live = live
        self.ran: list[str] = []

    def connected(self) -> bool:
        return self._live

    async def preview(self, action_id, arguments):
        return Change(summary=f"do {action_id}", target="somewhere")

    async def run(self, action_id, arguments):
        self.ran.append(action_id)
        return f"{action_id} ran"


@pytest.fixture
def only(monkeypatch):
    def install(*integrations):
        monkeypatch.setattr(registry, "_CACHE", list(integrations))
        return integrations
    return install


@pytest.fixture(autouse=True)
def allow_everything(monkeypatch):
    async def allow(request):
        return None
    monkeypatch.setattr(registry, "_ASK", allow)


# ------------------------------------------------------------ classification
def test_every_capability_has_a_risk_category() -> None:
    """A capability nobody has classified cannot be governed, and defaulting it
    to READ is how a send ends up running under a read's policy."""
    for capability in Capability:
        assert capability in RISK, f"{capability.value} is unclassified"


def test_anything_that_reaches_another_person_is_stricter_than_a_write() -> None:
    """An email cannot be unsent, and the recipient is not the user."""
    for capability in (Capability.EMAIL_SEND, Capability.CHAT_MESSAGE_SEND,
                       Capability.CALENDAR_CREATE, Capability.CODE_ISSUE_CREATE,
                       Capability.CODE_PR_CREATE):
        assert risk_of(capability) is Risk.MESSAGE, capability.value


def test_drafting_is_separated_from_sending() -> None:
    """A draft is reversible and a sent message is not. That difference is the
    whole reason approval exists."""
    assert risk_of(Capability.EMAIL_DRAFT) is Risk.WRITE
    assert risk_of(Capability.EMAIL_SEND) is Risk.MESSAGE


def test_writes_is_derived_rather_than_declared_twice() -> None:
    assert Capability.EMAIL_SEND in WRITES
    assert Capability.EMAIL_READ not in WRITES


def test_two_providers_of_one_capability_get_the_same_policy(only) -> None:
    """The reason risk is derived from the capability rather than declared per
    action: sending mail must not ask for approval through one provider and
    not through another."""
    gmail, outlook = only(Stub("gmail", (Capability.EMAIL_SEND,)),
                          Stub("outlook", (Capability.EMAIL_SEND,)))
    assert (gmail.actions[0].risk == outlook.actions[0].risk == Risk.MESSAGE)


# -------------------------------------------------------------------- routing
def test_the_registry_answers_with_whoever_can_do_it(only) -> None:
    only(Stub("gmail", (Capability.EMAIL_SEND, Capability.EMAIL_READ)),
         Stub("outlook", (Capability.EMAIL_SEND,)),
         Stub("github", (Capability.CODE_ISSUE_CREATE,)))
    assert [i.id for i in registry.providers_for(Capability.EMAIL_SEND)] \
        == ["gmail", "outlook"]
    assert [i.id for i in registry.providers_for(Capability.EMAIL_READ)] \
        == ["gmail"]


def test_a_disconnected_provider_is_not_offered(only) -> None:
    only(Stub("gmail", (Capability.EMAIL_SEND,), live=False),
         Stub("outlook", (Capability.EMAIL_SEND,)))
    assert [i.id for i in registry.providers_for(Capability.EMAIL_SEND)] \
        == ["outlook"]


def test_an_unbuilt_provider_is_never_routed_to(only) -> None:
    only(Stub("planned", (Capability.EMAIL_SEND,), available=False))
    assert registry.providers_for(Capability.EMAIL_SEND) == []


def test_performing_a_capability_picks_a_provider_without_being_told(only) -> None:
    gmail, _ = only(Stub("gmail", (Capability.EMAIL_SEND,)),
                    Stub("outlook", (Capability.EMAIL_SEND,)))
    asyncio.run(registry.perform_capability(Capability.EMAIL_SEND, {}))
    assert gmail.ran == ["gmail.email.send"]


def test_a_named_provider_is_honoured(only) -> None:
    """'Send it from my work account' is a real instruction and has to survive
    the abstraction."""
    _, outlook = only(Stub("gmail", (Capability.EMAIL_SEND,)),
                      Stub("outlook", (Capability.EMAIL_SEND,)))
    asyncio.run(registry.perform_capability(Capability.EMAIL_SEND, {},
                                            provider="outlook"))
    assert outlook.ran == ["outlook.email.send"]


def test_nothing_connected_says_what_to_connect(only) -> None:
    """'No connected integration can send email — connect Gmail or Outlook' is
    actionable. 'Action not found' is not."""
    only(Stub("gmail", (Capability.EMAIL_SEND,), live=False),
         Stub("outlook", (Capability.EMAIL_SEND,), live=False))
    with pytest.raises(IntegrationError) as raised:
        asyncio.run(registry.perform_capability(Capability.EMAIL_SEND, {}))
    assert "No connected integration" in str(raised.value)
    assert "Gmail" in raised.value.remedy and "Outlook" in raised.value.remedy


def test_a_capability_no_provider_implements_says_so_differently(only) -> None:
    """Distinct from 'nothing is connected', because one is fixed by signing in
    and the other is not fixed by anything the user can do."""
    only(Stub("gmail", (Capability.EMAIL_READ,)))
    with pytest.raises(IntegrationError) as raised:
        asyncio.run(registry.perform_capability(Capability.EMAIL_SEND, {}))
    assert "Nothing in this build" in str(raised.value)


def test_routing_still_goes_through_the_gate(only, monkeypatch) -> None:
    """Choosing a provider must not become a way around the permission
    system."""
    stub = only(Stub("gmail", (Capability.EMAIL_SEND,)))[0]
    asked = []

    async def refuse(request):
        asked.append(request.action)
        raise PermissionError("no")

    monkeypatch.setattr(registry, "_ASK", refuse)
    with pytest.raises(PermissionError):
        asyncio.run(registry.perform_capability(Capability.EMAIL_SEND, {}))
    assert asked == ["gmail.email.send"]
    assert stub.ran == []


def test_the_capability_map_is_readable_without_a_connection(only) -> None:
    only(Stub("gmail", (Capability.EMAIL_SEND,), live=False))
    assert registry.capability_map(connected_only=False) == {
        "email.send": ["gmail"]}
    assert registry.capability_map() == {}


# ------------------------------------------------------------- Office writers
def parts(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


def well_formed(path: Path) -> None:
    """Every XML part parses. A package with one malformed part opens as
    'unreadable content' rather than failing usefully."""
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.endswith((".xml", ".rels")):
                ElementTree.fromstring(archive.read(name))


def test_a_written_document_round_trips_through_our_own_reader(tmp_path) -> None:
    path = ooxml.write_docx(tmp_path / "a.docx",
                            ["# Summary", "First point.", "Second point."])
    well_formed(path)
    text = documents.extract(path)
    assert "Summary" in text and "Second point." in text


def test_a_written_workbook_keeps_numbers_as_numbers(tmp_path) -> None:
    """A spreadsheet of numeric text is one somebody has to re-type."""
    path = ooxml.write_xlsx(tmp_path / "b.xlsx",
                            [["Item", "Cost"], ["Widget", 4.5], ["Gadget", 12]])
    well_formed(path)
    with zipfile.ZipFile(path) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").decode()
    assert 't="inlineStr"' in sheet          # text cells
    assert "<v>4.5</v>" in sheet             # numeric cell, not a string
    assert "Widget" in documents.extract(path)


def test_a_written_deck_has_one_slide_part_per_slide(tmp_path) -> None:
    path = ooxml.write_pptx(tmp_path / "c.pptx",
                            [("Q1", ["Up 12%"]), ("Q2", ["Flat"]), ("Q3", [])])
    well_formed(path)
    slides = [n for n in parts(path)
              if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
    assert len(slides) == 3
    text = documents.extract(path)
    assert "Q1" in text and "Up 12%" in text and "Q3" in text


def test_every_package_carries_the_parts_office_requires(tmp_path) -> None:
    """A missing content-type map or package relationship is the difference
    between a file that opens and one that reports corruption."""
    for path in (ooxml.write_docx(tmp_path / "a.docx", ["x"]),
                 ooxml.write_xlsx(tmp_path / "b.xlsx", [["x"]]),
                 ooxml.write_pptx(tmp_path / "c.pptx", [("x", [])])):
        names = parts(path)
        assert "[Content_Types].xml" in names
        assert "_rels/.rels" in names


def test_text_that_would_break_the_xml_is_escaped(tmp_path) -> None:
    """The obvious injection, and the one a summary of somebody's spreadsheet
    would hit by accident."""
    hostile = '</w:t></w:r></w:p><script>alert("x")</script> & < >'
    path = ooxml.write_docx(tmp_path / "a.docx", [hostile])
    well_formed(path)
    assert "script" in documents.extract(path)


def test_column_names_follow_excels_own_scheme() -> None:
    assert ooxml._column_name(0) == "A"
    assert ooxml._column_name(25) == "Z"
    assert ooxml._column_name(26) == "AA"
    assert ooxml._column_name(701) == "ZZ"


def test_a_wide_sheet_keeps_its_later_columns(tmp_path) -> None:
    """Past column Z the naming changes shape, and a wrong reference silently
    drops the cell."""
    path = ooxml.write_xlsx(tmp_path / "wide.xlsx",
                            [[f"c{i}" for i in range(30)]])
    with zipfile.ZipFile(path) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").decode()
    assert 'r="AD1"' in sheet
