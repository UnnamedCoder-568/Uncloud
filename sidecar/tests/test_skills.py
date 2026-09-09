"""Skills declare what they need. Declaring is not receiving.

The boundary being defended is the one the module was built on: a skill is
instructions, never code, because the agent can write skills and executable
skills would let it grant itself arbitrary code execution. The manifest adds
declarations, and every test here is about a declaration being CHECKED rather
than trusted.
"""

from __future__ import annotations

import pytest

from uncloud_engine.agent import skills
from uncloud_engine.core import Capability, Gate, Mode, Risk


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "SKILLS_DIR", tmp_path / "skills")
    skills.SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    return skills.SKILLS_DIR


def write(store, slug: str, text: str) -> None:
    directory = store / slug
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(text, encoding="utf-8")


# ------------------------------------------------------- backwards compat
def test_a_skill_written_before_the_manifest_still_loads(store) -> None:
    """Every file on disk today has only a name and a description. Breaking
    them to add a feature would be a poor trade."""
    write(store, "old", "---\nname: Old One\ndescription: From before\n---\n\nDo the thing.")
    found = skills.find("old")
    assert found is not None
    assert found.name == "Old One"
    assert found.tools == ()
    assert found.usable is True


def test_a_skill_with_no_frontmatter_at_all_still_loads(store) -> None:
    write(store, "bare", "Just some instructions, written by hand.")
    found = skills.find("bare")
    assert found is not None and found.usable
    assert found.name == "Bare"


# -------------------------------------------------------------- manifest
def test_declared_tools_are_read(store) -> None:
    write(store, "report", "---\nname: Report\ntools: fs_read, fs_write\n---\n\nSteps.")
    assert skills.find("report").tools == ("fs_read", "fs_write")


def test_permissions_are_derived_from_tools_whether_or_not_declared(store) -> None:
    """A skill cannot under-declare its way into looking harmless."""
    write(store, "quiet", "---\nname: Quiet\ntools: shell\npermissions: read\n---\n\nx")
    found = skills.find("quiet")
    assert Risk.SHELL in found.permissions, (
        "a skill that names the shell and declares only 'read' still needs shell")
    assert Risk.READ in found.permissions


def test_a_skill_that_declares_nothing_gets_an_accurate_list(store) -> None:
    write(store, "auto", "---\nname: Auto\ntools: web_search, fs_write\n---\n\nx")
    found = skills.find("auto")
    assert set(found.permissions) == {Risk.NETWORK, Risk.WRITE}


def test_the_risk_ceiling_is_the_worst_of_its_tools(store) -> None:
    """Derived, never declared. A skill cannot claim to be safer than the tools
    it names."""
    write(store, "worst", "---\nname: Worst\ntools: fs_read, shell, web_search\n---\n\nx")
    assert skills.find("worst").risk is Risk.SHELL


def test_a_reading_skill_reports_a_reading_ceiling(store) -> None:
    write(store, "safe", "---\nname: Safe\ntools: fs_read, fs_list\n---\n\nx")
    assert skills.find("safe").risk is Risk.READ


# --------------------------------------------------------------- broken
def test_a_skill_naming_a_tool_that_does_not_exist_is_reported(store) -> None:
    """Not hidden. A skill its author can see is broken gets fixed; one that
    silently vanished does not."""
    write(store, "wrong", "---\nname: Wrong\ntools: teleport\n---\n\nx")
    found = skills.find("wrong")
    assert found.usable is False
    assert "teleport" in found.problems[0]
    assert "wrong" in skills.skill_list()


def test_a_skill_with_no_instructions_is_not_usable(store) -> None:
    write(store, "empty", "---\nname: Empty\ndescription: Nothing\n---\n")
    assert skills.find("empty").usable is False


def test_an_unknown_permission_is_reported_rather_than_ignored(store) -> None:
    write(store, "odd", "---\nname: Odd\npermissions: telepathy\n---\n\nx")
    assert any("telepathy" in p for p in skills.find("odd").problems)


def test_a_nonsense_version_does_not_stop_the_skill_loading(store) -> None:
    write(store, "ver", "---\nname: Ver\nversion: two\n---\n\nx")
    found = skills.find("ver")
    assert found.version == 1
    assert any("version" in p for p in found.problems)


