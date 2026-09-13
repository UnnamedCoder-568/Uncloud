"""Update manifests: what gets shown, and everything that must not.

The dangerous shape here is not the feature, it is the trust. An installed
application that fetches something and acts on it is one bad server away from
being a remote execution hole, so most of these tests are about what a
manifest CANNOT make the application do.

The other half is the distinction the whole thing exists for: an announcement
is not an update, and telling somebody Studio 2 exists must never be capable
of turning their Studio 1 into it.
"""

from __future__ import annotations

from datetime import date, timedelta

from uncloud_engine.core import updates
from uncloud_engine.core.updates import Kind, Version


def manifest(*items, product="uncloud", **extra) -> dict:
    return {"product": product, "items": list(items), **extra}


def entry(**over) -> dict:
    base = {"id": "x", "kind": "patch", "title": "A fix", "version": "9.9.9"}
    return {**base, **over}


# ------------------------------------------------------------------ versions
def test_the_versions_both_products_actually_ship_can_be_read() -> None:
    """A parser that rejected these would refuse to tell somebody about the
    very build they are running."""
    for text in ("0.2.0", "0.3.0-test.2", "0.3.0rc2", "v1.4.1", "2.0"):
        assert Version.parse(text) is not None, text


def test_a_prerelease_is_older_than_the_release_it_precedes() -> None:
    assert Version.parse("0.3.0-test.2") < Version.parse("0.3.0")
    assert Version.parse("0.3.0") < Version.parse("0.3.1")
    assert Version.parse("0.3.0-test.1") < Version.parse("0.3.0-test.2")


def test_nonsense_is_not_a_version() -> None:
    for text in ("", "latest", "../../etc", None, "1.2.3; rm -rf /"):
        assert Version.parse(text) is None, text


# ------------------------------------------------- what a manifest cannot do
def test_an_item_cannot_walk_the_user_backwards() -> None:
    """The downgrade attack in its simplest form: replay an old manifest and
    call an older build an update."""
    report = updates.read(manifest(entry(version="0.1.0")),
                          product="uncloud", current_version="0.3.0")
    assert report.items == ()


def test_the_running_version_is_not_offered_to_itself() -> None:
    report = updates.read(manifest(entry(version="0.3.0")),
                          product="uncloud", current_version="0.3.0")
    assert report.items == ()


def test_a_link_to_somewhere_we_do_not_control_is_stripped() -> None:
    """The URL is shown to a person, never opened by the application — but a
    compromised manifest must not be able to put an arbitrary site behind our
    interface's button either."""
    report = updates.read(
        manifest(entry(url="https://evil.example.com/installer.dmg")),
        product="uncloud", current_version="0.1.0")
    assert report.items[0].url == ""


def test_a_plaintext_link_is_stripped_even_on_a_trusted_host() -> None:
    report = updates.read(manifest(entry(url="http://github.com/x/y")),
                          product="uncloud", current_version="0.1.0")
    assert report.items[0].url == ""


def test_a_trusted_release_link_survives() -> None:
    report = updates.read(
        manifest(entry(url="https://github.com/UnnamedCoder-568/Uncloud/releases")),
        product="uncloud", current_version="0.1.0")
    assert report.items[0].url.endswith("/releases")


def test_a_manifest_for_another_product_is_ignored() -> None:
    report = updates.read(manifest(entry(), product="something-else"),
                          product="uncloud", current_version="0.1.0")
    assert report.items == () and "different product" in report.note


def test_one_malformed_item_does_not_cost_the_others() -> None:
    report = updates.read(
        manifest({"garbage": True}, entry(id="good", title="Real"),
                 {"kind": "patch"}),
        product="uncloud", current_version="0.1.0")
    assert [i.id for i in report.items] == ["good"]


def test_rubbish_where_the_manifest_should_be_changes_nothing() -> None:
    for payload in ("<html>not json</html>", None, [], 42):
        report = updates.read(payload, product="uncloud", current_version="0.1.0")
        assert report.items == ()
        assert report.note, "silence needs a reason, even an internal one"


def test_an_unreadable_running_version_reports_rather_than_raises() -> None:
    report = updates.read(manifest(entry()), product="uncloud",
                          current_version="not-a-version")
    assert report.items == () and report.note


