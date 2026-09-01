"""Browse what has been generated.

Files were always written to disk, but nothing in the app could list them, so
finished work was effectively write-only. This walks the output folder — which
the user chooses — and describes what is in it.
"""

from __future__ import annotations

import time
from pathlib import Path

KINDS = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".mp4": "video", ".mov": "video",
    ".wav": "audio", ".aiff": "audio", ".flac": "audio", ".mp3": "audio",
}


def _describe(p: Path, root: Path) -> dict:
    st = p.stat()
    rel = p.relative_to(root)
    # The first path segment is the engine that wrote it, when there is one.
    group = rel.parts[0] if len(rel.parts) > 1 else KINDS.get(p.suffix.lower(), "other")
    return {
        "path": str(p),
        "name": p.name,
        "relative": str(rel),
        "kind": KINDS.get(p.suffix.lower(), "other"),
        "group": group,
        "size_bytes": st.st_size,
        "modified": st.st_mtime,
        "age_seconds": max(0.0, time.time() - st.st_mtime),
    }


def list_outputs(limit: int = 300, kind: str = "") -> list[dict]:
    """Newest first. Bounded, because this is polled by the UI."""
    from .config import settings

    root = settings.output_dir
    if not root.is_dir():
        return []
    found: list[dict] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.suffix.lower() not in KINDS:
            continue
        try:
            found.append(_describe(p, root))
        except OSError:
            continue
    if kind:
        found = [f for f in found if f["kind"] == kind]
    found.sort(key=lambda f: f["modified"], reverse=True)
    return found[:limit]


def reveal(path: str) -> bool:
    """Show a file in the desktop's file manager.

    A Save button that only tells you a path is not much use; this opens the
    folder with the file selected so it can be dragged somewhere real.
    """
    import subprocess
    import sys

    p = Path(path)
    if not p.exists():
        return False
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(p)], check=False, timeout=10)
        elif sys.platform.startswith("linux"):
            subprocess.run(["xdg-open", str(p.parent)], check=False, timeout=10)
        elif sys.platform == "win32":
            subprocess.run(["explorer", "/select,", str(p)], check=False, timeout=10)
        else:
            return False
        return True
    except Exception:  # noqa: BLE001
        return False


def _unique(target: Path) -> Path:
    """A free filename beside `target`, so saving twice never clobbers."""
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    for n in range(1, 1000):
        candidate = target.with_name(f"{stem}-{n}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Too many files named like {target.name}")


def save_copy(src: str, dest: str, *, into_folder: bool) -> str:
    """Copy a generated file somewhere the user picked, and say where it landed.

    Generated work is written to the output folder as it is made, so this is
    always a copy rather than a move — the original stays where the Outputs
    gallery can find it. `into_folder` distinguishes the two buttons: Save picks
    a folder and keeps the existing name (uniquified rather than overwritten),
    Save As names the file itself, where the system dialog has already asked
    about replacing anything in the way.
    """
    import shutil

    from .config import settings

    root = settings.output_dir.resolve()
    source = Path(src).resolve()
    # Reachable over HTTP: only files this app generated may be copied out.
    if root != source.parent and root not in source.parents:
        raise ValueError("Refusing to copy a file outside the output folder")
    if not source.is_file():
        raise FileNotFoundError(f"No such file: {source}")

    target = Path(dest).expanduser()
    if into_folder:
        target.mkdir(parents=True, exist_ok=True)
        target = _unique(target / source.name)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return str(target)


def delete(path: str) -> bool:
    """Remove one generated file, confined to the output folder.

    The path is checked against the output root rather than trusted: this is
    reachable over HTTP, and an unchecked delete would take any file the engine
    can write.
    """
    from .config import settings

    root = settings.output_dir.resolve()
    p = Path(path).resolve()
    if root not in p.parents:
        raise ValueError("Refusing to delete outside the output folder")
    if not p.is_file():
        return False
    p.unlink()
    return True
