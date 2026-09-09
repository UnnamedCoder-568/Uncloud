"""The legal core: consent, disclosure, and the wall between them and permission.

Most of these tests are about refusing to be helpful in a particular way. A
legal layer's failure mode is not crashing — it is quietly answering a question
it was not entitled to answer: treating silence as consent, treating an
unverified licence as permission, or letting agreement to a document stand in
for approval of an action.
"""

from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path

import pytest

from uncloud_engine.foundation.capability import (
    CommercialUse,
    Component,
    Licence,
    ModelProfile,
)
from uncloud_engine.legal import disclosure, notices, terms

REPO = Path(__file__).resolve().parents[2]
OURS = REPO / "sidecar" / "uncloud_engine" / "legal"
THEIRS = REPO.parent / "UncloudAdStudio" / "engine" / "adstudio_engine" / "legal"

SHARED = ("__init__.py", "terms.py", "disclosure.py", "notices.py",
          "documents/core-terms.md", "documents/privacy.md")


def document(**over) -> terms.Document:
    base = {"id": "core-terms", "title": "Terms", "version": 1,
            "effective": "2026-01-01", "body": "text", "accepted_from": 1}
    return terms.Document(**{**base, **over})


def profile(**over) -> ModelProfile:
    base = {"id": "m", "name": "A Model", "licence": Licence()}
    return ModelProfile(**{**base, **over})


# ------------------------------------------------------------------ parsing
def test_a_document_is_read_from_its_frontmatter() -> None:
    parsed = terms.parse(
        "---\nid: core-terms\ntitle: Terms\nversion: 3\n"
        "effective: 2026-01-01\naccepted_from: 2\n---\n\nThe body.\n")
    assert parsed.id == "core-terms"
    assert parsed.version == 3 and parsed.accepted_from == 2
    assert parsed.body == "The body."


def test_a_document_with_no_body_is_refused() -> None:
    """A blank agreement somebody is recorded as having accepted is worse than
    a startup failure."""
    with pytest.raises(terms.Malformed):
        terms.parse("---\nid: x\nversion: 1\n---\n\n   \n")


def test_a_document_with_no_version_is_refused() -> None:
    with pytest.raises(terms.Malformed):
        terms.parse("---\nid: x\n---\n\nBody.\n")


def test_the_shipped_documents_all_parse() -> None:
    loaded = terms.load()
    assert {d.id for d in loaded} >= {"core-terms", "privacy"}


def test_the_drafts_say_they_are_drafts() -> None:
    """Nobody should be able to ship these by accident."""
    for doc in terms.load():
        assert "unreviewed draft" in doc.body.lower()


def test_every_fact_we_must_not_invent_is_a_visible_placeholder() -> None:
    """The brief was explicit: no invented entity, address, jurisdiction or
    contact. A placeholder is greppable; a plausible-looking invention is not."""
    body = "\n".join(d.body for d in terms.load())
    for required in ("[[LEGAL_ENTITY_NAME]]", "[[REGISTERED_ADDRESS]]",
                     "[[GOVERNING_JURISDICTION]]", "[[LEGAL_CONTACT_EMAIL]]",
                     "[[SUPPORT_EMAIL]]", "[[REFUND_POLICY]]",
                     "[[COMPANY_REGISTRATION]]", "[[TAX_INFORMATION]]",
                     "[[COMMERCIAL_LICENCE_TERMS]]"):
        assert required in body, f"{required} was invented rather than left open"


# --------------------------------------------------------------- acceptance
def test_nothing_is_accepted_until_it_is_recorded() -> None:
    register = terms.Register(documents=[document()])
    assert register.settled is False
    assert register.outstanding()[0].because == "new"


def test_an_editorial_revision_does_not_ask_again() -> None:
    """Fixing a typo must not throw a modal at everybody who already agreed."""
    register = terms.Register(documents=[document(version=1)])
    register.accept("core-terms", 1)
    register.documents = [document(version=2, accepted_from=1)]
    assert register.settled is True


def test_a_material_revision_asks_again_and_says_so() -> None:
    register = terms.Register(documents=[document(version=1)])
    register.accept("core-terms", 1)
    register.documents = [document(version=2, accepted_from=2)]
    outstanding = register.outstanding()
    assert outstanding[0].because == "changed"
    assert outstanding[0].previously == 1


