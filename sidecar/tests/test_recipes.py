"""Recipes: written, validated, run, and never a way around the gate.

Two properties carry the file. A recipe is checked when it is SAVED, because
one that fails on its third step has already done two things. And running one
changes nothing about permissions — otherwise "save this as a recipe" becomes
the way to stop being asked, which is the only interesting attack on a feature
like this.
"""

from __future__ import annotations

import asyncio

import pytest

from uncloud_engine import workflows
from uncloud_engine.core import recipes as core_recipes
from uncloud_engine.core.integrations import (
    Action,
    Capability,
    Change,
    Integration,
    credentials,
    registry,
)
from uncloud_engine.core.permission import Risk


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """A settings file of this test's own, never the developer's."""
    from uncloud_engine import config

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config.settings, "_data", {})
    monkeypatch.setattr(workflows, "_store", None)
    monkeypatch.setattr(credentials, "_keyring", lambda: None)
    monkeypatch.setattr(credentials, "_DIRECTORY", tmp_path)
    yield


class Recorder(Integration):
    """A provider that records what it was asked to do."""

    def __init__(self) -> None:
        super().__init__(
            id="recorder", name="Recorder", summary="", available=True,
            needs_credential=False,
            actions=(
                Action(id="recorder.read", capability=Capability.STORAGE_READ,
                       summary="Read"),
                Action(id="recorder.draft", capability=Capability.EMAIL_DRAFT,
                       summary="Draft"),
            ))
        self.ran: list[tuple[str, dict]] = []

    def ready(self) -> bool:
        return True

    async def preview(self, action_id, arguments):
        return Change(summary=action_id, target="somewhere")

    async def run(self, action_id, arguments):
        self.ran.append((action_id, dict(arguments)))
        return f"result of {action_id}"


@pytest.fixture
def recorder(monkeypatch):
    stub = Recorder()
    monkeypatch.setattr(registry, "_CACHE", [stub])
    return stub


@pytest.fixture
def allowed(monkeypatch):
    asked = []

    async def allow(request):
        asked.append(request)
        return None

    monkeypatch.setattr(registry, "_ASK", allow)
    return asked


def simple(**over) -> dict:
    base = {
        "name": "Summarise a sheet",
        "description": "Read a spreadsheet and draft a note about it",
        "parameters": {"path": "which spreadsheet"},
        "steps": [
            {"capability": "storage.file.read",
             "arguments": {"path": "{path}"}, "note": "Read it"},
            {"capability": "email.draft",
             "arguments": {"to": "me@example.test", "body": "{previous}"},
             "note": "Draft it"},
        ],
    }
    return {**base, **over}


# ------------------------------------------------------------------- writing
def test_a_recipe_can_be_created_listed_read_edited_and_deleted() -> None:
    made = workflows.create(**simple())
    assert made.id and made.uses == 0

    assert [r.id for r in workflows.store().list()] == [made.id]
    assert workflows.store().get(made.id).name == "Summarise a sheet"

    edited = workflows.update(made.id, {"name": "Weekly summary"})
    assert edited.name == "Weekly summary"
    assert workflows.store().get(made.id).name == "Weekly summary"

    assert workflows.store().delete(made.id) is True
    assert workflows.store().list() == []


def test_a_recipe_survives_a_restart() -> None:
    """It is written to the settings file, not held in memory."""
    made = workflows.create(**simple())
    workflows._store = None                     # as though the engine restarted
    assert workflows.store().get(made.id) is not None


# ---------------------------------------------------------------- validation
def test_a_step_naming_nothing_real_is_refused_at_save_time() -> None:
    """Not at run time. A recipe that fails on its third step has already done
    two things, and undoing those is not something this layer can offer."""
    with pytest.raises(workflows.RecipeError) as raised:
        workflows.create(**simple(steps=[
            {"capability": "email.telepathy", "arguments": {}}]))
    assert "not a capability" in str(raised.value)


def test_a_step_must_name_exactly_one_of_a_capability_or_a_tool() -> None:
    for steps in ([{"arguments": {}}],
                  [{"capability": "email.send", "tool": "shell"}]):
        with pytest.raises(workflows.RecipeError) as raised:
            workflows.create(**simple(steps=steps))
        assert "exactly one" in str(raised.value)


def test_a_placeholder_with_no_parameter_is_refused() -> None:
    """The failure would otherwise be a literal `{whatever}` arriving at a
    provider, which fails somewhere much further away."""
    with pytest.raises(workflows.RecipeError) as raised:
        workflows.create(**simple(
            parameters={},
            steps=[{"capability": "storage.file.read",
                    "arguments": {"path": "{whatever}"}}]))
    assert "not a parameter" in str(raised.value)


def test_previous_is_always_available_without_being_declared() -> None:
    made = workflows.create(**simple(parameters={}, steps=[
        {"capability": "storage.file.read", "arguments": {"path": "a"}},
        {"capability": "email.draft", "arguments": {"body": "{previous}"}}]))
    assert len(workflows.steps_of(made)) == 2


def test_a_recipe_long_enough_to_be_a_program_is_refused() -> None:
    """Not a technical limit. Past twenty steps the thing people wanted — do
    these in order — has stopped being obvious to read, and what they actually
    need is a skill."""
    with pytest.raises(workflows.RecipeError) as raised:
        workflows.create(**simple(parameters={}, steps=[
            {"capability": "storage.file.read", "arguments": {}}] * 25))
    assert "that is what a skill is for" in str(raised.value)


