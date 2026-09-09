"""Recipes: a saved way of doing something, and the part both products share.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

The two products mean genuinely different things by the word, and this module
is deliberately the small honest intersection rather than a unification.

* **Studio's** recipes are settings that worked — a rank, a step count, a
  prompt shape that held a product's identity. They are LEARNED, scored, and
  consulted while planning a render.
* **Uncloud's** are procedures — read that spreadsheet, summarise it, draft the
  mail. They are WRITTEN, executed, and produce a result.

Forcing one shape onto both would make Studio's recipes carry an empty step
list and Uncloud's carry a meaningless score. What they actually share is
identity, provenance and trust: a name, when it was made, how often it has been
reached for, whether a person approved it, and how much weight that earns. That
is what lives here, and it is enough for one storage contract and one set of
rules about trust.

**Nothing here executes anything.** A recipe that could run itself would be a
second execution path, and the whole point is that a recipe's steps go through
the same tools, the same permission gate and the same approvals as anything
else. Execution belongs to each product, on top of this.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Recipe:
    """What both products agree a recipe is.

    `payload` is the part each product owns: Studio puts settings in it,
    Uncloud puts steps. Kept opaque here on purpose — the moment Core starts
    interpreting it, Core has opinions about creative pipelines.
    """

    id: str
    name: str
    #: What this is for, in the user's words. The one field that makes a list
    #: of saved recipes usable six weeks later.
    description: str = ""
    #: Free-form, owned by whichever product wrote it.
    payload: dict = field(default_factory=dict)
    #: Grouping, so "recipes for this project" is answerable without a second
    #: table. Empty means it belongs to the installation rather than to a
    #: project.
    scope: str = ""
    #: What it applies to — a task name, a product id, a capability. Products
    #: decide the vocabulary; Core only matches on it.
    subject: str = ""
    #: 0..1 where a product measured one. Absent is 0 and means unscored, not
    #: bad — see `weight`.
    score: float = 0.0
    #: How many times it has been reached for again.
    uses: int = 1
    #: Whether a person said this one was right.
    approved: bool = False
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)

    @property
    def weight(self) -> float:
        """How much this should be trusted, relative to its alternatives.

        Approval outranks score, and repetition outranks both up to a point. A
        recipe a person approved once is better evidence than one that merely
        scored well; one that has held up across five uses is better than
        either. The repetition bonus is capped because a recipe used fifty
        times is not five times better than one used ten.
        """
        return (self.score
                + (0.25 if self.approved else 0.0)
                + min(0.25, 0.05 * max(0, self.uses - 1)))

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name,
                "description": self.description, "payload": dict(self.payload),
                "scope": self.scope, "subject": self.subject,
                "score": round(self.score, 3), "uses": self.uses,
                "approved": self.approved, "weight": round(self.weight, 3),
                "created_at": self.created_at, "updated_at": self.updated_at}


class Store:
    """Where recipes live. Implemented by each product.

    An interface rather than a table: Studio keeps them per project in SQLite,
    Uncloud keeps them beside its settings, and a shared package that opened
    its own database would be a third place for state to be.
    """

    def save(self, recipe: Recipe) -> Recipe:  # pragma: no cover
        raise NotImplementedError

    def get(self, recipe_id: str) -> Recipe | None:  # pragma: no cover
        raise NotImplementedError

    def list(self, *, scope: str = "", subject: str = "") -> list[Recipe]:  # pragma: no cover
        raise NotImplementedError

    def delete(self, recipe_id: str) -> bool:  # pragma: no cover
        raise NotImplementedError


class Memory(Store):
    """An in-process store. Used by tests, and by nothing else."""

    def __init__(self) -> None:
        self._by_id: dict[str, Recipe] = {}

    def save(self, recipe: Recipe) -> Recipe:
        recipe.updated_at = now()
        self._by_id[recipe.id] = recipe
        return recipe

    def get(self, recipe_id: str) -> Recipe | None:
        return self._by_id.get(recipe_id)

    def list(self, *, scope: str = "", subject: str = "") -> list[Recipe]:
        return ranked([r for r in self._by_id.values()
                       if (not scope or r.scope == scope)
                       and (not subject or r.subject == subject)])

    def delete(self, recipe_id: str) -> bool:
        return self._by_id.pop(recipe_id, None) is not None


def ranked(recipes: list[Recipe]) -> list[Recipe]:
    """Most trusted first, then most recent.

    The tie-break matters more than it looks: two unscored recipes both weigh
    zero, and returning them in insertion order would put the oldest draft
    above the one somebody wrote this morning.
    """
    return sorted(recipes, key=lambda r: (-r.weight, r.updated_at), reverse=False)


def best_for(recipes: list[Recipe], subject: str = "") -> Recipe | None:
    """The one to reach for, preferring a match on the subject.

    A recipe for THIS product beats a general one that merely scored higher,
    because specificity is evidence that a score cannot supply.
    """
    if subject:
        specific = ranked([r for r in recipes if r.subject == subject])
        if specific:
            return specific[0]
    general = ranked([r for r in recipes if not r.subject])
    return general[0] if general else None


def record_use(recipe: Recipe, *, score: float | None = None,
               approved: bool | None = None) -> Recipe:
    """Note that a recipe was used again, and how it went.

    Score is averaged rather than replaced. One bad run should move a
    well-established recipe, not erase what every previous run established —
    and one lucky run should not promote a poor recipe to the top of the list.
    """
    recipe.uses += 1
    if score is not None:
        if recipe.score:
            recipe.score = (recipe.score * (recipe.uses - 1) + score) / recipe.uses
        else:
            recipe.score = score
    if approved is not None:
        recipe.approved = approved or recipe.approved
    recipe.updated_at = now()
    return recipe
