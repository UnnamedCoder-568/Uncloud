"""The release side of updating: the manifest the updater reads, and the job
that builds it.

A release is the one place a mistake reaches every installed copy at once, so
the rules are pinned here rather than remembered: no partial manifests, signed
or nothing, and a publish step that matches what the build matrix produces.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = (REPO / ".github" / "workflows" / "build.yml").read_text()


def _script():
    spec = importlib.util.spec_from_file_location(
        "write_updater_manifest", REPO / "scripts" / "write_updater_manifest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release(tmp_path: Path, *, signed: set[str]) -> Path:
    script = _script()
    for platform, artifact in script.PLATFORMS.items():
        (tmp_path / artifact).write_bytes(b"installer")
        if platform in signed:
            (tmp_path / f"{artifact}.sig").write_text(f"sig-for-{platform}\n")
    return tmp_path


def test_an_unsigned_release_writes_no_manifest(tmp_path: Path) -> None:
    assert _script().manifest(_release(tmp_path, signed=set()), "v0.4.0") is None


def test_a_partly_signed_release_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="linux-x86_64"):
        _script().manifest(_release(tmp_path, signed={"darwin-aarch64", "windows-x86_64"}),
                           "v0.4.0")


def test_a_signed_release_names_every_platform_and_this_tag(tmp_path: Path) -> None:
    script = _script()
    result = script.manifest(_release(tmp_path, signed=set(script.PLATFORMS)), "v0.4.0", "Notes")
    assert result["version"] == "0.4.0" and result["notes"] == "Notes"
    assert set(result["platforms"]) == {"darwin-aarch64", "windows-x86_64", "linux-x86_64"}
    mac = result["platforms"]["darwin-aarch64"]
    assert mac["signature"] == "sig-for-darwin-aarch64"
    assert mac["url"] == ("https://github.com/UnnamedCoder-568/Uncloud/releases/download/"
                          "v0.4.0/Uncloud-macOS-Apple-Silicon.app.tar.gz")
    json.dumps(result)


def test_the_app_and_the_release_agree_on_where_updates_live() -> None:
    rust = (REPO / "uncloud" / "src-tauri" / "src" / "updates.rs").read_text()
    assert "UnnamedCoder-568/Uncloud/releases/latest/download/latest.json" in rust
    assert _script().REPOSITORY == "UnnamedCoder-568/Uncloud"


def test_the_publish_step_no_longer_expects_the_withdrawn_intel_build() -> None:
    """It asserted four checksums and named the Intel .dmg with
    fail_on_unmatched_files after Intel left the matrix."""
    assert "Intel.dmg" not in WORKFLOW
    assert "-eq 4" not in WORKFLOW
    for installer in ("Uncloud-Windows-x64.exe", "Uncloud-Linux-x64.AppImage",
                      "Uncloud-macOS-Apple-Silicon.dmg"):
        assert installer in WORKFLOW


def test_updater_artifacts_need_both_halves_of_the_key() -> None:
    assert "TAURI_SIGNING_PRIVATE_KEY" in WORKFLOW
    assert "updater-pubkey.txt" in WORKFLOW
    assert '"createUpdaterArtifacts":true' in WORKFLOW
    assert "write_updater_manifest.py" in WORKFLOW


def test_no_private_key_is_ever_committed() -> None:
    for path in (REPO / "uncloud" / "src-tauri").glob("*.key"):
        pytest.fail(f"a private key file is in the repository: {path}")
    pubkey = (REPO / "uncloud" / "src-tauri" / "updater-pubkey.txt").read_text()
    assert "PRIVATE" not in pubkey.upper()
