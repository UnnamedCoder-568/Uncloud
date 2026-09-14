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
