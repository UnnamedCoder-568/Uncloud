"""Deciding whether an action may run.

THIS FILE IS BYTE-IDENTICAL IN BOTH REPOSITORIES. See `capability.py` for the
rules it lives by; a test on each side fails the moment the copies disagree.

Before this, Uncloud had one boolean — `agent_device_access` — and a tool-group
allowlist, and Studio had a licence gate that answers a different question
entirely. Neither recorded anything. This is the layer that both products ask,
and it is deliberately separate from two things it is often confused with:

    LEGAL ACCEPTANCE   the user agreed to use the software
    PERMISSION         this category of action is allowed, in general
    APPROVAL           this specific action may run, now

Accepting terms is not permission. Granting a permission is not approval of
every future action under it. Keeping the three apart is what stops "the user
clicked Agree" from becoming "the agent may run any command it likes".

**This is not a sandbox and does not pretend to be.** It decides whether to
call something; it cannot contain what that something does once called. Where a
tool can do arbitrary damage — a shell, principally — the honest answer is to
ask about the specific command rather than to grant a category once and hope.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

POLICY_VERSION = 1


class Risk(StrEnum):
    """What kind of harm an action could do.

    Policy is set per category rather than per tool, so a tool added later
    inherits a decision the user has already made instead of appearing as an
    ungoverned hole. The categories are chosen by *consequence*, not by
    subsystem: reading a file and reading a calendar are the same risk to a
    person even though they are different code.
    """

    #: Looking at something the user already has.
    READ = "read"
    #: Changing something that existed before.
    WRITE = "write"
    #: Removing something. Separated from WRITE because it is the one that
    #: cannot be undone by writing again.
    DELETE = "delete"
    #: Arbitrary code with the user's own privileges. Its own category because
    #: no other permission constrains what a command does once it runs.
    SHELL = "shell"
    #: Anything that leaves the machine. The promise this product makes is
    #: local-first, so this is the category that breaks it.
    NETWORK = "network"
    #: Adding software or model weights to the machine.
    INSTALL = "install"
    #: Changing how the application itself behaves — including this policy.
    SETTINGS = "settings"
    #: Spending real time and memory making something.
    GENERATE = "generate"
    #: Training or fine-tuning. Long, expensive, and it writes new weights.
    TRAIN = "train"
    #: Controlling hardware or another application on this machine.
    DEVICE = "device"
    #: Sending something to another person: mail, a message, a post.
    MESSAGE = "message"


class Mode(StrEnum):
    """What to do when an action in a category comes up."""

    #: Never ask. The right setting for reading, and almost nothing else.
    ALLOW = "allow"
    #: Ask the first time this exact action is used in a session.
    ASK_ONCE = "ask_once"
    #: Ask the first time ANYTHING in this category is used in a session, then
    #: apply that answer to the rest of the category for the session.
    ASK_CATEGORY = "ask_category"
    #: Ask every single time. The only setting that is meaningful for a shell.
    ASK = "ask"
    #: Refuse, without asking. A user who has decided is not asked again.
    DENY = "deny"


#: What a fresh installation starts with.
#:
#: Reading is allowed because a tool that cannot look at anything cannot help,
#: and because reading is the category where constant prompting trains people
#: to click through the ones that matter. Everything that changes the world
#: asks. Shell asks EVERY time and is not offered a per-session grant: a
#: category grant on arbitrary code execution is indistinguishable from having
#: no policy at all.
DEFAULTS: dict[Risk, Mode] = {
    Risk.READ: Mode.ALLOW,
    Risk.WRITE: Mode.ASK_CATEGORY,
    Risk.DELETE: Mode.ASK,
    Risk.SHELL: Mode.ASK,
    Risk.NETWORK: Mode.ASK_CATEGORY,
    Risk.INSTALL: Mode.ASK,
    Risk.SETTINGS: Mode.ASK,
    Risk.GENERATE: Mode.ALLOW,
    Risk.TRAIN: Mode.ASK,
    Risk.DEVICE: Mode.ASK_CATEGORY,
    Risk.MESSAGE: Mode.ASK,
}

#: Categories where a per-session grant is not offered, whatever the policy
#: says. Setting one of these to ALLOW or ASK_ONCE is silently upgraded to ASK,
#: and `clamp` is where that happens so no caller has to remember.
ALWAYS_ASK: frozenset[Risk] = frozenset({Risk.SHELL, Risk.DELETE})


def clamp(category: Risk, mode: Mode) -> Mode:
    """The strongest of the requested mode and the category's own floor."""
    if mode is Mode.DENY:
        return mode
    if category in ALWAYS_ASK and mode is not Mode.ASK:
        return Mode.ASK
    return mode


class Denied(Exception):
    """The action may not run, and the user has already decided."""

    def __init__(self, request: Request, reason: str) -> None:
        self.request, self.reason = request, reason
        super().__init__(reason)


