"""Copy Uncloud Core into Uncloud Studio, or report what has drifted.

Core is shared by COPYING rather than by packaging, and that stays a deliberate
decision: the two products ship as separate applications from separate
repositories, and a published package would mean a release cycle between
noticing a problem and fixing it in the product that has it.

What that trade costs is discipline, and discipline does not scale by hand —
which is what this script and the drift test are for. Editing one copy and
forgetting the other is the failure mode, so the test fails loudly and the fix
is one command.

    python scripts/sync_core.py --check     # what has drifted
    python scripts/sync_core.py             # copy ours over theirs

Two things are deliberately NOT shared, and the exclusions are the interesting
part of this file:

* `legal/documents/third-party.json` — generated from each application's own
  dependency tree. Identical files here would mean one of them was lying about
  what it ships.
* `legal/product/` — Studio's supplement is about activation and advertising;
  Uncloud's is about an agent that can run shell commands. Neither belongs in
  the other.
"""

from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OURS = HERE.parent / "uncloud_engine" / "core"
THEIRS = (HERE.parent.parent.parent / "UncloudAdStudio" / "engine"
          / "adstudio_engine" / "core")

#: Paths, relative to core/, that each product owns for itself.
EXCLUDED = ("legal/documents/third-party.json", "legal/product")


def shared_files(root: Path) -> list[Path]:
    out = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        if any(relative == e or relative.startswith(f"{e}/") for e in EXCLUDED):
            continue
        out.append(path.relative_to(root))
    return out


def differences() -> tuple[list[Path], list[Path]]:
    """(differing, missing) — as relative paths under core/."""
    differing, missing = [], []
    for relative in shared_files(OURS):
        theirs = THEIRS / relative
        if not theirs.exists():
            missing.append(relative)
        elif not filecmp.cmp(OURS / relative, theirs, shallow=False):
            differing.append(relative)
    return differing, missing


def main(argv: list[str]) -> int:
    if not THEIRS.parent.exists():
        print("Uncloud Studio is not checked out beside this repository; "
              "nothing to sync.", file=sys.stderr)
        return 0

    differing, missing = differences()
    if "--check" in argv:
        for relative in missing:
            print(f"missing from Studio: core/{relative}")
        for relative in differing:
            print(f"drifted:             core/{relative}")
        if differing or missing:
            print(f"\n{len(differing) + len(missing)} file(s) out of step. "
                  f"Run `python scripts/sync_core.py` after checking which "
                  f"copy is correct.")
            return 1
        print(f"Core is identical in both products "
              f"({len(shared_files(OURS))} files).")
        return 0

    for relative in [*differing, *missing]:
        target = THEIRS / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(OURS / relative, target)
        print(f"copied core/{relative}")
    if not differing and not missing:
        print("Nothing to copy; Core is already identical.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
