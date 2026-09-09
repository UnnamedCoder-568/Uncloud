"""Uncloud's recipes: a saved procedure, run through the ordinary machinery.

A recipe here is a named sequence of steps somebody wrote down because they do
it often — read that spreadsheet, summarise it, draft the mail. The shared part
(identity, trust, storage contract) is `core.recipes`; this is the part that is
Uncloud's, which is what a step IS and what running one means.

Three decisions.

**A step is a capability or a tool, and nothing else.** No conditionals, no
loops, no expressions. The moment a recipe grows control flow it is a
programming language with no debugger, and the thing people actually want — "do
these four things in order, with these arguments" — stops being obvious to
read. Anything more complicated is a skill, which is prose an agent interprets.

**Running one changes nothing about permissions.** Every step goes through
`run_tool`, so a recipe containing a shell command prompts exactly as a shell
command does. A recipe is a shortcut for the user's fingers, never for the
gate — otherwise "save this as a recipe" would become the way to escape being
asked.

**Placeholders are substituted, not evaluated.** `{path}` is replaced with a
parameter's value as a string. There is no expression language, because a
recipe that can compute can be made to compute something its author did not
intend.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from .config import settings
from .core.recipes import Recipe, Store, best_for, now, ranked, record_use

#: `{name}` — a parameter. Deliberately the whole syntax.
_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

#: A recipe long enough to be a program is one nobody can read. This is not a
#: technical limit; it is a design one.
MAX_STEPS = 20


class RecipeError(Exception):
    """Something about the recipe itself is wrong, before anything ran."""

    def __init__(self, message: str, *, remedy: str = "") -> None:
        super().__init__(message)
        self.message, self.remedy = message, remedy

    def to_dict(self) -> dict:
        return {"error": self.message, "remedy": self.remedy}


@dataclass
class Step:
    """One thing a recipe does.

    `capability` and `tool` are alternatives, and exactly one must be set. A
    capability step is the better one to write — it survives changing which
    provider is connected — and a tool step exists because not everything
    Uncloud can do is an integration.
    """

    #: A capability id such as `email.draft`. Preferred.
    capability: str = ""
    #: A tool id such as `fs_read`. Used where no capability covers it.
    tool: str = ""
    arguments: dict = field(default_factory=dict)
    #: Ask this provider specifically. Empty lets the registry choose.
    provider: str = ""
    #: What this step is for, shown while it runs.
    note: str = ""

    def to_dict(self) -> dict:
        return {"capability": self.capability, "tool": self.tool,
                "arguments": dict(self.arguments), "provider": self.provider,
                "note": self.note}

    @classmethod
    def from_dict(cls, raw: dict) -> Step:
        return cls(capability=str(raw.get("capability", "")),
                   tool=str(raw.get("tool", "")),
                   arguments=dict(raw.get("arguments") or {}),
                   provider=str(raw.get("provider", "")),
                   note=str(raw.get("note", "")))


def steps_of(recipe: Recipe) -> list[Step]:
    return [Step.from_dict(s) for s in (recipe.payload.get("steps") or [])]


def parameters_of(recipe: Recipe) -> dict[str, str]:
    """Declared parameters, name → description."""
    return dict(recipe.payload.get("parameters") or {})


# ------------------------------------------------------------------ validity
def check(steps: list[Step], parameters: dict[str, str]) -> list[str]:
    """What is wrong with this recipe, before it is saved.

    Checked at save time rather than at run time, because a recipe that fails
    on its third step has already done two things — and undoing those is not
    something this layer can offer.
    """
    problems: list[str] = []
    if not steps:
        problems.append("A recipe needs at least one step.")
    if len(steps) > MAX_STEPS:
        problems.append(
            f"{len(steps)} steps is more than a recipe should be. Past about "
            f"{MAX_STEPS} it is a program, and a program needs somewhere to "
            f"put the reasoning — that is what a skill is for.")

    from .agent.tools import TOOL_SPECS
    from .core.integrations import Capability

    known_tools = {spec["id"] for spec in TOOL_SPECS}
    known_capabilities = {c.value for c in Capability}

    for number, step in enumerate(steps, start=1):
        if bool(step.capability) == bool(step.tool):
            problems.append(
                f"Step {number} must name exactly one of a capability or a "
                f"tool.")
            continue
        if step.capability and step.capability not in known_capabilities:
            problems.append(
                f"Step {number}: {step.capability!r} is not a capability.")
        if step.tool and step.tool not in known_tools:
            problems.append(f"Step {number}: {step.tool!r} is not a tool.")

        for name in _referenced(step.arguments):
            if name not in parameters and name != "previous":
                problems.append(
                    f"Step {number} uses {{{name}}}, which is not a parameter "
                    f"of this recipe.")
    return problems


def _referenced(value) -> set[str]:
    """Every `{placeholder}` anywhere in a step's arguments."""
    if isinstance(value, str):
        return set(_PLACEHOLDER.findall(value))
    if isinstance(value, dict):
        return set().union(*(_referenced(v) for v in value.values())) \
            if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(_referenced(v) for v in value)) if value else set()
    return set()


