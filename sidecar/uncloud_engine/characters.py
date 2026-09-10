from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

CHARACTERS_DIR = Path.home() / ".uncloud" / "characters"
CHARACTERS_DIR.mkdir(parents=True, exist_ok=True)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "character"


@dataclass
class Character:
    """A reusable subject profile.

    Two complementary halves, because reference-editing models use them differently:
      * `description` — plain-language traits, injected into prompts. Works everywhere,
        including product shots where the reference slot is taken by the product.
      * `reference.png` — an image of the subject, usable as the reference in Generate
        and Edit, where identity carries far more strongly than text alone.
    """

    slug: str
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: float = 0.0
    has_reference: bool = False

    @property
    def dir(self) -> Path:
        return CHARACTERS_DIR / self.slug

    @property
    def reference_path(self) -> Path:
        return self.dir / "reference.png"

    def to_dict(self) -> dict:
        return {
            "slug": self.slug, "name": self.name, "description": self.description,
            "tags": self.tags, "created_at": self.created_at,
            "has_reference": self.reference_path.exists(),
            "reference_path": str(self.reference_path) if self.reference_path.exists() else None,
        }


def _read(slug: str) -> Character | None:
    meta = CHARACTERS_DIR / slug / "character.json"
    if not meta.exists():
        return None
    try:
        data = json.loads(meta.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return Character(
        slug=slug, name=data.get("name", slug), description=data.get("description", ""),
        tags=data.get("tags", []), created_at=data.get("created_at", 0.0),
    )


def list_characters() -> list[Character]:
    out: list[Character] = []
    for child in sorted(CHARACTERS_DIR.iterdir()) if CHARACTERS_DIR.exists() else []:
        if not child.is_dir():
            continue
        c = _read(child.name)
        if c:
            out.append(c)
    return sorted(out, key=lambda c: c.name.lower())


def get_character(slug: str) -> Character | None:
    return _read(slug)


def save_character(
    name: str, description: str = "", tags: list[str] | None = None,
    reference_source: str | None = None, slug: str | None = None,
) -> Character:
    slug = slug or _slugify(name)
    char = Character(
        slug=slug, name=name.strip() or slug, description=description.strip(),
        tags=tags or [],
        created_at=(_read(slug) or Character(slug, name)).created_at or time.time(),
    )
    char.dir.mkdir(parents=True, exist_ok=True)
    (char.dir / "character.json").write_text(json.dumps({
        "name": char.name, "description": char.description,
        "tags": char.tags, "created_at": char.created_at,
    }, indent=2))

    if reference_source:
        src = Path(reference_source)
        if not src.exists():
            raise FileNotFoundError(f"Reference image not found: {reference_source}")
        shutil.copyfile(src, char.reference_path)

    return char


def delete_character(slug: str) -> bool:
    target = CHARACTERS_DIR / slug
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True
