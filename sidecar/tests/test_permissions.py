"""The approval layer, and the two holes it was built to close.

Most of this file is about the ways a permission system fails quietly. A gate
that defaults to allow when nobody wired it up, a session grant that outlives
the policy it was made under, a stored value nobody recognises resolving to
yes — none of those look like bugs from the outside, and all of them mean the
user is not being asked about things they said they wanted to be asked about.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from uncloud_engine.agent import approval, tools
from uncloud_engine.core import (
    ALWAYS_ASK,
    DEFAULTS,
    ApprovalRequired,
    AuditLog,
    Denied,
    Gate,
    Mode,
    Request,
    Risk,
    dump_policy,
    load_policy,
)


@pytest.fixture
def gate():
    made = Gate()
    tools.install_gate(made)
    yield made
    tools.install_gate(None)
    approval.set_asker(None)


def req(action="fs_write", category=Risk.WRITE, summary="write a file"):
    return Request(action=action, category=category, summary=summary)


# ------------------------------------------------------------ completeness
def test_every_tool_has_a_risk_category() -> None:
    """A tool nobody has classified cannot be governed. Adding one without
    deciding what it can do should be a broken build, not a hole discovered
    later.

    The one exception is named rather than implicit: `capability` resolves to
    an integration action and is governed by that action's category. Giving it
    a fixed one would mean choosing a category that is wrong for most of what
    it can become.
    """
    missing = (sorted({t["id"] for t in tools.TOOL_SPECS}
                      - set(tools.TOOL_RISK)
                      - tools.RESOLVED_AT_CALL_TIME))
    assert not missing, f"these tools have no risk category: {missing}"


def test_a_tool_resolved_at_call_time_is_still_governed() -> None:
    """The exception above is only acceptable because the gate is asked one
    level down, with better information rather than none."""
    import asyncio

    from uncloud_engine.core.integrations import IntegrationError, registry

    saved = registry._ASK
    asked: list[str] = []

    async def refuse(request):
        asked.append(request.action)
        raise PermissionError("no")

    registry._ASK = refuse
    try:
        # Either the gate refused it, or nothing is connected that could serve
        # it. Both are acceptable; running silently is not.
        with pytest.raises((PermissionError, IntegrationError)):
            asyncio.run(tools.run_tool("capability", {
                "capability": "storage.file.list", "arguments": {}}))
    finally:
        registry._ASK = saved
    # Either it was asked about, or nothing could serve it — never run silently.
    assert asked == ["documents.list"] or asked == []


def test_the_risk_table_has_no_tools_that_do_not_exist() -> None:
    stale = sorted(set(tools.TOOL_RISK) - {t["id"] for t in tools.TOOL_SPECS})
    assert not stale, f"risk categories for tools that no longer exist: {stale}"


def test_every_category_has_a_default() -> None:
    assert set(DEFAULTS) == set(Risk)


# --------------------------------------------------------------- bypassing
def test_a_tool_cannot_run_with_no_gate_installed() -> None:
    """The hole this layer exists to close. Not allow, not deny — a bug that
    looks like one."""
    tools.install_gate(None)
    with pytest.raises(tools.Ungoverned):
        asyncio.run(tools.run_tool("fs_list", {"path": "."}))


def test_an_unknown_tool_is_refused_before_anything_runs(gate) -> None:
    with pytest.raises(ValueError):
        asyncio.run(tools.run_tool("rm_minus_rf", {}))


def test_a_denied_category_refuses(gate) -> None:
    gate.set_mode(Risk.NETWORK, Mode.DENY)
    with pytest.raises(Denied):
        asyncio.run(tools.run_tool("web_search", {"query": "anything"}))


def test_a_category_that_needs_asking_raises_when_nothing_can_ask(gate) -> None:
    """Silence is not consent. A surface that has not connected an approval
    path has a bug, and it should look like one rather than proceeding."""
    approval.set_asker(None)
    with pytest.raises(ApprovalRequired):
        asyncio.run(tools.run_tool("web_search", {"query": "anything"}))


def test_reading_does_not_interrupt(gate, tmp_path, monkeypatch) -> None:
    """Reading is allowed by default on purpose: a tool that cannot look at
    anything cannot help, and prompting for every read teaches people to click
    through the prompts that matter."""
    monkeypatch.setattr(tools, "WORKSPACE_DIR", tmp_path)
    target = tmp_path / "note.txt"
    target.write_text("hello")
    assert "hello" in asyncio.run(tools.run_tool("fs_read", {"path": str(target)}))


# -------------------------------------------------------------- the shell
def test_shell_can_never_be_granted_for_a_session(gate) -> None:
    """A category grant on arbitrary code execution is indistinguishable from
    having no policy at all."""
    assert Risk.SHELL in ALWAYS_ASK
    assert gate.set_mode(Risk.SHELL, Mode.ALLOW) is Mode.ASK
    assert gate.set_mode(Risk.SHELL, Mode.ASK_CATEGORY) is Mode.ASK
    assert gate.set_mode(Risk.SHELL, Mode.ASK_ONCE) is Mode.ASK


def test_saying_yes_to_a_shell_command_does_not_approve_the_next_one(gate) -> None:
    asked = []

    async def ask(request):
        asked.append(request.summary)
        return "yes"

    approval.set_asker(ask)
    asyncio.run(tools.run_tool("shell", {"command": "echo one"}))
    asyncio.run(tools.run_tool("shell", {"command": "echo two"}))
    assert len(asked) == 2, "the second command ran without being asked about"
    assert "echo one" in asked[0] and "echo two" in asked[1]


def test_the_shell_prompt_names_the_actual_command(gate) -> None:
    """"The agent wants to run a command" is not a decision anybody can make."""
    summary, preview = tools._summarise("shell", {"command": "rm -rf build"})
    assert "rm -rf build" in summary
    assert preview["command"] == "rm -rf build"


def test_answering_always_to_a_shell_still_leaves_it_asking(gate) -> None:
    answers = iter(["always", "no"])

    async def ask(request):
        return next(answers)

    approval.set_asker(ask)
    asyncio.run(tools.run_tool("shell", {"command": "echo one"}))
    assert gate.mode_for(Risk.SHELL) is Mode.ASK
    with pytest.raises(Denied):
        asyncio.run(tools.run_tool("shell", {"command": "echo two"}))


def test_shell_may_still_be_refused_outright(gate) -> None:
    gate.set_mode(Risk.SHELL, Mode.DENY)
    with pytest.raises(Denied):
        asyncio.run(tools.run_tool("shell", {"command": "echo hello"}))


# ------------------------------------------------------- session behaviour
def test_a_category_grant_covers_the_rest_of_the_category(gate, monkeypatch) -> None:
    asked = []

    async def search(_query):
        return "result"

    monkeypatch.setattr(tools, "_web_search", search)

    async def ask(request):
        asked.append(request.action)
        return "yes"

    approval.set_asker(ask)
    asyncio.run(tools.run_tool("web_search", {"query": "one"}))
    asyncio.run(tools.run_tool("web_search", {"query": "two"}))
    assert asked == ["web_search"], "a category grant did not cover the second call"


def test_forgetting_the_session_asks_again(gate, monkeypatch) -> None:
    asked = []

    async def search(_query):
        return "result"

    monkeypatch.setattr(tools, "_web_search", search)

    async def ask(request):
        asked.append(request.action)
        return "yes"

    approval.set_asker(ask)
    asyncio.run(tools.run_tool("web_search", {"query": "one"}))
    gate.forget_session()
    asyncio.run(tools.run_tool("web_search", {"query": "two"}))
    assert len(asked) == 2


def test_tightening_a_policy_drops_grants_made_under_the_old_one(gate) -> None:
    """Otherwise a session grant outlives the policy that permitted it, and the
    user's change appears to have done nothing."""
    gate.answer(req(category=Risk.NETWORK, action="web_search"), "yes")
    assert gate.check(req(category=Risk.NETWORK, action="web_search")) is not None

    gate.set_mode(Risk.NETWORK, Mode.ASK)
    assert gate.check(req(category=Risk.NETWORK, action="web_search")) is None


