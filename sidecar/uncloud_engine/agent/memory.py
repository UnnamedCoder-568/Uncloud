from __future__ import annotations

import json
import time
from pathlib import Path

MEMORY_DIR = Path.home() / ".uncloud" / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

PLAN_FILE = MEMORY_DIR / "plan.json"
NOTES_FILE = MEMORY_DIR / "notes.json"

STATUSES = ("todo", "doing", "done", "blocked")


def _load(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _save(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2))


# ------------------------------------------------------------------- plan
def plan_set(goal: str, steps: list[str]) -> str:
    """Replace the working plan. Called once, when the agent decides its approach."""
    if not steps:
        raise ValueError("plan_set needs at least one step")
    plan = {
        "goal": goal,
        "created_at": time.time(),
        "steps": [
            {"n": i, "what": s, "status": "todo", "note": ""}
            for i, s in enumerate(steps, 1)
        ],
    }
    _save(PLAN_FILE, plan)
    return plan_show()


def plan_show() -> str:
    plan = _load(PLAN_FILE, None)
    if not plan or not plan.get("steps"):
        return "No plan saved yet. Use plan_set to write one."

    mark = {"todo": "[ ]", "doing": "[~]", "done": "[x]", "blocked": "[!]"}
    lines = [f"GOAL: {plan['goal']}", ""]
    for s in plan["steps"]:
        line = f"  {mark.get(s['status'], '[ ]')} {s['n']}. {s['what']}"
        if s.get("note"):
            line += f"\n        note: {s['note']}"
        lines.append(line)

    done = sum(1 for s in plan["steps"] if s["status"] == "done")
    lines += ["", f"Progress: {done}/{len(plan['steps'])} complete."]
    remaining = [s for s in plan["steps"] if s["status"] in ("todo", "doing")]
    if remaining:
        lines.append(f"Next up: step {remaining[0]['n']} — {remaining[0]['what']}")
    else:
        lines.append("All steps are finished or blocked.")
    return "\n".join(lines)


def plan_update(n: int, status: str, note: str = "") -> str:
    plan = _load(PLAN_FILE, None)
    if not plan:
        raise RuntimeError("No plan saved. Use plan_set first.")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")

    for s in plan["steps"]:
        if s["n"] == n:
            s["status"] = status
            if note:
                s["note"] = note
            _save(PLAN_FILE, plan)
            return plan_show()
    raise ValueError(f"No step numbered {n}. Steps run 1..{len(plan['steps'])}.")


def plan_clear() -> str:
    if PLAN_FILE.exists():
        PLAN_FILE.unlink()
    return "Plan cleared."


# ------------------------------------------------------------------ notes
def note_save(key: str, value: str) -> str:
    """Durable facts discovered mid-task — paths, IDs, findings worth not re-deriving."""
    if not key:
        raise ValueError("note_save needs a 'key'")
    notes = _load(NOTES_FILE, {})
    notes[key] = {"value": value, "at": time.time()}
    _save(NOTES_FILE, notes)
    return f"Saved note '{key}'."


def note_recall(key: str = "") -> str:
    notes = _load(NOTES_FILE, {})
    if not notes:
        return "No notes saved."
    if key:
        entry = notes.get(key)
        if entry:
            return entry["value"]
        return f"No note called '{key}'. Saved keys: {', '.join(notes)}"
    return "\n".join(f"{k}: {v['value'][:300]}" for k, v in notes.items())


def note_clear() -> str:
    if NOTES_FILE.exists():
        NOTES_FILE.unlink()
    return "Notes cleared."
