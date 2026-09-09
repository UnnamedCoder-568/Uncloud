"""User-supplied procedures the agent can look up and follow.

A skill is *instructions, never code*. That boundary predates everything else
here and it survives: the agent can author a skill, so executable skills would
amount to it granting itself arbitrary code execution, and every limit on the
tool list would stop meaning anything. Skills describe how to do something; the
tools remain the only way anything happens.

    Models       intelligence
    Tools        actions
    Skills       reusable procedures
    Orchestrator decides which of the above a task needs
    Permissions  decide what any of them may do

The manifest added here does not weaken that. It lets a skill DECLARE what it
needs — which tools, which model capabilities, which permissions, how much
memory — so that three things become possible:

* the orchestrator can decline to offer a skill whose tools are unavailable,
  instead of watching it fail four steps in;
* a person can be told once, before installing, what a skill will want, rather
  than being interrupted six times while it works;
* a third-party skill is a text file that ASKS for capabilities it does not
  automatically receive.

Needing is not having. A skill naming `shell` is a skill that will prompt.

Layout is unchanged, and so is compatibility: a `SKILL.md` with nothing but a
name still loads, and simply declares less.

    ~/.uncloud/skills/<slug>/SKILL.md

    ---
    name: Weekly report
    description: How to assemble the Monday summary from the sales sheet.
    version: 2
    tools: fs_read, fs_write, web_search
    permissions: read, write, network
    capabilities: text.generate
    memory_gb: 4
    ---
    1. Read the sheet at ~/work/sales.csv
    ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..foundation import Capability, Risk

SKILLS_DIR = Path.home() / ".uncloud" / "skills"
SKILLS_DIR.mkdir(parents=True, exist_ok=True)

MAX_BODY = 20000

#: Frontmatter keys that hold a list. Written comma- or newline-separated,
#: because a skill is a text file a person edits and YAML lists are a tax.
_LISTS = frozenset({"tools", "permissions", "capabilities"})


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "skill"


def _split(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in re.split(r"[,\n]", value) if part.strip())


@dataclass
class Skill:
    """One procedure, and what it says it needs.

    Every declared requirement is a CLAIM by the skill's author, checked
    against reality at discovery time. A skill that asks for a tool which does
    not exist is reported as broken rather than quietly offered.
    """

    slug: str
    name: str
    description: str = ""
    body: str = ""
    path: str = ""
    version: int = 1

    #: Tool ids it intends to use.
    tools: tuple[str, ...] = ()
    #: Risk categories it will ask for. Derived from `tools` when not declared,
    #: which is the common case and the one that cannot be wrong.
    permissions: tuple[Risk, ...] = ()
    #: Model capabilities it needs — vision, image generation, a long context.
    capabilities: tuple[Capability, ...] = ()
    #: Memory floor in gigabytes, so a skill needing a large model is not
    #: offered on a machine that cannot hold one.
    memory_gb: float = 0.0

    #: Problems found while reading it. A skill with these is still listed, so
    #: its author can see what is wrong, but it is not offered to the planner.
    problems: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return not self.problems

    @property
    def risk(self) -> Risk | None:
        """The most serious thing this skill can lead to.

        Derived, never declared: a skill cannot claim to be safer than the
        tools it names. Its ceiling is the sum of its parts.
        """
        order = [Risk.READ, Risk.GENERATE, Risk.NETWORK, Risk.DEVICE, Risk.WRITE,
                 Risk.SETTINGS, Risk.INSTALL, Risk.TRAIN, Risk.MESSAGE,
                 Risk.DELETE, Risk.SHELL]
        rank = {risk: i for i, risk in enumerate(order)}
        found = [p for p in self.permissions if p in rank]
        return max(found, key=lambda p: rank[p]) if found else None

    def to_dict(self) -> dict:
        return {
            "slug": self.slug, "name": self.name, "description": self.description,
            "version": self.version, "path": self.path,
            "tools": list(self.tools),
            "permissions": [p.value for p in self.permissions],
            "capabilities": [c.value for c in self.capabilities],
            "memory_gb": self.memory_gb,
            "risk": self.risk.value if self.risk else None,
            "problems": list(self.problems),
            "usable": self.usable,
        }


def _parse(text: str) -> tuple[dict, str]:
    """Split leading `---` frontmatter from the body.

    Tolerant on purpose: a skill with no frontmatter is still a usable skill,
    it just declares nothing. That is what keeps every file written before the
    manifest existed working unchanged.
    """
    meta: dict[str, str] = {}
    body = text
    if text.lstrip().startswith("---"):
        parts = text.lstrip().split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    meta[key.strip().lower()] = value.strip()
            body = parts[2]
    return meta, body.strip()


def _read_one(directory: Path) -> Skill | None:
    file = directory / "SKILL.md"
    if not file.is_file():
        return None
    try:
        meta, body = _parse(file.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None

    problems: list[str] = []

    tools = _split(meta.get("tools", ""))
    from .tools import TOOL_RISK

    unknown = [t for t in tools if t not in TOOL_RISK]
    if unknown:
        problems.append(f"names tools that do not exist: {', '.join(unknown)}")

    declared = _split(meta.get("permissions", ""))
    permissions: list[Risk] = []
    for value in declared:
        try:
            permissions.append(Risk(value))
        except ValueError:
            problems.append(f"unknown permission {value!r}")

    # Whatever its tools need, whether or not it said so. A skill cannot
    # under-declare its way into looking harmless — and one that declares
    # nothing gets an accurate list for free.
    from_tools = {TOOL_RISK[t] for t in tools if t in TOOL_RISK}
    permissions = sorted(set(permissions) | from_tools, key=lambda r: r.value)

    capabilities: list[Capability] = []
    for value in _split(meta.get("capabilities", "")):
        try:
            capabilities.append(Capability(value))
        except ValueError:
            problems.append(f"unknown capability {value!r}")

    try:
        version = int(meta.get("version", "1") or 1)
    except ValueError:
        version = 1
        problems.append("version is not a number")

    try:
        memory_gb = float(meta.get("memory_gb", "0") or 0)
    except ValueError:
        memory_gb = 0.0
        problems.append("memory_gb is not a number")

    if not body.strip():
        problems.append("has no instructions")

    return Skill(
        slug=directory.name,
        name=meta.get("name") or directory.name.replace("-", " ").title(),
        description=meta.get("description", ""),
        body=body,
        path=str(file),
        version=version,
        tools=tools,
        permissions=tuple(permissions),
        capabilities=tuple(capabilities),
        memory_gb=memory_gb,
        problems=tuple(problems),
    )


def all_skills() -> list[Skill]:
    if not SKILLS_DIR.is_dir():
        return []
    out = []
    for directory in sorted(SKILLS_DIR.iterdir()):
        if directory.is_dir():
            found = _read_one(directory)
            if found:
                out.append(found)
    return out


def find(name: str) -> Skill | None:
    want = _slug(name)
    for skill in all_skills():
        if skill.slug == want or skill.name.lower() == name.strip().lower():
            return skill
    return None


# ------------------------------------------------------------- discovery
@dataclass
class Availability:
    """Whether a skill can be offered here, and why not."""

    skill: Skill
    available: bool
    reasons: tuple[str, ...] = ()
    #: What it would prompt for if run now. Shown once, before installing,
    #: rather than as six interruptions while it works.
    prompts_for: tuple[Risk, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {**self.skill.to_dict(), "available": self.available,
                "reasons": list(self.reasons),
                "prompts_for": [r.value for r in self.prompts_for]}


def availability(skill: Skill, *, tools: set[str] | None = None,
                 capabilities: set[Capability] | None = None,
                 memory_gb: float = 0.0, gate=None) -> Availability:
    """Whether this machine can run this skill, and what it would ask for.

    Checked rather than assumed. A skill offered to the planner and then unable
    to run wastes a whole turn — and on a small model, a turn is most of the
    budget.
    """
    reasons: list[str] = []
    if skill.problems:
        reasons.extend(skill.problems)

    if tools is not None:
        missing = [t for t in skill.tools if t not in tools]
        if missing:
            reasons.append(
                f"needs tools that are switched off here: {', '.join(missing)}")

    if capabilities is not None and skill.capabilities:
        absent = [c.value for c in skill.capabilities if c not in capabilities]
        if absent:
            reasons.append(
                f"needs a model that can {', '.join(absent)}, and none is loaded")

    if skill.memory_gb and memory_gb and skill.memory_gb > memory_gb:
        reasons.append(
            f"needs about {skill.memory_gb:.0f} GB and this machine can spare "
            f"{memory_gb:.0f} GB")

    prompts: tuple[Risk, ...] = ()
    if gate is not None:
        from ..foundation import Request

        prompts = tuple(
            r.category for r in gate.would_prompt(
                Request(action=tool, category=risk, summary=skill.name)
                for tool, risk in (
                    (t, _risk_of(t)) for t in skill.tools) if risk is not None))
        denied = [p for p in skill.permissions if _denied(gate, p)]
        if denied:
            reasons.append(
                "needs permissions that are switched off: "
                + ", ".join(p.value for p in denied))

    return Availability(skill=skill, available=not reasons,
                        reasons=tuple(reasons), prompts_for=prompts)


def _risk_of(tool_id: str) -> Risk | None:
    from .tools import TOOL_RISK

    return TOOL_RISK.get(tool_id)


def _denied(gate, category: Risk) -> bool:
    from ..foundation import Mode

    return gate.mode_for(category) is Mode.DENY


def discover(**kwargs) -> list[Availability]:
    """Every skill, with whether it can be offered here."""
    return [availability(skill, **kwargs) for skill in all_skills()]


# ------------------------------------------------------------------- tools
def skill_list() -> str:
    """Names and one-line descriptions only.

    Deliberately not the bodies: this is what the planner sees, and loading
    every skill's full text into the prompt is exactly the cost tool groups
    exist to avoid.

    Unusable skills are listed with the reason rather than hidden. A skill the
    author can see is broken gets fixed; one that silently vanished does not.
    """
    skills = all_skills()
    if not skills:
        return (
            "No skills are installed. Skills live in ~/.uncloud/skills/<name>/SKILL.md "
            "and can be added by the user or written with skill_save."
        )
    lines = [f"{len(skills)} skill(s):"]
    for skill in skills:
        line = f"- {skill.slug}: {skill.description or skill.name}"
        if skill.tools:
            line += f" [uses {', '.join(skill.tools)}]"
        if not skill.usable:
            line += f" — UNUSABLE: {skill.problems[0]}"
        lines.append(line)
    lines.append("\nUse skill_read to get the full instructions for one before "
                 "following it. A skill tells you HOW; carry it out with the "
                 "normal tools.")
    return "\n".join(lines)


def skill_read(name: str) -> str:
    if not name.strip():
        raise ValueError("skill_read needs the name of a skill")
    skill = find(name)
    if not skill:
        known = ", ".join(s.slug for s in all_skills()) or "none installed"
        raise ValueError(f"No skill named '{name}'. Available: {known}")

    header = f"# {skill.name}"
    if skill.tools:
        header += f"\n\nIt expects to use: {', '.join(skill.tools)}."
    if not skill.usable:
        header += (f"\n\nNote: this skill has problems — "
                   f"{'; '.join(skill.problems)}. Follow it with care.")
    return f"{header}\n\n{skill.body}"


def skill_save(name: str, description: str, instructions: str,
               tools: str = "", capabilities: str = "",
               memory_gb: str = "") -> str:
    """Write a skill. Instructions only — this never produces anything runnable.

    The declarations are optional and are written as given. They are checked on
    the way back IN, at discovery, rather than here: a skill that names a tool
    which is later renamed should report that when somebody tries to use it,
    not be impossible to save today.
    """
    if not name.strip():
        raise ValueError("skill_save needs a name")
    if not instructions.strip():
        raise ValueError("skill_save needs instructions to save")

    body = instructions.strip()[:MAX_BODY]
    slug = _slug(name)
    directory = SKILLS_DIR / slug
    directory.mkdir(parents=True, exist_ok=True)

    front = ["---", f"name: {name.strip()}", f"description: {description.strip()}"]
    if tools.strip():
        front.append(f"tools: {', '.join(_split(tools))}")
    if capabilities.strip():
        front.append(f"capabilities: {', '.join(_split(capabilities))}")
    if memory_gb.strip():
        front.append(f"memory_gb: {memory_gb.strip()}")
    front += ["---", ""]

    (directory / "SKILL.md").write_text("\n".join(front) + body + "\n",
                                        encoding="utf-8")
    saved = _read_one(directory)
    note = ""
    if saved and saved.problems:
        note = " Note: " + "; ".join(saved.problems) + "."
    return f"Saved skill '{slug}' to {directory / 'SKILL.md'}.{note}"


def skill_delete(slug: str) -> bool:
    import shutil

    directory = SKILLS_DIR / _slug(slug)
    if not directory.is_dir():
        return False
    shutil.rmtree(directory)
    return True