def test_an_empty_recipe_is_refused() -> None:
    with pytest.raises(workflows.RecipeError):
        workflows.create(**simple(steps=[]))


# ------------------------------------------------------------------- running
def test_running_executes_the_steps_in_order(recorder, allowed) -> None:
    made = workflows.create(**simple())
    outcome = asyncio.run(workflows.run(made, {"path": "q1.xlsx"}))

    assert outcome.ok is True
    assert [action for action, _ in recorder.ran] \
        == ["recorder.read", "recorder.draft"]
    assert [r.what for r in outcome.results] == ["Read it", "Draft it"]


def test_a_parameter_is_substituted_into_the_arguments(recorder, allowed) -> None:
    made = workflows.create(**simple())
    asyncio.run(workflows.run(made, {"path": "q1.xlsx"}))
    assert recorder.ran[0][1]["path"] == "q1.xlsx"


def test_a_step_can_use_what_the_previous_one_produced(recorder, allowed) -> None:
    made = workflows.create(**simple())
    asyncio.run(workflows.run(made, {"path": "q1.xlsx"}))
    assert recorder.ran[1][1]["body"] == "result of recorder.read"


def test_a_missing_parameter_is_refused_before_anything_runs(recorder,
                                                              allowed) -> None:
    made = workflows.create(**simple())
    with pytest.raises(workflows.RecipeError) as raised:
        asyncio.run(workflows.run(made, {}))
    assert "needs path" in str(raised.value)
    assert recorder.ran == []


def test_a_failing_step_stops_the_rest(recorder, allowed, monkeypatch) -> None:
    """A later step almost always depends on an earlier one, and pressing on
    produces a second, more confusing failure on top of the first."""
    async def explode(action_id, arguments):
        raise RuntimeError("the file was not there")

    monkeypatch.setattr(recorder, "run", explode)
    made = workflows.create(**simple())
    outcome = asyncio.run(workflows.run(made, {"path": "gone.xlsx"}))

    assert outcome.ok is False
    assert len(outcome.results) == 1
    assert "the file was not there" in outcome.results[0].error


def test_a_whole_string_placeholder_keeps_its_type(recorder, allowed) -> None:
    """So a step can pass a list of rows through without it becoming a string
    that looks like one."""
    made = workflows.create(
        name="Rows", parameters={"rows": "some rows"},
        steps=[{"capability": "email.draft", "arguments": {"rows": "{rows}"}}])
    asyncio.run(workflows.run(made, {"rows": [["a", 1], ["b", 2]]}))
    assert recorder.ran[0][1]["rows"] == [["a", 1], ["b", 2]]


# -------------------------------------------------------------- the gate
def test_a_recipe_is_not_a_way_around_being_asked(recorder, monkeypatch) -> None:
    """The only interesting attack on a feature like this: if a recipe could
    execute without prompting, "save this as a recipe" would be how you stop
    being asked."""
    asked: list[str] = []

    async def refuse(request):
        asked.append(request.action)
        raise PermissionError("no")

    monkeypatch.setattr(registry, "_ASK", refuse)
    made = workflows.create(**simple())
    outcome = asyncio.run(workflows.run(made, {"path": "q1.xlsx"}))

    assert outcome.ok is False
    assert asked == ["recorder.read"]
    assert recorder.ran == []


def test_each_step_is_governed_by_its_own_category(recorder, allowed) -> None:
    made = workflows.create(**simple())
    asyncio.run(workflows.run(made, {"path": "q1.xlsx"}))
    assert [r.category for r in allowed] == [Risk.READ, Risk.WRITE]


def test_a_recipe_containing_a_shell_step_prompts_as_a_shell_step(monkeypatch,
                                                                   tmp_path) -> None:
    """The case that would matter most if this were wrong."""
    from uncloud_engine.agent import approval

    made = workflows.create(
        name="Tidy", parameters={},
        steps=[{"tool": "shell", "arguments": {"command": "rm -rf /"}}])

    asked: list = []

    async def refuse(request):
        asked.append((request.action, request.category))
        raise PermissionError("no")

    monkeypatch.setattr(approval, "decide", refuse)
    outcome = asyncio.run(workflows.run(made))

    assert outcome.ok is False
    assert asked == [("shell", Risk.SHELL)]


# ------------------------------------------------------------------- trust
def test_using_a_recipe_averages_its_score_rather_than_replacing_it() -> None:
    """One bad run should move a well-established recipe, not erase what every
    previous run established."""
    recipe = core_recipes.Recipe(id="a", name="x", score=0.9, uses=9)
    core_recipes.record_use(recipe, score=0.0)
    assert 0.7 < recipe.score < 0.85


def test_approval_outranks_a_score() -> None:
    approved = core_recipes.Recipe(id="a", name="a", score=0.6, approved=True)
    scored = core_recipes.Recipe(id="b", name="b", score=0.8)
    assert approved.weight > scored.weight


def test_a_specific_recipe_beats_a_better_scoring_general_one() -> None:
    """Specificity is evidence a score cannot supply."""
    general = core_recipes.Recipe(id="a", name="general", score=0.95)
    specific = core_recipes.Recipe(id="b", name="specific", subject="invoices",
                                   score=0.5)
    assert core_recipes.best_for([general, specific], "invoices").name == "specific"