def test_agreement_can_only_be_recorded_for_the_version_displayed() -> None:
    """An interface showing version 3 while the engine records 4 produces a
    consent record that is not true."""
    register = terms.Register(documents=[document(version=3)])
    with pytest.raises(ValueError):
        register.accept("core-terms", 4)


def test_a_notice_is_never_something_to_tick() -> None:
    register = terms.Register(documents=[document(id="privacy",
                                                  requires_agreement=False)])
    assert register.settled is True


def test_downgrading_the_app_does_not_withdraw_consent() -> None:
    store = terms.Memory()
    store.record(terms.Acceptance("core-terms", 5, "2026-01-01T00:00:00+00:00"))
    store.record(terms.Acceptance("core-terms", 2, "2026-01-02T00:00:00+00:00"))
    assert store.accepted("core-terms").version == 5


# --------------------------------------------------------------- disclosure
def test_an_unverified_licence_is_neither_a_yes_nor_a_no() -> None:
    """The single most damaging thing this layer could do is render 'nobody
    checked' as an answer."""
    shown = disclosure.describe(profile(licence=Licence(id="unknown")))
    assert shown.headline == "Licence not checked"
    assert "not a yes and it is not a no" in shown.explanation
    assert shown.must_acknowledge is True


def test_a_permissive_claim_nobody_checked_does_not_read_as_checked() -> None:
    shown = disclosure.describe(profile(licence=Licence(
        id="apache-2.0", commercial_use=CommercialUse.ALLOWED)))
    assert "no record of who checked" in shown.explanation


def test_a_verified_permissive_licence_says_nothing_extra() -> None:
    """Interrupting every download teaches people to click through the ones
    that matter."""
    shown = disclosure.describe(profile(licence=Licence(
        id="apache-2.0", commercial_use=CommercialUse.ALLOWED,
        verified_by="audit", verified_on="2026-09-02")))
    assert shown.severity == disclosure.Severity.NONE
    assert shown.must_acknowledge is False


def test_the_legal_layer_has_no_way_to_block_a_download() -> None:
    """The correction this module exists for. Whatever a licence says, there is
    no function here that answers 'may this be installed?' — because that was
    our restriction, not the publisher's."""
    api = set(dir(disclosure))
    for forbidden in ("may_download", "may_install", "blocks", "allowed_to_download",
                      "can_download", "permits_download"):
        assert forbidden not in api


def test_a_restrictive_licence_explains_that_you_may_still_install_it() -> None:
    shown = disclosure.describe(profile(licence=Licence(
        id="flux-1-dev-nc", commercial_use=CommercialUse.FORBIDDEN)))
    assert "You can still install" in shown.explanation


def test_parts_that_disagree_are_always_stopped_for() -> None:
    """A permissive transformer with a restrictive text encoder is the case
    that catches people out."""
    shown = disclosure.describe(profile(
        licence=Licence(id="apache-2.0", commercial_use=CommercialUse.ALLOWED,
                        verified_on="2026-09-02"),
        components=(Component(role="text encoder", name="T5",
                              licence=Licence(id="research-only",
                                              commercial_use=CommercialUse.RESEARCH_ONLY)),)))
    assert shown.mixed is True
    assert shown.must_acknowledge is True


# ------------------------------------------------------------- auto-selection
def test_nothing_is_restricted_when_the_work_is_not_commercial() -> None:
    for use in CommercialUse:
        allowed, _ = disclosure.may_auto_select(
            Licence(commercial_use=use), commercial=False)
        assert allowed is True


def test_conditional_is_not_a_yes_for_an_automatic_choice() -> None:
    """The conditions are the publisher's and depend on facts about the user
    that the software does not have."""
    allowed, why = disclosure.may_auto_select(
        Licence(commercial_use=CommercialUse.CONDITIONAL), commercial=True)
    assert allowed is False
    assert "by you, not by us" in why


def test_an_unverified_licence_is_not_auto_selected_for_commercial_work() -> None:
    allowed, why = disclosure.may_auto_select(
        Licence(commercial_use=CommercialUse.UNVERIFIED), commercial=True)
    assert allowed is False and "unknown is not a yes" in why