class ApprovalRequired(Exception):
    """The action needs a person, and there is nobody to ask.

    Raised when policy says ask and no asker was wired in. Deliberately not a
    silent allow and not a silent refusal: a caller that has not connected an
    approval path has a bug, and it should look like one.
    """

    def __init__(self, request: Request) -> None:
        self.request = request
        super().__init__(f"{request.action} needs approval and nothing can ask")


@dataclass(frozen=True)
class Request:
    """One action, described well enough for a person to decide about it.

    `summary` is the sentence the user reads. It has to name the specific thing
    — the command, the path, the recipients — because "the agent wants to write
    a file" is not a decision anybody can make. `preview` carries whatever the
    interface can show: a diff, a recipient list, a command.
    """

    action: str
    category: Risk
    summary: str
    preview: dict = field(default_factory=dict)
    #: Which surface asked. An audit line without this cannot answer "what was
    #: I doing when this happened".
    origin: str = ""

    @property
    def key(self) -> str:
        return f"{self.category.value}:{self.action}"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    mode: Mode
    reason: str = ""
    #: Whether a person was actually asked for this one.
    asked: bool = False
    #: Whether the answer will be reused for the rest of the session.
    remembered: bool = False

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "mode": self.mode.value,
                "reason": self.reason, "asked": self.asked,
                "remembered": self.remembered}


#: Answers a person can give. `always` and `never` write policy; the other two
#: last for the session only.
Answer = str
YES, NO, ALWAYS, NEVER = "yes", "no", "always", "never"

Asker = Callable[[Request], Answer]
Recorder = Callable[[Request, Decision], None]


class Gate:
    """The one place either product asks whether something may happen.

    Constructed with the current policy, a way to ask a person, and a way to
    record what happened. All three are injected: the foundation has no opinion
    about where settings live, how a user is prompted, or what an audit log is
    written to, and giving it one would make it un-shareable.
    """

    def __init__(self, policy: dict[Risk, Mode] | None = None, *,
                 ask: Asker | None = None, record: Recorder | None = None,
                 on_policy_change: Callable[[dict[Risk, Mode]], None] | None = None
                 ) -> None:
        self.policy: dict[Risk, Mode] = {**DEFAULTS, **(policy or {})}
        self._ask = ask
        self._record = record
        self._on_policy_change = on_policy_change
        #: Grants that last until the process ends. Never persisted: a session
        #: grant that survived a restart would be a permission the user never
        #: gave.
        self._session_actions: set[str] = set()
        self._session_categories: set[Risk] = set()

    # -------------------------------------------------------------- policy
    def mode_for(self, category: Risk) -> Mode:
        return clamp(category, self.policy.get(category, DEFAULTS[category]))

    def set_mode(self, category: Risk, mode: Mode) -> Mode:
        """Change policy. Returns what was actually stored, which may be
        stricter than what was asked for — see ALWAYS_ASK."""
        applied = clamp(category, mode)
        self.policy[category] = applied
        # A category that has become stricter must not keep honouring a grant
        # made under the looser setting.
        self._session_categories.discard(category)
        self._session_actions = {
            k for k in self._session_actions if not k.startswith(f"{category.value}:")}
        if self._on_policy_change:
            self._on_policy_change(dict(self.policy))
        return applied

    def forget_session(self) -> None:
        """Drop every per-session grant. Called when a conversation ends, and
        available to the user as "ask me again"."""
        self._session_actions.clear()
        self._session_categories.clear()

    # ------------------------------------------------------------ deciding
    def check(self, request: Request) -> Decision | None:
        """Decide without asking anybody. None means a person is needed.

        Split out so an interface can show what WOULD happen — which tools a
        skill will prompt for, say — without prompting for it.
        """
        mode = self.mode_for(request.category)
        if mode is Mode.DENY:
            reason = f"{request.category.value} is never allowed"
            if request.category is Risk.NETWORK:
                reason = (
                    "Internet access is disabled. In Settings > What Uncloud may do > "
                    "Reach the internet, change Never to Ask once a session or Always. "
                    "Enabling the Web tool alone does not grant permission."
                )
            return Decision(False, mode, reason)
        if mode is Mode.ALLOW:
            return Decision(True, mode)
        if mode is Mode.ASK_ONCE and request.key in self._session_actions:
            return Decision(True, mode, "already approved this session",
                            remembered=True)
        if mode is Mode.ASK_CATEGORY and request.category in self._session_categories:
            return Decision(True, mode, "already approved this session",
                            remembered=True)
        return None

    def request(self, request: Request) -> Decision:
        """Decide, asking a person if the policy calls for it.

        Raises `Denied` when the answer is no, rather than returning a decision
        the caller might forget to look at. A refusal that a caller can ignore
        is not a refusal.
        """
        settled = self.check(request)
        if settled is None:
            settled = self._consult(request)
        return self.settle(request, settled)

    def settle(self, request: Request, decision: Decision) -> Decision:
        """Record a decision and enforce it. The single exit from the gate.

        Both the synchronous path and an asynchronous one end here, so there is
        one place that writes the audit line and one place that raises — rather
        than two paths that could disagree about either.
        """
        if self._record:
            self._record(request, decision)
        if not decision.allowed:
            raise Denied(request, decision.reason or "not allowed")
        return decision

    def _consult(self, request: Request) -> Decision:
        if self._ask is None:
            raise ApprovalRequired(request)
        return self.answer(request, self._ask(request))

    def answer(self, request: Request, answer: Answer | None) -> Decision:
        """Apply a person's answer. Public because asking is not always
        synchronous.

        Uncloud asks over a websocket and Studio asks in process, so the gate
        cannot own the round trip. It owns what the answer MEANS — which
        session grants it creates, which policy it rewrites, and the fact that
        an unrecognised answer is a no.
        """
        mode = self.mode_for(request.category)
        answer = (answer or NO).strip().lower()
        if answer == ALWAYS:
            applied = self.set_mode(request.category, Mode.ALLOW)
            # A category with a floor cannot be set to always. The user is
            # given the strongest thing they can have, and told what it was.
            if applied is not Mode.ALLOW:
                self._session_categories.add(request.category)
                return Decision(True, applied, asked=True, remembered=True,
                                reason=f"{request.category.value} always asks")
            return Decision(True, Mode.ALLOW, asked=True, remembered=True)
        if answer == NEVER:
            self.set_mode(request.category, Mode.DENY)
            return Decision(False, Mode.DENY, "the user chose never", asked=True)
        if answer == YES:
            if mode is Mode.ASK_ONCE:
                self._session_actions.add(request.key)
            elif mode is Mode.ASK_CATEGORY:
                self._session_categories.add(request.category)
            return Decision(True, mode, asked=True,
                            remembered=mode in (Mode.ASK_ONCE, Mode.ASK_CATEGORY))
        return Decision(False, mode, "the user declined", asked=True)

    # --------------------------------------------------------------- views
    def describe(self) -> dict:
        return {
            "version": POLICY_VERSION,
            "policy": {c.value: self.mode_for(c).value for c in Risk},
            "always_ask": sorted(c.value for c in ALWAYS_ASK),
            "session_grants": {
                "actions": sorted(self._session_actions),
                "categories": sorted(c.value for c in self._session_categories),
            },
        }

    def would_prompt(self, requests: Iterable[Request]) -> list[Request]:
        """Which of these would stop and ask, as things stand.

        Used to tell somebody what a skill will want before they run it, rather
        than interrupting them six times while it works.
        """
        return [r for r in requests if self.check(r) is None]


