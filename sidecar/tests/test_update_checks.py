"""Uncloud's update checks: when they happen, what they send, what they keep.

Every test injects the fetcher. Nothing here reaches the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uncloud_engine.update_checks import CHECK_EVERY, MANIFEST_URL, UpdateChecks, app_version

MANIFEST = {"product": "uncloud", "items": [
    {"id": "notice", "kind": "announcement", "title": "Read this"},
    {"id": "fix", "kind": "patch", "title": "0.3.1 fixes LTX", "version": "0.3.1"},
    {"id": "old", "kind": "patch", "title": "An older build", "version": "0.2.0"},
    {"id": "urgent", "kind": "hotfix", "severity": "critical", "title": "Update now",
     "version": "9.9.9"},
]}


class Fetcher:
    def __init__(self, payload=MANIFEST) -> None:
        self.payload, self.calls = payload, []

    def __call__(self, url: str):
        self.calls.append(url)
        return self.payload


def checks(tmp_path: Path, fetch: Fetcher) -> UpdateChecks:
    return UpdateChecks(tmp_path / "updates.json", fetch=fetch, version=lambda: "0.3.0")


def test_the_manifest_url_is_https_on_github(tmp_path) -> None:
    assert MANIFEST_URL.startswith("https://raw.githubusercontent.com/UnnamedCoder-568/Uncloud/")


def test_a_check_reports_newer_things_and_drops_older_ones(tmp_path) -> None:
    report = checks(tmp_path, Fetcher()).report(enabled=True)
    assert {i["id"] for i in report["items"]} == {"notice", "fix", "urgent"}
    assert report["critical"][0]["id"] == "urgent"
    assert report["current_version"] == "0.3.0" and report["policy"] == "continuous"


def test_checks_are_spaced_and_disabled_means_no_request(tmp_path, monkeypatch) -> None:
    fetch = Fetcher()
    service = checks(tmp_path, fetch)
    service.report(enabled=False)
    assert fetch.calls == [], "with checks off, nothing may be fetched unasked"
    service.report(enabled=True)
    service.report(enabled=True)
    assert len(fetch.calls) == 1, "a second look inside the interval must not refetch"

    import uncloud_engine.update_checks as module

    real = module.time.time
    monkeypatch.setattr(module.time, "time", lambda: real() + CHECK_EVERY + 1)
    service.report(enabled=True)
    assert len(fetch.calls) == 2


def test_asking_checks_even_when_automatic_checks_are_off(tmp_path) -> None:
    fetch = Fetcher()
    checks(tmp_path, fetch).report(enabled=False, force=True)
    assert len(fetch.calls) == 1


def test_an_unreachable_manifest_keeps_the_last_good_one(tmp_path) -> None:
    fetch = Fetcher()
    service = checks(tmp_path, fetch)
    service.report(enabled=True)
    fetch.payload = None
    report = service.report(enabled=True, force=True)
    assert {i["id"] for i in report["items"]} == {"notice", "fix", "urgent"}


def test_nothing_fetched_yet_says_so_rather_than_erroring(tmp_path) -> None:
    report = checks(tmp_path, Fetcher(payload=None)).report(enabled=True)
    assert report["items"] == [] and "could not be reached" in report["note"]


def test_dismissals_persist_and_critical_notices_come_back(tmp_path) -> None:
    service = checks(tmp_path, Fetcher())
    service.report(enabled=True)
    service.dismiss("notice")
    service.dismiss("urgent")
    again = UpdateChecks(tmp_path / "updates.json", fetch=Fetcher(), version=lambda: "0.3.0")
    ids = {i["id"] for i in again.report(enabled=True)["items"]}
    assert "notice" not in ids and "urgent" in ids


def test_the_running_version_decides_what_is_newer(tmp_path) -> None:
    service = checks(tmp_path, Fetcher())
    assert {i["id"] for i in service.report(enabled=True, version="0.3.1")["items"]} \
        == {"notice", "urgent"}


def test_app_version_comes_from_the_shell(monkeypatch) -> None:
    monkeypatch.setenv("UNCLOUD_APP_VERSION", "0.3.0-test.2")
    assert app_version() == "0.3.0-test.2"


def test_a_checkout_falls_back_to_tauri_conf(monkeypatch) -> None:
    monkeypatch.delenv("UNCLOUD_APP_VERSION", raising=False)
    conf = Path(__file__).resolve().parents[2] / "uncloud" / "src-tauri" / "tauri.conf.json"
    assert app_version() == json.loads(conf.read_text())["version"]


def test_the_published_manifest_is_valid(tmp_path) -> None:
    """The file in the repository, read the way every install reads it."""
    from uncloud_engine.core import updates

    path = Path(__file__).resolve().parents[2] / "updates" / "uncloud.json"
    payload = json.loads(path.read_text())
    report = updates.read(payload, product="uncloud", current_version="0.0.1")
    assert report.note == "" or report.items == ()
    assert payload["product"] == "uncloud"


# ------------------------------------------------------------------ routes
@pytest.fixture
def http(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from uncloud_engine import main
    from uncloud_engine.config import settings

    monkeypatch.setattr(settings, "_data", {})
    monkeypatch.setattr(settings, "_save", lambda: None)
    fetch = Fetcher()
    monkeypatch.setattr(main, "_update_checks", checks(tmp_path, fetch))
    client = TestClient(main.app)
    client.headers.update({"Authorization": f"Bearer {main.settings.token}"})
    return client, fetch


def test_routes_report_dismiss_and_toggle(http) -> None:
    client, fetch = http
    assert {i["id"] for i in client.get("/api/updates").json()["items"]} >= {"notice"}
    after = client.post("/api/updates/dismiss", json={"id": "notice"}).json()
    assert "notice" not in {i["id"] for i in after["items"]}
    assert client.post("/api/settings/check_updates", json={"enabled": False}).json() \
        == {"check_updates": False}
    calls = len(fetch.calls)
    client.post("/api/updates/check")
    assert len(fetch.calls) == calls + 1


def test_a_paired_device_cannot_change_update_settings(http) -> None:
    client, _ = http
    assert client.post("/api/settings/check_updates", json={"enabled": False},
                       headers={"Authorization": ""}).status_code == 403