# ---------------------------------------------------------- acknowledgement
def test_an_acknowledgement_stops_the_same_warning_recurring() -> None:
    model = profile(licence=Licence(id="nc", commercial_use=CommercialUse.FORBIDDEN))
    ledger = disclosure.Ledger()
    assert ledger.needed(model) is True
    ledger.record(disclosure.acknowledge(model))
    assert ledger.needed(model) is False


def test_nobody_checked_is_acknowledged_once_rather_than_per_model() -> None:
    """The difference between informing somebody and training them to dismiss
    dialogs. In a catalogue where most licences are unread, a per-model prompt
    puts an identical box in front of every download."""
    ledger = disclosure.Ledger()
    first = profile(id="a", licence=Licence())
    second = profile(id="b", licence=Licence())
    assert ledger.needed(first) is True

    ledger.acknowledge(first)
    assert ledger.needed(first) is False
    assert ledger.needed(second) is False, \
        "a second unread licence asked again, which is the noise this avoids"


def test_a_specific_restriction_is_still_acknowledged_per_model() -> None:
    """The other half. 'This model forbids commercial use' is about this model,
    is rare, and is worth a stop."""
    ledger = disclosure.Ledger()
    ledger.acknowledge(profile(id="a", licence=Licence()))
    restricted = profile(id="b", licence=Licence(
        id="nc", commercial_use=CommercialUse.FORBIDDEN))
    assert ledger.needed(restricted) is True


def test_relicensing_invalidates_an_acknowledgement() -> None:
    """Consent to terms that no longer exist is not consent."""
    model = profile(licence=Licence(id="nc", commercial_use=CommercialUse.FORBIDDEN))
    ledger = disclosure.Ledger()
    ledger.record(disclosure.acknowledge(model))
    changed = profile(licence=Licence(id="nc-2",
                                      commercial_use=CommercialUse.RESEARCH_ONLY))
    assert ledger.needed(changed) is True


# ----------------------------------------------------------------- notices
def test_a_missing_notice_file_is_an_empty_list_not_a_crash(tmp_path) -> None:
    assert notices.load(tmp_path / "absent.json") == []


def test_a_notice_with_no_licence_is_reported_as_incomplete(tmp_path) -> None:
    """An approximated licence is worse than an absent one — it reads as
    authoritative."""
    path = tmp_path / "third-party.json"
    path.write_text('[{"name": "somelib", "version": "1.0"}]')
    loaded = notices.load(path)
    assert loaded[0].complete is False
    assert loaded[0].to_dict()["licence"] == "not recorded"
    assert notices.summarise(loaded)["incomplete"] == 1


# ------------------------------------------------------- the wall, and drift
def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add((node.module or "").split(".")[0]
                      if node.level == 0 else (node.module or "").split(".")[0])
    return {name for name in found if name}


def test_consent_and_permission_never_import_each_other() -> None:
    """Agreeing to terms is not granting an agent permission to run a shell
    command, and one must never be able to satisfy the other. Structural,
    because 'remember not to' is not a mechanism."""
    for name in ("terms.py", "disclosure.py", "notices.py", "__init__.py"):
        assert "permission" not in _imports(OURS / name), \
            f"legal/{name} imports the permission gate"
    gate = REPO / "sidecar" / "uncloud_engine" / "foundation" / "permission.py"
    assert "legal" not in _imports(gate), "the permission gate imports the legal core"


def test_the_legal_core_imports_only_the_standard_library_and_foundation() -> None:
    allowed = set(sys.stdlib_module_names) | {"foundation", ""}
    for name in ("terms.py", "disclosure.py", "notices.py"):
        outside = _imports(OURS / name) - allowed
        assert not outside, f"legal/{name} reaches into the product: {outside}"


def test_the_legal_core_declares_itself_shared() -> None:
    assert "BYTE-IDENTICAL IN BOTH REPOSITORIES" in (OURS / "terms.py").read_text()


@pytest.mark.skipif(not THEIRS.exists(),
                    reason="Uncloud Studio is not checked out beside this repository")
