"""Every engine package must be in the app bundle.

The Tauri resource list names each directory of Python files explicitly, so a
new subpackage is absent from the installed app until somebody remembers to add
a line — and the failure is an ImportError on a user's machine, never in
development, where the files are simply on disk. Uncloud Studio has had this
guard; Uncloud did not, and `core/lan` was the package that would have shipped
missing.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "sidecar" / "uncloud_engine"
CONF = REPO / "uncloud" / "src-tauri" / "tauri.conf.json"


def _resources() -> dict[str, str]:
    return json.loads(CONF.read_text())["bundle"]["resources"]


def test_every_engine_package_is_bundled() -> None:
    resources = _resources()
    missing = []
    for directory in sorted(ENGINE.rglob("*")):
        if not directory.is_dir() or "__pycache__" in directory.parts:
            continue
        if not any(directory.glob("*.py")):
            continue
        rel = directory.relative_to(ENGINE).as_posix()
        if f"../../sidecar/uncloud_engine/{rel}/*.py" not in resources:
            missing.append(rel)
    assert not missing, (
        "these packages would be absent from the built app: " + ", ".join(missing))


def test_the_package_root_is_bundled() -> None:
    assert "../../sidecar/uncloud_engine/*.py" in _resources()


def test_the_native_listener_is_built_and_bundled() -> None:
    """Talking natively needs three things to agree, and nothing else notices
    when one of them is dropped: a Swift source, a build step that compiles it
    on macOS, and a bundle entry that ships it. Miss the build step and the app
    quietly falls back to Whisper — slower, and only on the machines where the
    fast path was the whole point."""
    root = Path(__file__).resolve().parents[2]
    assert (root / "uncloud" / "src-tauri" / "listener" / "main.swift").is_file()
    assert (root / "uncloud" / "scripts" / "build_listener.sh").is_file()

    workflow = (root / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    assert "build_listener.sh" in workflow, "the release build never compiles the listener"

    config = json.loads((root / "uncloud" / "src-tauri" / "tauri.macos.conf.json")
                        .read_text(encoding="utf-8"))
    assert config["bundle"]["resources"].get("binaries/uncloud-listen") == "uncloud-listen"


def test_the_listener_carries_its_own_usage_descriptions() -> None:
    """macOS reads them from the process that asks, and a command-line tool has
    no bundle to read them from: without them the helper is killed on its first
    request, which reaches the user as a crash with no explanation."""
    root = Path(__file__).resolve().parents[2]
    plist = (root / "uncloud" / "src-tauri" / "listener" / "Info.plist").read_text(encoding="utf-8")
    assert "NSSpeechRecognitionUsageDescription" in plist
    assert "NSMicrophoneUsageDescription" in plist
    # And the app, because it is the responsible process when it spawns one.
    app = (root / "uncloud" / "src-tauri" / "Info.plist").read_text(encoding="utf-8")
    assert "NSSpeechRecognitionUsageDescription" in app