# ------------------------------------------------------------ discovery
def test_a_skill_is_not_offered_when_its_tools_are_switched_off(store) -> None:
    """Offered and then unable to run wastes a whole turn, and on a small model
    a turn is most of the budget."""
    write(store, "needs-shell", "---\nname: Needs Shell\ntools: shell\n---\n\nx")
    found = skills.availability(skills.find("needs-shell"),
                                tools={"fs_read", "fs_write"})
    assert found.available is False
    assert "shell" in found.reasons[0]


def test_a_skill_is_offered_when_everything_it_needs_is_there(store) -> None:
    write(store, "fine", "---\nname: Fine\ntools: fs_read\n---\n\nx")
    assert skills.availability(skills.find("fine"), tools={"fs_read"}).available


def test_a_skill_needing_vision_is_not_offered_to_a_text_model(store) -> None:
    write(store, "looks", "---\nname: Looks\ncapabilities: vision.analyse\n---\n\nx")
    found = skills.availability(skills.find("looks"),
                                capabilities={Capability.TEXT_GENERATE})
    assert found.available is False
    assert "vision.analyse" in found.reasons[0]


def test_a_skill_needing_more_memory_than_the_machine_has_is_not_offered(store) -> None:
    write(store, "big", "---\nname: Big\nmemory_gb: 48\n---\n\nx")
    found = skills.availability(skills.find("big"), memory_gb=16.0)
    assert found.available is False
    assert "48" in found.reasons[0]


# ----------------------------------------------------- permission inheritance
def test_a_skill_does_not_receive_the_permissions_it_names(store) -> None:
    """Needing is not having. A skill naming the shell is a skill that will
    prompt — the gate still decides, per category, every time."""
    write(store, "asks", "---\nname: Asks\ntools: shell, web_search\n---\n\nx")
    gate = Gate()
    found = skills.availability(skills.find("asks"), gate=gate)
    assert Risk.SHELL in found.prompts_for
    assert found.available is True, "it can be offered; it will just have to ask"


def test_a_skill_needing_a_denied_permission_is_not_offered(store) -> None:
    write(store, "denied", "---\nname: Denied\ntools: web_search\n---\n\nx")
    gate = Gate({Risk.NETWORK: Mode.DENY})
    found = skills.availability(skills.find("denied"), gate=gate)
    assert found.available is False
    assert "switched off" in found.reasons[0]


def test_a_skill_using_only_allowed_tools_prompts_for_nothing(store) -> None:
    write(store, "reads", "---\nname: Reads\ntools: fs_read, fs_list\n---\n\nx")
    found = skills.availability(skills.find("reads"), gate=Gate())
    assert found.prompts_for == ()


# ------------------------------------------------------------- authoring
def test_saving_a_skill_writes_instructions_and_never_code(store) -> None:
    skills.skill_save("Weekly report", "The Monday summary",
                      "1. Read the sheet\n2. Write it up", tools="fs_read, fs_write")
    found = skills.find("weekly-report")
    assert found.tools == ("fs_read", "fs_write")
    assert "Read the sheet" in found.body
    # The one property this module exists to keep: a skill is a text file, and
    # saving one never produces anything the machine would execute.
    written = sorted(p.name for p in (store / "weekly-report").iterdir())
    assert written == ["SKILL.md"]


def test_saving_reports_a_problem_rather_than_refusing(store) -> None:
    """A skill naming a tool that is later renamed should say so when somebody
    tries to use it, not be impossible to write today."""
    message = skills.skill_save("Odd", "x", "y", tools="teleport")
    assert "teleport" in message


def test_a_skill_needs_instructions_to_be_saved(store) -> None:
    with pytest.raises(ValueError):
        skills.skill_save("Nameless", "x", "   ")


def test_reading_a_skill_says_what_it_expects_to_use(store) -> None:
    write(store, "tooled", "---\nname: Tooled\ntools: fs_read\n---\n\nDo it.")
    text = skills.skill_read("tooled")
    assert "fs_read" in text and "Do it." in text


def test_reading_a_broken_skill_warns_rather_than_hiding_it(store) -> None:
    write(store, "iffy", "---\nname: Iffy\ntools: teleport\n---\n\nDo it.")
    assert "problems" in skills.skill_read("iffy")


def test_the_planner_list_names_the_tools_a_skill_will_use(store) -> None:
    write(store, "listed", "---\nname: Listed\ndescription: d\ntools: fs_read\n---\n\nx")
    assert "uses fs_read" in skills.skill_list()


def test_an_empty_store_explains_where_skills_live(store) -> None:
    assert ".uncloud/skills" in skills.skill_list()