def _fill(value, values: dict[str, str]):
    """Substitute placeholders. Substitution only — never evaluation.

    A recipe that could compute could be made to compute something its author
    did not intend, and the useful case is entirely `{path}` and `{previous}`.
    """
    if isinstance(value, str):
        # A whole-string placeholder keeps the value's type, so a step can pass
        # a list of rows through without it becoming a string that looks like
        # one.
        whole = _PLACEHOLDER.fullmatch(value)
        if whole and whole.group(1) in values:
            return values[whole.group(1)]
        return _PLACEHOLDER.sub(
            lambda m: str(values.get(m.group(1), m.group(0))), value)
    if isinstance(value, dict):
        return {k: _fill(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, values) for v in value]
    return value


# ------------------------------------------------------------------- running
@dataclass
class StepResult:
    step: int
    what: str
    ok: bool
    output: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {"step": self.step, "what": self.what, "ok": self.ok,
                "output": self.output[:4000], "error": self.error}


@dataclass
class Run:
    recipe_id: str
    results: list[StepResult] = field(default_factory=list)
    ok: bool = True
    started_at: str = field(default_factory=now)

    def to_dict(self) -> dict:
        return {"recipe_id": self.recipe_id, "ok": self.ok,
                "started_at": self.started_at,
                "results": [r.to_dict() for r in self.results]}


async def run(recipe: Recipe, values: dict[str, str] | None = None, *,
              origin: str = "recipe") -> Run:
    """Execute a recipe's steps in order, stopping at the first failure.

    Every step goes through `run_tool`, which means every step is asked about
    exactly as it would be if a person had typed it. A recipe is a shortcut for
    somebody's fingers, never for the gate.

    Stops rather than continuing, because a later step almost always depends on
    an earlier one and pressing on produces a second, more confusing failure on
    top of the first.
    """
    from .agent.tools import run_tool

    supplied = dict(values or {})
    missing = [name for name in parameters_of(recipe) if name not in supplied]
    if missing:
        raise RecipeError(
            f"{recipe.name} needs {', '.join(missing)}.",
            remedy="Supply every parameter the recipe declares.")

    outcome = Run(recipe_id=recipe.id)
    for number, step in enumerate(steps_of(recipe), start=1):
        what = step.note or step.capability or step.tool
        arguments = _fill(step.arguments, supplied)
        try:
            if step.capability:
                text = await run_tool("capability", {
                    "capability": step.capability, "arguments": arguments,
                    "provider": step.provider}, origin=origin)
            else:
                text = await run_tool(step.tool, arguments, origin=origin)
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            outcome.results.append(StepResult(
                step=number, what=what, ok=False,
                error=f"{type(exc).__name__}: {exc}"))
            outcome.ok = False
            return outcome

        outcome.results.append(StepResult(step=number, what=what, ok=True,
                                          output=text))
        # The one thing a later step can refer to. Named rather than indexed,
        # because `{step_3_output}` in a recipe somebody edits later is a
        # reference that silently breaks when a step moves.
        supplied["previous"] = text

    return outcome


