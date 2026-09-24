"""Write the `latest.json` the built-in updater reads, from a release's signatures.

Run by the release job after every platform's artifacts are collected:

    python scripts/write_updater_manifest.py release v0.4.0 [notes.md]

Signed releases only. With no signatures present it writes nothing and says so
— an unsigned release is still a release, just not one installed apps will
pick up. With SOME signatures present it fails: a manifest missing a platform
would leave those users silently never updated.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY = "UnnamedCoder-568/Uncloud"

#: Tauri target -> the artifact the updater downloads for it. On macOS that is
#: the .app archive, not the .dmg; on Windows and Linux the installer itself.
PLATFORMS = {
    "darwin-aarch64": "Uncloud-macOS-Apple-Silicon.app.tar.gz",
    "windows-x86_64": "Uncloud-Windows-x64.exe",
    "linux-x86_64": "Uncloud-Linux-x64.AppImage",
}


def manifest(folder: Path, tag: str, notes: str = "", platforms: list[str] | None = None) -> dict | None:
    selected = {p: PLATFORMS[p] for p in platforms} if platforms else PLATFORMS
    signed = {platform: folder / f"{artifact}.sig" for platform, artifact in selected.items()}
    present = {p for p, sig in signed.items() if sig.is_file()}
    if not present:
        return None
    missing = sorted(set(selected) - present)
    if missing:
        raise SystemExit(f"Signatures are missing for {', '.join(missing)}. Refusing to publish "
                         "a manifest that would leave those platforms never updated.")
    for artifact in selected.values():
        if not (folder / artifact).is_file():
            raise SystemExit(f"{artifact} is signed but not present.")
    return {
        "version": tag.removeprefix("v"),
        "notes": notes.strip(),
        "pub_date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": {
            platform: {
                "signature": signed[platform].read_text().strip(),
                "url": f"https://github.com/{REPOSITORY}/releases/download/{tag}/{artifact}",
            }
            for platform, artifact in selected.items()
        },
    }


def main(argv: list[str]) -> int:
    folder, tag = Path(argv[1]), argv[2]
    notes = Path(argv[3]).read_text() if len(argv) > 3 and Path(argv[3]).is_file() else ""
    result = manifest(folder, tag, notes, argv[4:] or None)
    if result is None:
        print("No updater signatures in this release; latest.json not written. "
              "Installed apps will not be offered this version.")
        return 0
    (folder / "latest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"Wrote latest.json for {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