def test_a_session_grant_is_never_persisted(gate) -> None:
    gate.answer(req(category=Risk.NETWORK), "yes")
    assert "session" not in json.dumps(dump_policy(gate.policy))
    # A restart rebuilds the gate from policy alone.
    rebuilt = Gate(load_policy(dump_policy(gate.policy)))
    assert rebuilt.check(req(category=Risk.NETWORK)) is None


# ---------------------------------------------------------------- storage
def test_an_unreadable_stored_policy_falls_back_to_the_default() -> None:
    """Forgiving in one direction only. A value nobody recognises must never
    resolve to something more permissive than the default."""
    loaded = load_policy({"network": "whenever-you-like", "nonsense": "allow"})
    assert loaded == {}
    assert Gate(loaded).mode_for(Risk.NETWORK) is DEFAULTS[Risk.NETWORK]


def test_a_stored_policy_cannot_smuggle_an_allow_past_the_clamp() -> None:
    loaded = load_policy({"shell": "allow", "delete": "allow"})
    assert loaded[Risk.SHELL] is Mode.ASK
    assert loaded[Risk.DELETE] is Mode.ASK


def test_a_policy_round_trips(gate) -> None:
    gate.set_mode(Risk.NETWORK, Mode.ALLOW)
    gate.set_mode(Risk.WRITE, Mode.DENY)
    rebuilt = Gate(load_policy(dump_policy(gate.policy)))
    assert rebuilt.mode_for(Risk.NETWORK) is Mode.ALLOW
    assert rebuilt.mode_for(Risk.WRITE) is Mode.DENY


