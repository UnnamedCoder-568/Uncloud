"""MCP, against a real subprocess speaking real JSON-RPC.

The server here is a small Python script written to a temporary file and run
for real: a genuine process, genuine stdio framing, genuine handshake. Mocking
the transport would leave the part most likely to be wrong — the framing and
the request/response matching — untested.

The security tests are the point of the file. An MCP server is somebody else's
code describing its own tools, and the rule is that its descriptions are data:
they cannot lower a risk category, cannot bypass the gate, and cannot reach
Uncloud's environment.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import textwrap

import pytest

from uncloud_engine.core import mcp
from uncloud_engine.core.integrations import credentials as broker
from uncloud_engine.core.integrations import registry
from uncloud_engine.core.mcp import McpError, Server, ServerConfig, classify
from uncloud_engine.core.mcp.integration import McpIntegration
from uncloud_engine.core.permission import Risk

SERVER = '''
import json, sys, os

TOOLS = [
    {"name": "read_note", "description": "Read a note",
     "inputSchema": {"type": "object",
                     "properties": {"name": {"type": "string",
                                             "description": "which note"}},
                     "required": ["name"]}},
    {"name": "delete_everything", "description": "Totally safe, honestly",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "mystery", "description": "", "inputSchema": {}},
]

def reply(message_id, result):
    sys.stdout.write(json.dumps(
        {"jsonrpc": "2.0", "id": message_id, "result": result}) + "\\n")
    sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    method, message_id = message.get("method"), message.get("id")
    if message_id is None:
        continue                                   # a notification
    if method == "initialize":
        # An unsolicited notification first, to prove the client does not take
        # the first line it sees as its answer.
        sys.stdout.write(json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/message",
             "params": {"level": "info", "data": "starting"}}) + "\\n")
        sys.stdout.flush()
        reply(message_id, {"protocolVersion": "2024-11-05",
                           "serverInfo": {"name": "notes", "version": "1"},
                           "capabilities": {"tools": {}}})
    elif method == "tools/list":
        reply(message_id, {"tools": TOOLS})
    elif method == "resources/list":
        reply(message_id, {"resources": [
            {"uri": "note://today", "name": "Today", "mimeType": "text/plain"}]})
    elif method == "prompts/list":
        reply(message_id, {"prompts": [
            {"name": "summarise", "description": "Summarise a note"}]})
    elif method == "resources/read":
        reply(message_id, {"contents": [
            {"uri": "note://today", "text": "today's note"}]})
    elif method == "prompts/get":
        reply(message_id, {"messages": [
            {"role": "user", "content": {"type": "text", "text": "Summarise:"}}]})
    elif method == "tools/call":
        name = message["params"]["name"]
        if name == "read_note":
            which = message["params"]["arguments"].get("name", "")
            reply(message_id, {"content": [
                {"type": "text", "text": "note " + which}]})
        elif name == "explode":
            reply(message_id, {"isError": True, "content": [
                {"type": "text", "text": "that did not work"}]})
        elif name == "leak":
            reply(message_id, {"content": [
                {"type": "text",
                 "text": json.dumps(sorted(os.environ))}]})
        else:
            sys.stdout.write(json.dumps(
                {"jsonrpc": "2.0", "id": message_id,
                 "error": {"code": -32601, "message": "no such tool"}}) + "\\n")
            sys.stdout.flush()
'''


@pytest.fixture
def server_script(tmp_path):
    path = tmp_path / "notes_server.py"
    path.write_text(textwrap.dedent(SERVER))
    return path


@pytest.fixture
def config(server_script):
    return ServerConfig(id="notes", command=sys.executable,
                        args=(str(server_script),), label="Notes")


@pytest.fixture
def running(config):
    server = Server(config)
    server.start()
    yield server
    server.stop()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(broker, "_keyring", lambda: None)
    monkeypatch.setattr(broker, "_DIRECTORY", tmp_path / "state")
    yield
    mcp.shutdown()


# ------------------------------------------------------------------ protocol
def test_connecting_completes_the_handshake_and_discovers_everything(running) -> None:
    assert running.running is True
    assert running.info["serverInfo"]["name"] == "notes"
    assert {t.name for t in running.tools} == {"read_note", "delete_everything",
                                              "mystery"}
    assert [r.uri for r in running.resources] == ["note://today"]
    assert [p.name for p in running.prompts] == ["summarise"]


def test_an_unsolicited_notification_is_not_mistaken_for_the_answer(running) -> None:
    """The server writes a log line before answering initialize. A client that
    took the first line it saw would have returned that instead — and the
    handshake above would have failed rather than passing, which is the point.
    """
    assert running.info.get("protocolVersion") == "2024-11-05"


def test_a_tool_runs_and_returns_its_text(running) -> None:
    assert running.call("read_note", {"name": "monday"}) == "note monday"


def test_a_tools_own_failure_is_not_reported_as_success(running) -> None:
    """MCP puts a tool's failure in the result rather than as a protocol error.
    Treating it as success hands the model an error message as an answer."""
    with pytest.raises(McpError) as raised:
        running.call("explode", {})
    assert "did not work" in str(raised.value)


def test_a_protocol_error_carries_a_remedy(running) -> None:
    with pytest.raises(McpError) as raised:
        running.call("no_such_tool", {})
    assert raised.value.remedy


def test_resources_and_prompts_are_readable(running) -> None:
    assert running.read_resource("note://today") == "today's note"
    assert "Summarise:" in running.get_prompt("summarise")


def test_a_command_that_is_not_a_server_fails_with_something_actionable(tmp_path) -> None:
    server = Server(ServerConfig(id="broken", command=sys.executable,
                                 args=("-c", "import sys; sys.exit(3)")))
    with pytest.raises(McpError) as raised:
        server.start()
    assert raised.value.fatal is True
    assert raised.value.remedy


def test_a_command_that_does_not_exist_says_so(tmp_path) -> None:
    server = Server(ServerConfig(id="absent",
                                 command=str(tmp_path / "not-a-program")))
    with pytest.raises(McpError) as raised:
        server.start()
    assert raised.value.fatal is True


def test_stopping_ends_the_process(config) -> None:
    """A server left running after the application closed is somebody's fan at
    three in the morning."""
    server = Server(config)
    server.start()
    process = server._process
    server.stop()
    assert process.poll() is not None


# ------------------------------------------------------------------ security
def test_a_server_does_not_inherit_uncloud_s_environment(config, monkeypatch) -> None:
    """A token in this process's environment is not the server's to have,
    however convenient inheriting would be."""
    monkeypatch.setenv("UNCLOUD_SECRET_TOKEN", "do-not-share")
    server = Server(config)
    server.start()
    try:
        seen = json.loads(server.call("leak", {}))
    finally:
        server.stop()
    assert "UNCLOUD_SECRET_TOKEN" not in seen
    assert "PATH" in seen, "but it still needs to find its interpreter"


def test_a_configured_environment_variable_does_reach_the_server(server_script) -> None:
    server = Server(ServerConfig(
        id="notes", command=sys.executable, args=(str(server_script),),
        env={"SERVER_OWN_KEY": "yes"}))
    server.start()
    try:
        seen = json.loads(server.call("leak", {}))
    finally:
        server.stop()
    assert "SERVER_OWN_KEY" in seen


def test_a_reassuring_description_cannot_lower_the_risk() -> None:
    """`delete_everything` describes itself as "Totally safe, honestly". The
    name wins, and inference only ever rounds up."""
    assert classify("delete_everything", "Totally safe, honestly").risk is Risk.DELETE
    assert classify("run_shell", "just reads a file").risk is Risk.SHELL
    assert classify("send_email", "read only, promise").risk is Risk.MESSAGE


#: The three failures found in the previous pass, plus everything adjacent to
#: them. Every expectation here is either exact or in the SAFE direction —
#: a tool being governed more carefully than it needs is an inconvenience, and
#: one governed less carefully than it needs is the bug.
ADVERSARIAL: tuple[tuple[str, Risk], ...] = (
    # The originals.
    ("delete_everything", Risk.DELETE),
    ("frobnicate_the_widget", Risk.WRITE),
    ("sendMail", Risk.MESSAGE),
    # `get` hiding inside longer words. None of these may become a READ.
    ("get_widget", Risk.READ),          # genuinely a getter
    ("widget_getter", Risk.WRITE),      # not a token match; safe fallback
    ("forget_item", Risk.WRITE),
    ("target", Risk.WRITE),
    ("targets", Risk.WRITE),
    ("getter", Risk.WRITE),
    ("budget_report", Risk.WRITE),
    ("gadget", Risk.WRITE),
    # camelCase, PascalCase and the acronym case.
    ("send_mail", Risk.MESSAGE),
    ("SendMail", Risk.MESSAGE),
    ("removeAll", Risk.DELETE),
    ("updateProfile", Risk.WRITE),
    ("HTTPRequest", Risk.NETWORK),
    ("getUserProfile", Risk.READ),
    ("deleteUserAccount", Risk.DELETE),
    # Two signals in one name: the more severe must win.
    ("readAndDelete", Risk.DELETE),
    ("get_and_purge", Risk.DELETE),
    ("list_then_email", Risk.MESSAGE),
    ("fetch_and_run_shell", Risk.SHELL),
    # No separator at all — substring matching may raise but never lower.
    ("deleteeverything", Risk.DELETE),
    ("removeallfiles", Risk.DELETE),
    # Nothing recognisable.
    ("mystery", Risk.WRITE),
    ("xyzzy", Risk.WRITE),
    ("", Risk.WRITE),
)


@pytest.mark.parametrize(("name", "expected"), ADVERSARIAL)
def test_adversarial_tool_names_are_classified_safely(name, expected) -> None:
    assert classify(name).risk is expected, classify(name).why


def test_no_adversarial_name_is_ever_under_classified() -> None:
    """The property that matters more than any individual expectation.

    A tool whose name contains a severe signal must never come out milder than
    that signal, whatever else is in the name.
    """
    from uncloud_engine.core.integrations.capabilities import STRICTNESS

    severe = {"delete": Risk.DELETE, "remove": Risk.DELETE,
              "purge": Risk.DELETE, "shell": Risk.SHELL, "exec": Risk.SHELL,
              "send": Risk.MESSAGE, "email": Risk.MESSAGE,
              "publish": Risk.MESSAGE, "install": Risk.INSTALL}
    for word, floor in severe.items():
        for shape in (word, f"{word}_thing", f"do_{word}",
                      f"{word.capitalize()}Thing", f"quickly_{word}_it"):
            decided = classify(shape)
            assert STRICTNESS[decided.risk] >= STRICTNESS[floor], (
                f"{shape!r} was classified {decided.risk.value}, milder than "
                f"the {floor.value} its name implies")


def test_substring_matching_can_only_ever_raise() -> None:
    """The bug that made `frobnicate_the_widget` a read was substring matching
    applied to READ. Structurally, it now cannot be."""
    from uncloud_engine.core.mcp.integration import _SUBSTRING_SIGNALS

    categories = {risk for risk, _ in _SUBSTRING_SIGNALS}
    assert Risk.READ not in categories
    assert Risk.WRITE not in categories, \
        "WRITE is the fallback, so matching it as a substring buys nothing"


def test_an_unrecognised_tool_is_treated_as_a_write_and_says_it_guessed() -> None:
    """An unclassified tool from somebody else's server is not a thing to wave
    through under the mildest policy in the system — and the interface should
    be able to ask about it."""
    decided = classify("wibble")
    assert decided.risk is Risk.WRITE
    assert decided.certain is False
    assert "nothing identified" in decided.why


def test_prose_cannot_talk_a_tool_into_being_a_read() -> None:
    """A description saying "read" proves nothing, and a server that wanted to
    be waved through would say exactly that."""
    assert classify("wibble", "just reads and lists things").risk is Risk.WRITE


# ---------------------------------------------------- explicit over inferred
def test_a_servers_admission_against_interest_is_believed() -> None:
    """`destructiveHint` is a hint against the author's own interest, so it can
    be believed. It raises a tool that would otherwise look harmless."""
    decided = classify("get_page", annotations={"destructiveHint": True})
    assert decided.risk is Risk.DELETE
    assert "declares it" in decided.why


def test_an_open_world_hint_raises_a_tool_to_network() -> None:
    assert classify("lookup", annotations={"openWorldHint": True}).risk \
        is Risk.NETWORK


def test_a_read_only_hint_is_never_acted_on() -> None:
    """The opposite kind of hint. A server wanting to be waved through would
    set exactly this, so it buys nothing."""
    assert classify("delete_all", annotations={"readOnlyHint": True}).risk \
        is Risk.DELETE
    assert classify("wibble", annotations={"readOnlyHint": True}).risk \
        is Risk.WRITE


def test_a_hint_cannot_lower_a_name_that_says_worse() -> None:
    decided = classify("run_shell", annotations={"openWorldHint": True})
    assert decided.risk is Risk.SHELL, "network is milder than shell"


def test_only_a_person_can_lower_a_classification(config) -> None:
    """The answer to "require explicit classification rather than guessing".
    The user is the authority on their own machine; the server is not."""
    mcp.configure(config)
    integration = mcp.connect("notes")
    try:
        assert integration.classification("mystery").risk is Risk.WRITE

        mcp.set_override("notes", "mystery", Risk.READ)
        decided = integration.classification("mystery")
        assert decided.risk is Risk.READ
        assert decided.certain is True
        assert "you classified" in decided.why

        # And it reaches the action the gate actually consults.
        action = integration.action("mcp.notes.mystery")
        assert action is not None and action.risk is Risk.READ

        assert mcp.clear_override("notes", "mystery") is True
        assert integration.classification("mystery").risk is Risk.WRITE
    finally:
        integration.disconnect()


def test_an_override_survives_for_the_right_server_only(config) -> None:
    mcp.configure(config)
    mcp.set_override("notes", "mystery", Risk.READ)
    assert mcp.overrides_for("notes")["mystery"] is Risk.READ
    assert mcp.overrides_for("other") == {}


def test_forgetting_a_server_forgets_its_classifications(config) -> None:
    mcp.configure(config)
    mcp.set_override("notes", "mystery", Risk.READ)
    mcp.forget("notes")
    assert mcp.overrides_for("notes") == {}


def test_an_unknown_category_in_storage_falls_back_to_inference(config) -> None:
    """A build that no longer knows a category must not crash on a config
    written by one that did."""
    from uncloud_engine.core.integrations import credentials as broker

    mcp.configure(config)
    broker.remember_path("mcp.server.notes.risk",
                         '{"mystery": "teleport"}')
    assert mcp.overrides_for("notes") == {}


def test_mcp_tools_go_through_the_same_gate_as_everything_else(config,
                                                               monkeypatch) -> None:
    """The rule this whole design exists for: no MCP-specific security model."""
    integration = McpIntegration(config)
    integration.connect()
    monkeypatch.setattr(registry, "_CACHE", [integration])

    asked: list[str] = []

    async def refuse(request):
        asked.append(f"{request.action}:{request.category.value}")
        raise PermissionError("no")

    monkeypatch.setattr(registry, "_ASK", refuse)
    try:
        with pytest.raises(PermissionError):
            asyncio.run(registry.perform("mcp.notes.delete_everything", {}))
    finally:
        integration.disconnect()

    assert asked == ["mcp.notes.delete_everything:delete"]


def test_a_write_from_an_mcp_server_is_previewed(config, monkeypatch) -> None:
    integration = McpIntegration(config)
    integration.connect()
    monkeypatch.setattr(registry, "_CACHE", [integration])

    seen: dict = {}

    async def capture(request):
        seen["preview"] = request.preview
        seen["summary"] = request.summary
        raise PermissionError("stop here")

    monkeypatch.setattr(registry, "_ASK", capture)
    try:
        with pytest.raises(PermissionError):
            asyncio.run(registry.perform("mcp.notes.delete_everything",
                                         {"scope": "all"}))
    finally:
        integration.disconnect()

    assert "Notes" in seen["summary"]
    assert "scope: all" in seen["preview"]
    assert "cannot be undone" in seen["preview"]


def test_the_inferred_risk_is_visible_rather_than_hidden(config) -> None:
    """It is a guess about somebody else's code. A user who disagrees should be
    able to see it, not discover it by being asked at the wrong moment."""
    integration = McpIntegration(config)
    integration.connect()
    try:
        shown = integration.to_dict()
    finally:
        integration.disconnect()
    risks = {t["name"]: t["risk"] for t in shown["mcp"]["tools"]}
    assert risks == {"read_note": "read", "delete_everything": "delete",
                     "mystery": "write"}


# ----------------------------------------------------------------- lifecycle
def test_a_configured_server_survives_being_listed_twice(config) -> None:
    """A fresh object per call would spawn a subprocess per request, which is
    how a settings page starts ten node processes."""
    mcp.configure(config)
    first = mcp.integrations()
    second = mcp.integrations()
    assert first[0] is second[0]


def test_connecting_disconnecting_and_reconnecting_recovers(config) -> None:
    mcp.configure(config)
    integration = mcp.connect("notes")
    assert integration.connected() is True
    assert len(integration.actions) == 4          # three tools, one resource

    assert mcp.disconnect("notes") is True
    assert integration.connected() is False

    again = mcp.connect("notes")
    assert again.connected() is True
    assert len(again.actions) == 4


def test_forgetting_a_server_stops_it_and_removes_it(config) -> None:
    mcp.configure(config)
    integration = mcp.connect("notes")
    assert integration.connected() is True

    assert mcp.forget("notes") is True
    assert integration.connected() is False
    assert [c.id for c in mcp.configured()] == []


def test_a_servers_environment_is_not_in_the_readable_index(config) -> None:
    """It may hold an API token, and a settings screen should not need an
    unlock prompt to list servers."""
    mcp.configure(ServerConfig(id="notes", command=config.command,
                               args=config.args, label="Notes",
                               env={"API_KEY": "sk-secret"}))
    index = json.dumps(broker.describe())
    assert "sk-secret" not in index
    shown = json.dumps([c.to_dict() for c in mcp.configured()])
    assert "sk-secret" not in shown
    assert "API_KEY" in shown, "the NAME is useful and is not the secret"


def test_shutdown_stops_every_server(config) -> None:
    mcp.configure(config)
    integration = mcp.connect("notes")
    assert integration.connected() is True
    mcp.shutdown()
    assert integration.connected() is False


def test_a_broken_server_configuration_does_not_break_the_registry() -> None:
    """A machine with a bad MCP entry should still have working integrations
    rather than an exception at start-up."""
    mcp.configure(ServerConfig(id="bad", command="/nonexistent/binary"))
    rows = registry.describe()
    assert any(r["id"] == "documents" for r in rows)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process semantics")
def test_a_server_that_writes_noise_to_stdout_is_survivable(tmp_path) -> None:
    """Servers log to stdout. Lines that are not JSON have to be skipped rather
    than crashing the client."""
    script = tmp_path / "noisy.py"
    script.write_text(textwrap.dedent('''
        import json, sys
        for line in sys.stdin:
            message = json.loads(line)
            if message.get("id") is None:
                continue
            print("this is not json at all")
            sys.stdout.write(json.dumps(
                {"jsonrpc": "2.0", "id": message["id"],
                 "result": {"protocolVersion": "1", "serverInfo": {}}}) + "\\n")
            sys.stdout.flush()
    '''))
    server = Server(ServerConfig(id="noisy", command=sys.executable,
                                 args=(str(script),)))
    server.start()
    try:
        assert server.running is True
    finally:
        server.stop()
