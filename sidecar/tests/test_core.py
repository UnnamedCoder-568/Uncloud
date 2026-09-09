"""Uncloud Core: what is shared, and the boundaries that keep it shareable.

Core is the layer both products are built on — model vocabulary, permissions,
approvals, effort, evaluation, legal state, and the integration framework. It is
shared by COPYING, byte for byte, and these tests are the discipline that makes
that safe.

The previous version of this file checked two of the five foundation modules by
name. Nothing had drifted, but three files were unguarded for weeks, and a list
of filenames is exactly the thing nobody updates when they add a module. This
walks the tree instead, so a new file is covered the moment it exists.

The other tests here are about DIRECTION. Core may be imported by a product;
Core may never import one. That is what lets the same bytes run under two
applications with different databases, different config locations and different
ways of asking a person a question.
"""

from __future__ import annotations

import ast
import filecmp
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
OURS = REPO / "sidecar" / "uncloud_engine" / "core"
THEIRS = (REPO.parent / "UncloudAdStudio" / "engine" / "adstudio_engine" / "core")

sys.path.insert(0, str(REPO / "sidecar" / "scripts"))


def core_modules() -> list[Path]:
    return sorted(p for p in OURS.rglob("*.py") if "__pycache__" not in p.parts)


def imports_of(path: Path) -> set[str]:
    """Top-level module names an absolute import reaches for.

    Relative imports are excluded on purpose: `from ..permission import Risk`
    is Core importing Core, which is exactly what it should do. What matters is
    whether it reaches for something absolute that only exists in a product.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


# --------------------------------------------------------------------- drift
def test_the_whole_core_tree_is_identical_in_both_products() -> None:
    """Walked rather than listed. A filename list is the thing nobody updates
    when they add a module, and an unguarded shared file is one somebody edits
    on one side only."""
    if not THEIRS.parent.exists():
        pytest.skip("Uncloud Studio is not checked out beside this repository")

    from sync_core import differences, shared_files

    differing, missing = differences()
    assert not missing, (
        "these Core files are missing from Uncloud Studio: "
        + ", ".join(str(m) for m in missing)
        + "\nRun: python scripts/sync_core.py")
    assert not differing, (
        "Core has drifted between the products: "
        + ", ".join(str(d) for d in differing)
        + "\nCheck which copy is correct, then run: python scripts/sync_core.py")
    assert len(shared_files(OURS)) >= 16, "the shared set shrank unexpectedly"


def test_the_files_each_product_owns_are_not_forced_to_match() -> None:
    """Two exclusions, and both would be lies if shared.

    The notice file is generated from each application's own dependency tree —
    identical copies would mean one of them was misdescribing what it ships.
    The product supplement is about activation and advertising in one case and
    an agent with shell access in the other.
    """
    if not THEIRS.parent.exists():
        pytest.skip("Uncloud Studio is not checked out beside this repository")

    ours = OURS / "legal" / "documents" / "third-party.json"
    theirs = THEIRS / "legal" / "documents" / "third-party.json"
    if ours.is_file() and theirs.is_file():
        assert not filecmp.cmp(ours, theirs, shallow=False), (
            "both products claim the same third-party dependencies, which "
            "cannot be true — one of the notice files is stale")

    assert (OURS / "legal" / "product" / "uncloud-supplemental.md").is_file()
    assert (THEIRS / "legal" / "product" / "studio-supplemental.md").is_file()


# ----------------------------------------------------------------- direction
def test_core_never_imports_a_product() -> None:
    """The rule that makes the same bytes runnable under both applications.

    Core reaching into `uncloud_engine.agent` or `adstudio_engine.projects`
    would compile in one repository and fail in the other — and the failure
    would land on whoever synced next, not on whoever wrote it.
    """
    forbidden = {"uncloud_engine", "adstudio_engine", "agent", "projects",
                 "orchestrator", "campaigns", "assets", "autoengine",
                 "licensing", "commerce", "providers", "runtimes", "training"}
    for path in core_modules():
        reached = imports_of(path) & forbidden
        assert not reached, (
            f"core/{path.relative_to(OURS)} imports {sorted(reached)} — Core "
            f"may be imported BY a product, never the other way round")


def test_core_declares_what_it_is() -> None:
    for name in ("capability.py", "permission.py"):
        assert "BYTE-IDENTICAL IN BOTH REPOSITORIES" in (OURS / name).read_text()


def test_the_vocabulary_and_the_rules_stay_standard_library_only() -> None:
    """The modules everything else is defined in terms of.

    Adapters may need a client library; the vocabulary must not. A dependency
    here is a dependency in both products, forever, and in whatever runs Core
    next.
    """
    allowed = set(sys.stdlib_module_names)
    for name in ("capability.py", "permission.py", "effort.py", "evaluation.py",
                 "legal/terms.py", "legal/disclosure.py", "legal/notices.py"):
        outside = imports_of(OURS / name) - allowed
        assert not outside, f"core/{name} depends on {sorted(outside)}"


def test_consent_and_permission_never_import_each_other() -> None:
    """Agreeing to terms is not granting an agent permission to run a shell
    command, and one must never be able to satisfy the other. Structural,
    because 'remember not to' is not a mechanism."""
    for name in ("terms.py", "disclosure.py", "notices.py", "__init__.py"):
        assert "permission" not in imports_of(OURS / "legal" / name), \
            f"core/legal/{name} imports the permission gate"
    assert "legal" not in imports_of(OURS / "permission.py"), \
        "the permission gate imports the legal core"


def test_nothing_in_core_assumes_which_application_is_running_it() -> None:
    """Core cannot know where a product keeps its state or how it asks a
    person a question, so both are injected. This caught two real faults when
    the integration framework moved in: a hard-coded `~/.uncloud` and an
    import of Uncloud's own approval module."""
    text = (OURS / "integrations" / "credentials.py").read_text()
    assert "def configure(" in text, \
        "the credential store must be pointed at the product's own directory"
    text = (OURS / "integrations" / "registry.py").read_text()
    assert "def install_approver(" in text, \
        "the approval round trip belongs to the product, not to Core"
