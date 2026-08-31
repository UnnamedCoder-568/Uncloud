"""User-supplied procedures the agent can look up and follow.

A skill is *instructions*, never code. That is a deliberate boundary: the agent
can author a skill when asked, and if skills were executable that would amount
to the agent granting itself arbitrary code execution — every limit on the tool
list would stop meaning anything. Skills describe how to do something; the
existing tools remain the only way anything actually happens.

Layout, one directory per skill so a skill can carry reference files later:

    ~/.uncloud/skills/<slug>/SKILL.md

    ---
    name: Weekly report
    description: How to assemble the Monday summary from the sales sheet.
    ---
    1. Read the sheet at ~/work/sales.csv
    ...
"""

from __future__ import annotations

import re
from pathlib import Path

SKILLS_DIR = Path.home() / ".uncloud" / "skills"
SKILLS_DIR.mkdir(parents=True, exist_ok=True)

MAX_BODY = 20000


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "skill"


def _parse(text: str) -> tuple[dict, str]:
    """Split leading `---` frontmatter from the body. Tolerant: a skill with no
    frontmatter is still a usable skill, it just has no description."""
    meta: dict[str, str] = {}
    body = text
    if text.lstrip().startswith("---"):
        parts = text.lstrip().split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip().lower()] = v.strip()
            body = parts[2]
    return meta, body.strip()


def _read_one(d: Path) -> dict | None:
    f = d / "SKILL.md"
    if not f.is_file():
        return None
    try:
        meta, body = _parse(f.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return {
        "slug": d.name,
        "name": meta.get("name") or d.name.replace("-", " ").title(),
        "description": meta.get("description", ""),
        "body": body,
        "path": str(f),
    }


def all_skills() -> list[dict]:
    if not SKILLS_DIR.is_dir():
        return []
    out = []
    for d in sorted(SKILLS_DIR.iterdir()):
        if d.is_dir():
            s = _read_one(d)
            if s:
                out.append(s)
    return out


def find(name: str) -> dict | None:
    want = _slug(name)
    for s in all_skills():
        if s["slug"] == want or s["name"].lower() == name.strip().lower():
            return s
    return None


# ------------------------------------------------------------------- tools

def skill_list() -> str:
    """Names and one-line descriptions only.

    Deliberately not the bodies: this is what the planner sees, and loading
    every skill's full text into the prompt is exactly the cost that tool
    groups exist to avoid.
    """
    skills = all_skills()
    if not skills:
        return (
            "No skills are installed. Skills live in ~/.uncloud/skills/<name>/SKILL.md "
            "and can be added by the user or written with skill_save."
        )
    lines = [f"{len(skills)} skill(s):"]
    for s in skills:
        lines.append(f"- {s['slug']}: {s['description'] or s['name']}")
    lines.append("\nUse skill_read to get the full instructions for one before following it.")
    return "\n".join(lines)


def skill_read(name: str) -> str:
    if not name.strip():
        raise ValueError("skill_read needs the name of a skill")
    s = find(name)
    if not s:
        known = ", ".join(x["slug"] for x in all_skills()) or "none installed"
        raise ValueError(f"No skill named '{name}'. Available: {known}")
    return f"# {s['name']}\n\n{s['body']}"


def skill_save(name: str, description: str, instructions: str) -> str:
    """Write a skill. Instructions only — this never produces anything runnable."""
    if not name.strip():
        raise ValueError("skill_save needs a name")
    if not instructions.strip():
        raise ValueError("skill_save needs instructions to save")
    body = instructions.strip()[:MAX_BODY]
    slug = _slug(name)
    d = SKILLS_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    front = (
        "---\n"
        f"name: {name.strip()}\n"
        f"description: {description.strip()}\n"
        "---\n\n"
    )
    (d / "SKILL.md").write_text(front + body + "\n", encoding="utf-8")
    return f"Saved skill '{slug}' to {d / 'SKILL.md'}."


def skill_delete(slug: str) -> bool:
    import shutil

    d = SKILLS_DIR / _slug(slug)
    if not d.is_dir():
        return False
    shutil.rmtree(d)
    return True