# ------------------------------------------------------------------- storage
class SettingsStore(Store):
    """Recipes in `settings.json`, beside everything else Uncloud keeps.

    A file rather than a database for the same reason the terms acceptances
    are: Uncloud has no application database, and adding one to hold a handful
    of rows would be a second place for state to live.
    """

    def _all(self) -> dict:
        raw = settings._data.get("recipes")
        return dict(raw) if isinstance(raw, dict) else {}

    def _write(self, rows: dict) -> None:
        settings._data["recipes"] = rows
        settings._save()

    def save(self, recipe: Recipe) -> Recipe:
        recipe.updated_at = now()
        rows = self._all()
        rows[recipe.id] = recipe.to_dict()
        self._write(rows)
        return recipe

    def get(self, recipe_id: str) -> Recipe | None:
        raw = self._all().get(recipe_id)
        return _hydrate(raw) if raw else None

    def list(self, *, scope: str = "", subject: str = "") -> list[Recipe]:
        found = [_hydrate(raw) for raw in self._all().values()]
        return ranked([r for r in found
                       if (not scope or r.scope == scope)
                       and (not subject or r.subject == subject)])

    def delete(self, recipe_id: str) -> bool:
        rows = self._all()
        if recipe_id not in rows:
            return False
        del rows[recipe_id]
        self._write(rows)
        return True


def _hydrate(raw: dict) -> Recipe:
    return Recipe(
        id=str(raw.get("id", "")), name=str(raw.get("name", "")),
        description=str(raw.get("description", "")),
        payload=dict(raw.get("payload") or {}),
        scope=str(raw.get("scope", "")), subject=str(raw.get("subject", "")),
        score=float(raw.get("score") or 0.0), uses=int(raw.get("uses") or 1),
        approved=bool(raw.get("approved")),
        created_at=str(raw.get("created_at") or now()),
        updated_at=str(raw.get("updated_at") or now()))


_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = SettingsStore()
    return _store


def create(*, name: str, description: str = "", steps: list[dict],
           parameters: dict[str, str] | None = None,
           subject: str = "") -> Recipe:
    """Write a new recipe, refusing one that could not run."""
    parsed = [Step.from_dict(s) for s in steps]
    declared = dict(parameters or {})
    problems = check(parsed, declared)
    if problems:
        raise RecipeError("; ".join(problems),
                          remedy="Fix the steps and save again.")
    recipe = Recipe(
        id=uuid.uuid4().hex[:12], name=name.strip() or "Untitled",
        description=description, subject=subject, uses=0,
        payload={"steps": [s.to_dict() for s in parsed],
                 "parameters": declared})
    return store().save(recipe)


def update(recipe_id: str, changes: dict) -> Recipe:
    existing = store().get(recipe_id)
    if existing is None:
        raise RecipeError(f"There is no recipe {recipe_id!r}.",
                          remedy="It may have been deleted.")
    if "name" in changes:
        existing.name = str(changes["name"]).strip() or existing.name
    if "description" in changes:
        existing.description = str(changes["description"])
    if "subject" in changes:
        existing.subject = str(changes["subject"])
    if "steps" in changes or "parameters" in changes:
        parsed = [Step.from_dict(s) for s in
                  (changes.get("steps") or existing.payload.get("steps") or [])]
        declared = dict(changes.get("parameters")
                        if "parameters" in changes
                        else parameters_of(existing))
        problems = check(parsed, declared)
        if problems:
            raise RecipeError("; ".join(problems),
                              remedy="Fix the steps and save again.")
        existing.payload = {"steps": [s.to_dict() for s in parsed],
                            "parameters": declared}
    return store().save(existing)


__all__ = ["Recipe", "RecipeError", "Run", "Step", "StepResult", "best_for",
           "check", "create", "parameters_of", "record_use", "run", "steps_of",
           "store", "update"]
