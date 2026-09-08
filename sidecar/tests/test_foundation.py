"""The shared foundation, and Uncloud's projection into it.

The drift test is the same bargain the design chassis already makes: sharing by
copying is right for something this small, and a copy that has silently
diverged is worse than no sharing, because it still looks maintained.

The rest guard the projection. Uncloud's catalogue was written before there was
a shared vocabulary — it says `category="image"` where the vocabulary says
`image.generate` — so every entry is translated, and a translation that loses a
capability takes a model out of routing with nothing to show for it.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from uncloud_engine import profiles
from uncloud_engine.catalog import CATALOG
from uncloud_engine.foundation import (
    RUNTIMES,
    UNKNOWN_RUNTIME,
    VOCABULARY_VERSION,
    Capability,
    CommercialUse,
    Cost,
    Licence,
    Modality,
    ModelProfile,
    ReasoningSupport,
    fits,
    reasoning_support,
    runtime_profile,
    with_capability,
)

REPO = Path(__file__).resolve().parents[2]
OURS = REPO / "sidecar" / "uncloud_engine" / "foundation"
THEIRS = REPO.parent / "UncloudAdStudio" / "engine" / "adstudio_engine" / "foundation"

FILES = ("__init__.py", "capability.py")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------- drift
def test_the_foundation_declares_itself_shared() -> None:
    text = (OURS / "capability.py").read_text()
    assert "BYTE-IDENTICAL IN BOTH REPOSITORIES" in text


@pytest.mark.skipif(not THEIRS.exists(),
                    reason="Uncloud Studio is not checked out beside this repository")
def test_both_products_carry_the_same_foundation() -> None:
    for name in FILES:
        ours, theirs = OURS / name, THEIRS / name
        assert theirs.exists(), f"{name} is missing from Studio's foundation"
        assert _digest(ours) == _digest(theirs), (
            f"foundation/{name} has drifted between Uncloud and Uncloud Studio.\n"
            f"  ours:   {ours}\n  theirs: {theirs}\n"
            "Copy whichever is correct over the other; do not edit one alone.")


def test_the_foundation_imports_nothing_from_the_product() -> None:
    import ast
    import sys

    allowed = set(sys.stdlib_module_names)
    for name in FILES:
        tree = ast.parse((OURS / name).read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        outside = sorted(imported - allowed - {"__future__"})
        assert not outside, (
            f"foundation/{name} imports {outside}; it must be standard library only")


def test_the_vocabulary_version_is_declared() -> None:
    assert isinstance(VOCABULARY_VERSION, int) and VOCABULARY_VERSION >= 1


# -------------------------------------------------------------- projection
def test_every_catalogue_entry_projects() -> None:
    assert CATALOG, "catalogue is empty; this test would pass vacuously"
    for entry in CATALOG:
        profile = profiles.from_catalog(entry)
        assert profile.id == entry.id
        assert profile.name == entry.name
        assert profile.source == "uncloud"
        assert profile.capabilities, f"{entry.id} projected with no capabilities"


def test_every_catalogue_engine_is_a_known_runtime() -> None:
    unknown = sorted({e.engine for e in CATALOG} - set(RUNTIMES))
    assert not unknown, f"catalogue uses runtimes the foundation has not heard of: {unknown}"


def test_every_engine_the_scanner_can_emit_is_a_known_runtime() -> None:
    """Read from the scanner's source rather than from a disk scan.

    A library scan only finds what this machine happens to hold, so a test
    built on one passes on the developer's laptop and misses the runtime a
    customer has. The set of engine strings the scanner can produce is a fact
    about the code, and that is what is checked.
    """
    import re

    scanner = (Path(__file__).resolve().parents[1]
               / "uncloud_engine" / "library.py").read_text()
    emitted = set(re.findall(r'engine=\"([a-z0-9-]+)\"', scanner))
    emitted |= {m for m in re.findall(r'return \("[a-z-]+", "([a-z0-9-]+)"', scanner)}
    assert emitted, "found no engine strings in the scanner; the pattern has rotted"

    unknown = sorted(emitted - set(RUNTIMES))
    assert not unknown, (
        f"the library scanner can produce runtimes the foundation has never "
        f"heard of: {unknown}. Add them to RUNTIMES with honest transport "
        f"facts rather than letting them fall through to UNKNOWN_RUNTIME.")


def test_an_undescribed_runtime_is_safe_rather_than_absent() -> None:
    """Never None: a caller asking what a runtime accepts always gets an answer
    with the right shape, and every answer is no."""
    unknown = runtime_profile("something-nobody-described")
    assert unknown is UNKNOWN_RUNTIME
    assert unknown.accepts_max_tokens is False
    assert unknown.accepts_temperature is False
    assert unknown.native_tool_calling is False
    assert unknown.streams is False
    # Empty platforms means "anywhere", which is the only field where the safe
    # answer is permissive — refusing to run everywhere would be worse.
    assert unknown.runs_on("darwin-arm64") is True


def test_a_profile_reports_whether_its_runtime_is_described() -> None:
    assert ModelProfile(id="a", name="A", runtime="gguf").runtime_known is True
    assert ModelProfile(id="b", name="B", runtime="mystery").runtime_known is False
    assert ModelProfile(id="b", name="B", runtime="mystery").runtime_profile \
        is UNKNOWN_RUNTIME


def test_an_unmapped_category_raises_rather_than_defaulting() -> None:
    """A model silently projected as text would be offered for jobs it cannot
    do, and the failure would surface as a confusing generation error rather
    than as the missing mapping it is."""
    with pytest.raises(profiles.UnknownCategory):
        profiles.capabilities_for("holograms", None)


def test_image_capabilities_come_from_the_entrys_own_tags() -> None:
    assert profiles.capabilities_for("image", ["text2img"]) == \
        frozenset({Capability.IMAGE_GENERATE})
    assert profiles.capabilities_for("image", ["edit", "reference"]) == \
        frozenset({Capability.IMAGE_EDIT})
    # No tags at all is the catalogue's own default, not an inference.
    assert profiles.capabilities_for("image", None) == \
        frozenset({Capability.IMAGE_GENERATE})


def test_a_text_encoder_is_not_offered_as_a_model_to_run() -> None:
    """It is a part another model needs. Projecting it as an image model is how
    it ends up in a picker."""
    caps = profiles.capabilities_for("component", None)
    assert caps == frozenset({Capability.TEXT_ENCODE})
    assert Capability.IMAGE_GENERATE not in caps


def test_a_vision_model_reports_that_it_can_be_shown_a_picture() -> None:
    caps = profiles.capabilities_for("text", None)
    assert Modality.IMAGE in profiles.inputs_for("mlx-vlm", caps)
    assert Modality.IMAGE not in profiles.inputs_for("gguf", caps)


def test_transcription_takes_audio_rather_than_text() -> None:
    caps = profiles.capabilities_for("voice-stt", None)
    assert profiles.inputs_for("faster-whisper", caps) == frozenset({Modality.AUDIO})


# ----------------------------------------------------------------- licence
def test_no_catalogue_entry_claims_a_verified_licence() -> None:
    """Uncloud's catalogue carries no licence data — thirty-odd entries, none
    with terms. Every projection must therefore say UNVERIFIED, and UNVERIFIED
    must never be rendered as permission.

    This test is expected to change when licence data is populated. It exists
    so that the gap is a recorded fact rather than an assumption somebody makes
    while reading the code.
    """
    for entry in CATALOG:
        licence = profiles.from_catalog(entry).licence
        assert licence.commercial_use is CommercialUse.UNVERIFIED
        assert licence.verified is False
        assert licence.needs_disclosure is True


def test_a_projected_entry_still_points_at_its_publisher() -> None:
    """Until terms are recorded, the repository is where a person goes to read
    them. Losing that would leave nothing to check against."""
    entry = CATALOG[0]
    assert profiles.from_catalog(entry).licence.url.endswith(entry.repo)


def test_an_unread_licence_is_never_read_as_permission() -> None:
    assert Licence().commercial_use is CommercialUse.UNVERIFIED
    assert Licence().needs_disclosure is True
    assert Licence(commercial_use=CommercialUse.ALLOWED,
                   verified_on="2026-09-02").needs_disclosure is False


# ------------------------------------------------------------------ effort
def test_reasoning_support_is_recognised_rather_than_guessed() -> None:
    assert reasoning_support("qwen3-1.7b") is ReasoningSupport.THINKING_TOGGLE
    assert reasoning_support("llama-3.1-8b-instruct-gguf") is ReasoningSupport.NONE


def test_a_catalogue_qwen3_reports_its_reasoning_control() -> None:
    qwen3 = [e for e in CATALOG if "qwen3" in e.id.lower()]
    if not qwen3:
        pytest.skip("no Qwen3 in the catalogue")
    assert profiles.from_catalog(qwen3[0]).reasoning is ReasoningSupport.THINKING_TOGGLE


def test_runtimes_report_what_they_accept() -> None:
    """Effort translation works against these, so a wrong answer here is a
    parameter sent to a runtime that will reject it."""
    assert RUNTIMES["gguf"].accepts_max_tokens is True
    assert RUNTIMES["gguf"].streams is True
    assert RUNTIMES["mflux"].accepts_max_tokens is False
    assert RUNTIMES["mlx"].runs_on("darwin-arm64") is True
    assert RUNTIMES["mlx"].runs_on("linux-x86_64") is False
    assert RUNTIMES["gguf"].runs_on("linux-x86_64") is True


# ----------------------------------------------------------------- routing
def test_routing_only_offers_what_is_installed_and_runnable() -> None:
    ready = ModelProfile(id="ready", name="Ready", installed=True, runnable=True,
                         capabilities=frozenset({Capability.TEXT_GENERATE}),
                         cost=Cost(weights_gb=4.0, working_gb=1.0))
    absent = ModelProfile(id="absent", name="Absent", installed=False, runnable=True,
                          capabilities=frozenset({Capability.TEXT_GENERATE}))
    assert [p.id for p in with_capability([ready, absent], Capability.TEXT_GENERATE)] \
        == ["ready"]


def test_fitting_uses_peak_not_total() -> None:
    staged = ModelProfile(
        id="v", name="V",
        cost=Cost(weights_gb=20.0, working_gb=4.0, encoder_gb=15.0, staged=True))
    assert staged.cost.total_gb == 24.0
    assert staged.cost.peak_gb == 15.0
    assert fits(staged, 19.0) is True


def test_the_whole_catalogue_projects_without_a_machine() -> None:
    """No weights touched, no runtime imported, nothing downloaded."""
    made = profiles.catalogue_profiles()
    assert len(made) == len(CATALOG)
    assert all(p.source == "uncloud" for p in made)