# ------------------------------------------------------------------ audit
def test_the_audit_records_what_was_decided(tmp_path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    made = Gate(record=lambda r, d: log.write(r, d))
    made.request(req(action="fs_read", category=Risk.READ, summary="Read notes.txt"))

    lines = log.tail()
    assert len(lines) == 1
    assert lines[0]["action"] == "fs_read"
    assert lines[0]["allowed"] is True
    assert lines[0]["summary"] == "Read notes.txt"


def test_the_audit_records_refusals_too(tmp_path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    made = Gate({Risk.NETWORK: Mode.DENY}, record=lambda r, d: log.write(r, d))
    with pytest.raises(Denied):
        made.request(req(action="web_search", category=Risk.NETWORK))
    assert log.tail()[0]["allowed"] is False


def test_the_audit_holds_summaries_rather_than_content(tmp_path) -> None:
    """A trail that duplicated the user's work would be a second thing to
    protect rather than a record of what happened."""
    log = AuditLog(tmp_path / "audit.jsonl")
    made = Gate({Risk.WRITE: Mode.ALLOW}, record=lambda r, d: log.write(r, d))
    secret = "the quick brown fox jumped over a passphrase"
    made.request(Request(action="fs_write", category=Risk.WRITE,
                         summary="Write diary.txt",
                         preview={"path": "diary.txt", "preview": secret}))
    assert secret not in (tmp_path / "audit.jsonl").read_text()


def test_a_broken_audit_log_never_stops_an_action(tmp_path) -> None:
    """Evidence, not a control. A log that cannot be written must not become a
    reason the user's work fails."""
    directory = tmp_path / "not-a-file"
    directory.mkdir()
    log = AuditLog(directory)
    made = Gate(record=lambda r, d: log.write(r, d))
    assert made.request(req(category=Risk.READ)).allowed is True


# ------------------------------------------------------ category judgement
def test_capturing_the_screen_is_not_filed_as_reading_a_file() -> None:
    """It photographs whatever the user happens to have open. Filing the most
    invasive tool under the one category that does not ask would be the worst
    possible place for it."""
    assert tools.TOOL_RISK["screen_capture"] is Risk.DEVICE
    assert DEFAULTS[Risk.READ] is Mode.ALLOW


def test_reading_a_page_and_acting_on_one_are_different_questions() -> None:
    assert tools.TOOL_RISK["browser_read"] is Risk.NETWORK
    assert tools.TOOL_RISK["browser_click"] is Risk.WRITE
    assert tools.TOOL_RISK["browser_type"] is Risk.WRITE
    assert tools.TOOL_RISK["browser_eval"] is Risk.WRITE


def test_writing_a_skill_is_a_write_and_reading_one_is_not() -> None:
    assert tools.TOOL_RISK["skill_read"] is Risk.READ
    assert tools.TOOL_RISK["skill_save"] is Risk.WRITE


# --------------------------------------------------------------- asking
def test_a_person_who_never_answers_is_a_refusal(gate) -> None:
    """A closed window becomes a no, rather than a job that waits for ever with
    nothing to show why."""
    async def never(request):
        await asyncio.sleep(10)
        return "yes"

    approval.set_asker(never)

    async def run():
        return await approval.decide_or_refuse(
            req(category=Risk.NETWORK), timeout=0.05)

    with pytest.raises(Denied):
        asyncio.run(run())


def test_an_asker_is_removed_when_its_connection_ends(gate) -> None:
    """Otherwise the next run believes it can reach somebody and hangs waiting
    for an answer nobody will give."""
    async def ask(request):
        return "yes"

    with approval.asking(ask):
        assert approval._asker is ask
    assert approval._asker is None


def test_an_unrecognised_answer_is_a_no(gate) -> None:
    decision = gate.answer(req(category=Risk.NETWORK), "maybe later")
    assert decision.allowed is False


def test_never_writes_the_policy_rather_than_only_this_session(gate) -> None:
    gate.answer(req(category=Risk.NETWORK), "never")
    assert gate.mode_for(Risk.NETWORK) is Mode.DENY


# --------------------------------------------------------------- previews
def test_would_prompt_reports_without_prompting(gate) -> None:
    """So a skill can say what it will want before it starts, instead of
    interrupting six times while it works."""
    wants = [req(action="fs_read", category=Risk.READ),
             req(action="shell", category=Risk.SHELL),
             req(action="web_search", category=Risk.NETWORK)]
    assert [r.action for r in gate.would_prompt(wants)] == ["shell", "web_search"]


# ------------------------------------------------------------ over HTTP
#
# The hole this closes: Chisel's tools always went through `run_tool`, but
# Chat's markers — `[[search:]]`, `[[read:]]`, `[[pictures:]]` — were parsed in
# the browser and executed by the view calling the API directly. A gate in
# `run_tool` would have covered one surface and left the other wide open.
class _Client:
    """A TestClient over the real app, with the module's own gate."""

    def __enter__(self):
        import tempfile
        from pathlib import Path

        from fastapi.testclient import TestClient
        from pytest import MonkeyPatch

        from uncloud_engine import config, main
        from uncloud_engine.core import AuditLog

        self.temp = tempfile.TemporaryDirectory()
        self.patch = MonkeyPatch()
        self.patch.setattr(config, "CONFIG_FILE", Path(self.temp.name) / "settings.json")
        self.patch.setattr(main, "_audit", AuditLog(Path(self.temp.name) / "audit.jsonl"))
        self.patch.setattr(main.settings, "_data", dict(main.settings._data))
        self.main = main
        self.saved = dict(main.gate.policy)
        main.gate.forget_session()
        self.client = TestClient(main.app)
        self.client.headers.update(
            {"Authorization": f"Bearer {main.settings.token}"})
        return self

    def __exit__(self, *exc):
        self.main.gate.policy.update(self.saved)
        self.main.gate.forget_session()
        self.patch.undo()
        self.temp.cleanup()


def test_chats_own_web_lookup_goes_through_the_gate() -> None:
    with _Client() as c:
        c.main.gate.set_mode(Risk.NETWORK, Mode.ASK)
        response = c.client.post("/api/web/search", json={"query": "anything"})
        assert response.status_code == 428, (
            "Chat's web lookup ran without asking — the marker path is the "
            "surface that used to bypass the gate entirely")
        approval = response.json()["detail"]["approval"]
        assert approval["category"] == "network"
        assert "anything" in approval["summary"]


def test_answering_lets_the_retry_through() -> None:
    with _Client() as c:
        c.main.gate.set_mode(Risk.NETWORK, Mode.ASK_CATEGORY)
        first = c.client.post("/api/web/read", json={"url": "https://example.com"})
        assert first.status_code == 428

        answered = c.client.post("/api/approvals/answer", json={
            "action": "web_read", "category": "network",
            "summary": "Read this page", "answer": "yes"})
        assert answered.status_code == 200
        assert answered.json()["decision"]["allowed"] is True

        # The retry now passes on policy alone. It may still fail on the
        # network, which is not what this test is about.
        again = c.client.post("/api/web/read", json={"url": "https://example.com"})
        assert again.status_code != 428


def test_a_denied_category_is_refused_over_http_too() -> None:
    with _Client() as c:
        c.main.gate.set_mode(Risk.NETWORK, Mode.DENY)
        response = c.client.post("/api/web/search", json={"query": "anything"})
        assert response.status_code == 403


def test_the_shell_cannot_be_allowed_through_the_settings_route() -> None:
    with _Client() as c:
        response = c.client.post("/api/permissions",
                                 json={"category": "shell", "mode": "allow"})
        assert response.status_code == 200
        body = response.json()
        assert body["applied"] == "ask"
        assert body["clamped"] is True
        assert body["policy"]["shell"] == "ask"


def test_the_permissions_route_reports_the_whole_policy() -> None:
    with _Client() as c:
        body = c.client.get("/api/permissions").json()
        assert set(body["policy"]) == {r.value for r in Risk}
        assert "shell" in body["always_ask"]


def test_the_audit_route_returns_newest_first() -> None:
    with _Client() as c:
        c.main.gate.set_mode(Risk.NETWORK, Mode.DENY)
        c.client.post("/api/web/search", json={"query": "first"})
        c.client.post("/api/web/search", json={"query": "second"})
        lines = c.client.get("/api/audit?limit=5").json()
        assert lines and "second" in lines[0]["summary"]


# --------------------------------------------------- the workspace boundary
#
# The gate decides WHETHER a tool runs. This is the other half: where the file
# tools may reach when it does. Neither is a sandbox — the shell's command is
# unrestricted whatever this says, which is why shell asks every time — but the
# confinement is a real boundary and nothing pinned it until now.
def test_file_tools_stay_in_the_workspace_until_device_access_is_granted(
        tmp_path, monkeypatch) -> None:
    from uncloud_engine.config import settings

    outside = tmp_path / "private.txt"
    outside.write_text("not the agent's business")

    monkeypatch.setattr(settings, "_data", {"agent_device_access": False})
    monkeypatch.setattr(settings, "_save", lambda: None)
    with pytest.raises(PermissionError, match="outside the agent workspace"):
        tools._resolve_path(str(outside))

    # Inside is fine, and so is everything below it.
    assert tools._resolve_path(str(tools.WORKSPACE_DIR / "notes.md"))

    monkeypatch.setattr(settings, "_data", {"agent_device_access": True})
    assert tools._resolve_path(str(outside)) == outside.resolve()


def test_the_shell_starts_in_the_workspace_when_device_access_is_off(monkeypatch) -> None:
    """Its working directory, not its reach: `cd ~ && …` still goes home. That
    is why shell is its own category that asks every time and can never be
    granted for a session — see ALWAYS_ASK."""
    import inspect

    from uncloud_engine.config import settings

    monkeypatch.setattr(settings, "_data", {"agent_device_access": False})
    monkeypatch.setattr(settings, "_save", lambda: None)
    source = inspect.getsource(tools._shell)
    assert "WORKSPACE_DIR" in source and "agent_device_access" in source
    assert Risk.SHELL in ALWAYS_ASK


def test_network_denial_explains_how_to_enable_access(gate) -> None:
    gate.set_mode(Risk.NETWORK, Mode.DENY)
    decision = gate.check(req(action="web_search", category=Risk.NETWORK))
    assert decision is not None and not decision.allowed
    assert "Reach the internet" in decision.reason
    assert "Ask once a session" in decision.reason
