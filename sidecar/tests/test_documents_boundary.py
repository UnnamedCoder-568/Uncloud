"""The documents folder is a security boundary, and this is the fence.

Connecting a folder grants that folder. Everything here is an attempt to reach
outside it, and every one must fail — this file is deliberately adversarial
rather than illustrative, because the interesting cases are the ones nobody
writes by hand.

The case that decides the design is the symlink. Validating the string a caller
supplied catches `../` and misses a link entirely, so resolution happens FIRST
and the check happens on the resolved path. Everything below exists to prove
that ordering holds under every spelling of the same attack.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from uncloud_engine.core.integrations import credentials, documents
from uncloud_engine.core.integrations.contract import IntegrationError


@pytest.fixture
def folder(tmp_path, monkeypatch):
    """A connected folder, with a secret sitting just outside it."""
    root = tmp_path / "docs"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "q1.txt").write_text("inside, and allowed")

    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "secrets.txt").write_text("NOT YOURS")

    monkeypatch.setattr(credentials, "path_of",
                        lambda handle: root if handle == documents.HANDLE else None)
    return root, outside


def refused(relative: str) -> None:
    with pytest.raises(IntegrationError) as raised:
        documents.Documents()._resolve(relative)
    assert "outside the connected folder" in str(raised.value)


# ------------------------------------------------------------------- allowed
def test_the_folder_itself_and_things_in_it_are_reachable(folder) -> None:
    root, _ = folder
    resolver = documents.Documents()
    assert resolver._resolve("") == root.resolve()
    assert resolver._resolve("reports") == (root / "reports").resolve()
    assert resolver._resolve("reports/q1.txt") == (root / "reports" / "q1.txt").resolve()


def test_a_path_that_walks_up_and_back_inside_is_fine(folder) -> None:
    """`reports/../reports/q1.txt` never leaves. Refusing it would be a bug in
    the other direction — the check is about where you end up."""
    root, _ = folder
    resolved = documents.Documents()._resolve("reports/../reports/q1.txt")
    assert resolved == (root / "reports" / "q1.txt").resolve()


# ------------------------------------------------------------------- refused
@pytest.mark.parametrize("attempt", [
    "..",
    "../",
    "../private/secrets.txt",
    "reports/../../private/secrets.txt",
    "./../private/secrets.txt",
    "reports/./../../private/secrets.txt",
    "../../../../../../../../etc/passwd",
    "reports/../..",
])
def test_walking_out_of_the_folder_is_refused(folder, attempt) -> None:
    refused(attempt)


@pytest.mark.parametrize("attempt", [
    "/etc/passwd",
    "/",
])
def test_an_absolute_path_does_not_escape(folder, attempt) -> None:
    """`root / "/etc/passwd"` is `/etc/passwd` in pathlib — the absolute side
    wins and silently discards the root. Anything that joined without checking
    would hand over the file."""
    refused(attempt)


def test_an_absolute_path_to_the_secret_is_refused(folder) -> None:
    _, outside = folder
    refused(str(outside / "secrets.txt"))


def test_a_symlink_pointing_out_of_the_folder_is_refused(folder) -> None:
    """The one an attacker would actually use, and the one a string check
    misses entirely."""
    root, outside = folder
    (root / "shortcut").symlink_to(outside)
    refused("shortcut/secrets.txt")
    refused("shortcut")


def test_a_chain_of_symlinks_is_followed_all_the_way(folder) -> None:
    """One hop is easy to catch. Resolution has to follow the whole chain, or a
    second link is enough to get out."""
    root, outside = folder
    (root / "hop1").symlink_to(outside)
    (root / "hop2").symlink_to(root / "hop1")
    (root / "hop3").symlink_to(root / "hop2")
    refused("hop3/secrets.txt")


def test_a_symlink_to_a_single_file_outside_is_refused(folder) -> None:
    root, outside = folder
    (root / "looks-local.txt").symlink_to(outside / "secrets.txt")
    refused("looks-local.txt")


def test_a_symlink_that_stays_inside_is_allowed(folder) -> None:
    """The fence is about destination, not about links. Refusing every symlink
    would break a legitimate folder somebody organised with them."""
    root, _ = folder
    (root / "shortcut").symlink_to(root / "reports")
    assert documents.Documents()._resolve("shortcut/q1.txt") \
        == (root / "reports" / "q1.txt").resolve()


def test_a_symlink_pointing_at_the_root_itself_is_allowed(folder) -> None:
    root, _ = folder
    (root / "self").symlink_to(root)
    assert documents.Documents()._resolve("self") == root.resolve()


def test_a_sibling_folder_with_a_matching_prefix_is_not_inside(folder) -> None:
    """`/tmp/x/docs-private` starts with `/tmp/x/docs`. A prefix comparison on
    strings would let it through; a parent check does not."""
    root, _ = folder
    sibling = root.parent / f"{root.name}-private"
    sibling.mkdir()
    (sibling / "secrets.txt").write_text("NOT YOURS")
    refused(str(sibling / "secrets.txt"))


def test_a_path_that_does_not_exist_yet_is_still_checked(folder) -> None:
    """Resolution has to work on paths that are not there, or a write would be
    unguarded — which is exactly where it matters most."""
    refused("../private/not-created-yet.txt")


@pytest.mark.skipif(os.name != "posix", reason="POSIX path spellings")
@pytest.mark.parametrize("attempt", [
    "reports//../../private/secrets.txt",
    "reports/././../../private/secrets.txt",
    ".//..//private//secrets.txt",
])
def test_equivalent_spellings_of_the_same_escape_all_fail(folder, attempt) -> None:
    """Doubled separators and redundant `.` segments are the same path to the
    filesystem and a different string to a naive check."""
    refused(attempt)


def test_reading_through_an_escape_never_returns_content(folder) -> None:
    """The boundary tested through the action a caller actually reaches for,
    rather than only through the helper underneath it."""
    root, outside = folder
    (root / "shortcut").symlink_to(outside)
    with pytest.raises(IntegrationError):
        documents.Documents()._read("shortcut/secrets.txt")
    with pytest.raises(IntegrationError):
        documents.Documents()._read("../private/secrets.txt")


def test_listing_through_an_escape_never_reveals_names(folder) -> None:
    root, outside = folder
    (root / "shortcut").symlink_to(outside)
    with pytest.raises(IntegrationError):
        documents.Documents()._list("shortcut")


def test_searching_stays_inside_the_folder(folder) -> None:
    """A search that wandered would leak file NAMES and excerpts, which is most
    of the harm even without a read.

    `rglob` does not currently follow directory symlinks — but that is a
    property of the traversal implementation, it has changed between Python
    versions, and the boundary must not depend on it. The search checks every
    candidate itself, so this test would still pass if rglob started
    recursing.
    """
    root, outside = folder
    (root / "shortcut").symlink_to(outside)
    found = documents.Documents()._search("NOT YOURS")
    assert "secrets.txt" not in found


def test_searching_is_safe_even_if_the_walk_starts_following_links(folder,
                                                                   monkeypatch) -> None:
    """The same guarantee, with the traversal deliberately made hostile."""
    root, outside = folder
    (root / "shortcut").symlink_to(outside)

    real_rglob = Path.rglob

    def following(self, pattern):
        seen = list(real_rglob(self, pattern))
        # What a symlink-following walk would have handed back.
        seen.append(root / "shortcut" / "secrets.txt")
        return seen

    monkeypatch.setattr(Path, "rglob", following)
    assert "secrets.txt" not in documents.Documents()._search("NOT YOURS")