# ------------------------------------------- announcement is not an update
def test_a_major_announcement_never_replaces_the_installation() -> None:
    """Studio 1 being told Studio 2 exists must not be capable of becoming
    Studio 2. For a paid application that is the difference between an upgrade
    and a seizure."""
    report = updates.read(
        manifest(entry(id="studio2", kind="major_announcement",
                       title="Uncloud Studio 2 is available", version="2.0.0")),
        product="uncloud", current_version="1.4.1")

    item = report.items[0]
    assert item.kind is Kind.MAJOR_ANNOUNCEMENT
    assert item.is_application_update is False
    assert item.replaces_installation is False


def test_a_major_announcement_is_shown_even_though_it_names_a_new_version() -> None:
    report = updates.read(
        manifest(entry(id="s2", kind="major_announcement", version="2.0.0")),
        product="uncloud", current_version="1.9.9")
    assert len(report.items) == 1


def test_runtime_and_model_updates_do_not_ask_for_a_new_application() -> None:
    """The whole reason these exist: a production fix reaches users without
    waiting for a release."""
    report = updates.read(
        manifest(entry(id="rt", kind="runtime", title="Improved video memory",
                       version=None),
                 entry(id="md", kind="model", title="New model build",
                       version=None)),
        product="uncloud", current_version="0.3.0")
    assert {i.id for i in report.items} == {"rt", "md"}
    assert all(not i.is_application_update for i in report.items)


# ----------------------------------------------------------------- targeting
def test_an_item_can_be_aimed_at_a_range_of_builds() -> None:
    only_old = entry(id="old", appliesTo="1.3.0")
    report = updates.read(manifest(only_old), product="uncloud",
                          current_version="1.4.0")
    assert report.items == ()

    reaches = updates.read(manifest(only_old), product="uncloud",
                           current_version="1.2.0")
    assert len(reaches.items) == 1


def test_an_expired_item_stops_being_shown_without_anyone_withdrawing_it() -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    report = updates.read(manifest(entry(expires=yesterday)),
                          product="uncloud", current_version="0.1.0")
    assert report.items == ()


def test_an_item_expiring_later_is_still_shown() -> None:
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    report = updates.read(manifest(entry(expires=tomorrow)),
                          product="uncloud", current_version="0.1.0")
    assert len(report.items) == 1


# --------------------------------------------------------------- dismissal
def test_something_dismissed_stays_dismissed() -> None:
    report = updates.read(manifest(entry(id="seen")), product="uncloud",
                          current_version="0.1.0", dismissed={"seen"})
    assert report.items == ()


def test_a_critical_item_comes_back_anyway() -> None:
    """The only reason the flag exists. A security fix somebody clicked away
    on Monday is still a security fix on Friday."""
    report = updates.read(
        manifest(entry(id="sec", kind="hotfix", severity="critical")),
        product="uncloud", current_version="0.1.0", dismissed={"sec"})
    assert len(report.items) == 1
    assert report.items[0].dismissible is False


def test_critical_items_are_listed_first() -> None:
    report = updates.read(
        manifest(entry(id="a", title="Ordinary"),
                 entry(id="b", title="Urgent", severity="critical")),
        product="uncloud", current_version="0.1.0")
    assert [i.id for i in report.items] == ["b", "a"]
    assert [i.id for i in report.critical] == ["b"]


# ------------------------------------------------------ minimum supported
def test_a_build_below_the_floor_is_told_so_separately() -> None:
    """A statement about this install, not an item in a list — so an interface
    can treat it differently from "there is a new version"."""
    report = updates.read(
        manifest(entry(), minimumSupportedVersion="1.0.0"),
        product="uncloud", current_version="0.9.0")
    assert report.unsupported is True


def test_a_supported_build_is_not_flagged() -> None:
    report = updates.read(
        manifest(entry(), minimumSupportedVersion="0.1.0"),
        product="uncloud", current_version="0.9.0")
    assert report.unsupported is False


def test_a_report_serialises_for_an_interface() -> None:
    report = updates.read(manifest(entry(severity="recommended")),
                          product="uncloud", current_version="0.1.0")
    row = report.to_dict()
    assert row["items"][0]["kind"] == "patch"
    assert row["items"][0]["severity"] == "recommended"
    assert row["items"][0]["replaces_installation"] is True