def test_both_products_carry_the_same_legal_core() -> None:
    for name in SHARED:
        ours, theirs = OURS / name, THEIRS / name
        assert theirs.exists(), f"legal/{name} is missing from Studio"
        assert hashlib.sha256(ours.read_bytes()).hexdigest() == \
               hashlib.sha256(theirs.read_bytes()).hexdigest(), (
            f"legal/{name} has drifted between Uncloud and Uncloud Studio.\n"
            f"  ours:   {ours}\n  theirs: {theirs}\n"
            "Copy whichever is correct over the other; do not edit one alone.")


# ------------------------------------------------------ the wiring, over HTTP
class _Client:
    """A TestClient over the real app, with its settings file redirected.

    Redirected because these tests WRITE consent, and a test run that recorded
    an acceptance in the developer's own `~/.uncloud/settings.json` would make
    the first-launch flow untestable ever again on that machine.
    """

    def __init__(self, tmp_path: Path) -> None:
        self._tmp = tmp_path

    def __enter__(self):
        from fastapi.testclient import TestClient

        from uncloud_engine import config, main

        self.main = main
        self._saved_file = config.CONFIG_FILE
        self._saved_data = dict(main.settings._data)
        config.CONFIG_FILE = self._tmp / "settings.json"
        main.settings._data = {}
        self.client = TestClient(main.app)
        self.client.headers.update(
            {"Authorization": f"Bearer {main.settings.token}"})
        return self.client

    def __exit__(self, *exc):
        from uncloud_engine import config

        config.CONFIG_FILE = self._saved_file
        self.main.settings._data = self._saved_data


def test_a_fresh_install_has_agreements_outstanding(tmp_path) -> None:
    """A build shipped without its documents reports 'settled' and never asks
    anybody anything. That is the silent failure worth a test."""
    with _Client(tmp_path) as client:
        state = client.get("/api/legal").json()
        assert state["settled"] is False
        assert {"core-terms", "uncloud-supplemental"} <= \
               {o["id"] for o in state["outstanding"]}


def test_accepting_settles_it_and_persists(tmp_path) -> None:
    with _Client(tmp_path) as client:
        for doc in ("core-terms", "uncloud-supplemental"):
            version = client.get(f"/api/legal/{doc}").json()["version"]
            client.post("/api/legal/accept",
                        json={"document_id": doc, "version": version})
        assert client.get("/api/legal").json()["settled"] is True
        assert (tmp_path / "settings.json").exists()


def test_agreement_to_a_version_that_is_not_displayed_is_refused(tmp_path) -> None:
    with _Client(tmp_path) as client:
        assert client.post("/api/legal/accept",
                           json={"document_id": "core-terms", "version": 99}
                           ).status_code == 409


def test_accepting_terms_grants_no_permission(tmp_path) -> None:
    """The separation the whole package exists to keep. Uncloud is where it
    matters most: the thing on the other side of the wall is an agent that can
    run shell commands."""
    with _Client(tmp_path) as client:
        before = client.get("/api/permissions").json()
        for doc in ("core-terms", "uncloud-supplemental"):
            version = client.get(f"/api/legal/{doc}").json()["version"]
            client.post("/api/legal/accept",
                        json={"document_id": doc, "version": version})
        assert client.get("/api/permissions").json() == before


def test_an_unread_licence_reports_as_unread_rather_than_as_a_refusal(tmp_path
                                                                      ) -> None:
    """Most of Uncloud's catalogue has not been read. That answer is the truth,
    and the one thing it must never be rendered as is a no."""
    with _Client(tmp_path) as client:
        profiles = client.get("/api/models/profiles").json()
        unread = next(p for p in profiles
                      if p["licence"]["commercial_use"] == "unverified")
        body = client.get(f"/api/models/{unread['id']}/licence").json()
        assert body["headline"] == "Licence not checked"
        assert "not a yes and it is not a no" in body["explanation"]
        for absent in ("may_download", "can_download", "blocked",
                       "download_allowed"):
            assert absent not in body


def test_a_licence_that_was_read_says_who_read_it(tmp_path) -> None:
    """The other half of the same honesty: a verified permissive licence should
    not interrupt anybody, and should be able to show its provenance."""
    with _Client(tmp_path) as client:
        body = client.get("/api/models/flux1-schnell/licence").json()
        assert body["commercial_use"] == "allowed"
        assert body["verified"] is True and body["verified_on"]
        assert body["needs_acknowledgement"] is False