# ------------------------------------------------------------------- audit
@dataclass(frozen=True)
class AuditEntry:
    at: float
    action: str
    category: str
    summary: str
    allowed: bool
    mode: str
    asked: bool
    origin: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "at": self.at, "action": self.action, "category": self.category,
            "summary": self.summary, "allowed": self.allowed, "mode": self.mode,
            "asked": self.asked, "origin": self.origin, "reason": self.reason,
        }


class AuditLog:
    """Append-only, one JSON object per line.

    A log rather than a database because the useful properties are that it can
    only grow, that a partial write costs one line, and that a person can read
    it with `tail`. What it deliberately does not hold is content: the summary
    says a file was written, not what was written to it, so the audit trail
    never becomes a second copy of the user's work.
    """

    def __init__(self, path: Path, *, keep_lines: int = 20_000) -> None:
        self.path = Path(path)
        self.keep_lines = keep_lines
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, request: Request, decision: Decision) -> AuditEntry:
        entry = AuditEntry(
            at=time.time(), action=request.action, category=request.category.value,
            summary=request.summary, allowed=decision.allowed,
            mode=decision.mode.value, asked=decision.asked,
            origin=request.origin, reason=decision.reason)
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            # Never fail an action because the log could not be written. An
            # audit trail is evidence, not a control.
            pass
        return entry

    def tail(self, limit: int = 200) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[dict] = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return list(reversed(out))

    def trim(self) -> None:
        """Keep the log from growing without bound. Called rarely."""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if len(lines) <= self.keep_lines:
            return
        self.path.write_text("\n".join(lines[-self.keep_lines:]) + "\n",
                             encoding="utf-8")


# ---------------------------------------------------------------- storage
def load_policy(raw: dict | None) -> dict[Risk, Mode]:
    """Read a stored policy, ignoring anything it does not recognise.

    Forgiving in one direction only: an unknown category or mode is dropped and
    the default applies. A stored value that cannot be understood must never
    resolve to something more permissive than the default.
    """
    out: dict[Risk, Mode] = {}
    for key, value in (raw or {}).items():
        try:
            category, mode = Risk(key), Mode(value)
        except ValueError:
            continue
        out[category] = clamp(category, mode)
    return out


def dump_policy(policy: dict[Risk, Mode]) -> dict:
    return {c.value: m.value for c, m in policy.items()}