def test_acknowledging_a_licence_grants_nothing(tmp_path) -> None:
    with _Client(tmp_path) as client:
        model_id = client.get("/api/models/profiles").json()[0]["id"]
        before = client.get("/api/permissions").json()
        after = client.post("/api/models/licence/acknowledge",
                            json={"model_id": model_id}).json()
        assert after["needs_acknowledgement"] is False
        assert client.get("/api/permissions").json() == before


# ------------------------------------------------------- the licence table
def test_every_verified_row_records_who_read_it_and_when() -> None:
    """A verification with no date is not a verification. Publishers
    relicense, and a stale reading has to be visible as one."""
    from uncloud_engine.catalog import VERIFIED_TERMS

    for model_id, terms in VERIFIED_TERMS.items():
        assert terms.verified_on, f"{model_id} claims terms with no date"
        assert terms.verified_by, f"{model_id} claims terms with no source"
        assert terms.url, f"{model_id} states terms with nothing to check them against"


def test_a_model_with_no_row_reports_unread_rather_than_permitted() -> None:
    """Absence from the table is not an omission to be fixed by guessing."""
    from uncloud_engine.catalog import CATALOG, VERIFIED_TERMS

    unlisted = [e for e in CATALOG if e.id not in VERIFIED_TERMS]
    assert unlisted, "the table covers everything; this test has stopped testing"
    for entry in unlisted:
        assert entry.licence.commercial_use == "unverified"


def test_conditions_are_recorded_wherever_a_licence_sets_them() -> None:
    """A condition nobody read is a breach nobody intended."""
    from uncloud_engine.catalog import VERIFIED_TERMS

    for model_id, terms in VERIFIED_TERMS.items():
        if terms.commercial_use == "conditional":
            assert terms.conditions, \
                f"{model_id} is conditional but names no condition"


def test_the_klein_split_is_recorded_because_it_breaks_the_obvious_rule() -> None:
    """Licences split by model SIZE, not family. 'FLUX.2 Klein is Apache-2.0'
    is false as stated, and this is the row that says so."""
    from uncloud_engine.catalog import VERIFIED_TERMS

    assert VERIFIED_TERMS["flux2-klein-4b-mlx"].commercial_use == "allowed"
    assert VERIFIED_TERMS["flux2-klein-9b-mflux-q6"].commercial_use == "forbidden"


def test_the_shipped_notice_file_covers_both_halves_of_the_application() -> None:
    """Generated at build time and checked in, so what a user reads is what was
    actually shipped. Both halves matter: the frontend is bundled into the same
    application, so its dependencies carry the same obligation as the engine's.
    """
    from uncloud_engine.legal import load_notices, summarise

    entries = load_notices()
    assert entries, "run scripts/generate_notices.py"
    kinds = summarise(entries)["by_kind"]
    assert kinds.get("python", 0) > 0 and kinds.get("node", 0) > 0
    assert any(n.name == "react" for n in entries), \
        "the frontend's dependencies are missing from the notices"


def test_a_package_declaring_no_licence_is_recorded_as_unknown() -> None:
    """Not omitted, and not guessed at. An approximated licence reads as
    authoritative, which is worse than an absent one in the document somebody
    checks during due diligence."""
    from uncloud_engine.legal import load_notices

    for notice in load_notices():
        if not notice.licence:
            assert notice.complete is False
            assert notice.to_dict()["licence"] == "not recorded"


# ------------------------------------------------------------------ shipping
def test_the_legal_package_would_be_in_the_built_app() -> None:
    """Both non-Python parts fail SILENTLY when absent: no documents means an
    empty register, which reports nothing outstanding, so a shipped build never
    asks anybody to agree to anything."""
    import json

    conf = json.loads((REPO / "uncloud" / "src-tauri" / "tauri.conf.json").read_text())
    resources = conf["bundle"]["resources"]
    for expected in ("../../sidecar/uncloud_engine/legal/*.py",
                     "../../sidecar/uncloud_engine/legal/documents/*.md",
                     "../../sidecar/uncloud_engine/legal/product/*.md",
                     "../../sidecar/uncloud_engine/integrations/*.py"):
        assert expected in resources, f"{expected} would be absent from the build"
