import asyncio
from types import SimpleNamespace

import pytest

from uncloud_engine.inference_controls import apply, discover, validate
from uncloud_engine.user_events import EventStore


def active(fields=None, levels=None):
    return SimpleNamespace(
        engine="mlx",
        context_limit=8192,
        inference_profile={
            "capabilities": {
                "fields": fields or ["temperature", "seed", "stop", "max_tokens"],
                "reasoning": {"levels": levels or ["auto"]},
            }
        },
    )


@pytest.mark.parametrize(
    "values",
    [
        {"seed": 1.5},
        {"top_k": True},
        {"top_p": 1.1},
        {"temperature": float("nan")},
        {"reasoning": "maximum"},
        {"stop": [""]},
        {"system_prompt": 123},
        {"device_access": True},
        {"max_tokens": 0},
    ],
)
def test_bad_controls_rejected(values):
    with pytest.raises(ValueError):
        validate(values)


def test_auto_preserves_native_payload_and_empty_system_prompt():
    payload = {"messages": [], "temperature": 0.65}
    assert apply(active(), payload.copy(), {"reasoning": "auto", "system_prompt": ""}) == payload


def test_no_fake_reasoning_or_silent_unsupported_sampler():
    with pytest.raises(ValueError):
        apply(active(), {}, {"reasoning": "high"})
    with pytest.raises(ValueError):
        apply(active(), {}, {"typical_p": 0.8})
    result = apply(active(levels=["auto", "off", "high"]), {}, {"reasoning": "off"})
    assert result == {"chat_template_kwargs": {"enable_thinking": False}}


def test_reasoning_capability_requires_template_not_filename(tmp_path):
    path = tmp_path / "Qwen3-deepseek-reasoning"
    path.mkdir()
    assert discover(str(path), "gguf")["reasoning"]["levels"] == ["auto"]
    (path / "chat_template.jinja").write_text("{% if enable_thinking %}<think>{% endif %}")
    assert discover(str(path), "gguf")["reasoning"]["levels"] == ["auto", "off", "high"]


def test_native_graded_effort_requires_declared_template_values(tmp_path):
    (tmp_path / "chat_template.jinja").write_text(
        "{% if reasoning_effort in ['low', 'medium', 'high'] %}{{ reasoning_effort }}{% endif %}"
    )
    capabilities = discover(str(tmp_path), "gguf")
    assert capabilities["reasoning"]["levels"] == ["auto", "low", "medium", "high"]
    model = active()
    model.inference_profile["capabilities"] = capabilities
    assert apply(model, {}, {"reasoning": "medium"}) == {
        "chat_template_kwargs": {"reasoning_effort": "medium"}
    }


def test_notification_history_is_encrypted_and_tampering_preserves_original(tmp_path):
    path = tmp_path / "events.json"

    def key():
        return b"x" * 32

    store = EventStore(path, key=key)
    store.run("private-task", "desktop", "done", {"goal": "PRIVATE PROJECT WORDING"})
    encrypted = path.read_bytes()
    assert b"PRIVATE PROJECT WORDING" not in encrypted
    assert path.stat().st_mode & 0o777 == 0o600
    assert EventStore(path, key=key).listing("desktop")["runs"][0]["graph"]["goal"] == (
        "PRIVATE PROJECT WORDING"
    )
    damaged = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
    path.write_bytes(damaged)
    recovered = EventStore(path, key=key)
    assert recovered.error
    with pytest.raises(ValueError, match="preserved"):
        recovered.run("unsafe", "desktop", "running")
    assert recovered.notify("completed", "chat", "optional") is None
    assert path.read_bytes() == damaged


def test_notification_preference_validation_is_atomic(tmp_path):
    store = EventStore(tmp_path / "events.json")
    before = store.preferences()
    with pytest.raises(ValueError):
        store.set_preferences({"enabled": False, "sound": "invalid"})
    assert store.preferences() == before


def test_revocation_wins_over_waiting_approval_and_grants_do_not_cross_runs(monkeypatch):
    from uncloud_engine.agent import approval, tools
    from uncloud_engine.core import Denied, Gate, Mode, Request, Risk

    gate = Gate({Risk.WRITE: Mode.ASK_ONCE})
    monkeypatch.setattr(tools, "_gate", gate)
    request = Request("write", Risk.WRITE, "Test action", {})

    async def check():
        async def yes(_):
            return "yes"

        with tools.tool_session(), approval.asking(yes):
            await approval.decide(request)
            assert tools.current_gate().check(request).allowed
        assert gate.check(request) is None
        with tools.tool_session():
            assert tools.current_gate().check(request) is None

        async def revoked(_):
            gate.policy[Risk.WRITE] = Mode.DENY
            return "yes"

        with tools.tool_session(), approval.asking(revoked), pytest.raises(Denied):
            await approval.decide(request)

    asyncio.run(check())


def test_notification_dedupe_private_preview_and_owner_isolation(tmp_path):
    events = EventStore(tmp_path / "events.json")
    one = events.emit("permission", "chisel", "a", owner="lan:one")
    assert events.emit("permission", "chisel", "a", owner="lan:one")["id"] == one["id"]
    assert events.listing("desktop")["events"] == []
    assert events.native_batch()["events"] == []
    assert "prompt" not in one and "command" not in one
    with pytest.raises(KeyError):
        events.mark("desktop", one["id"], "read")


def test_native_claim_once_suppression_and_restart(tmp_path):
    path = tmp_path / "events.json"
    events = EventStore(path)
    events.emit("completed", "chat", "one", target="chat")
    assert len(events.native_batch()["events"]) == 1
    assert not EventStore(path).native_batch()["events"]
    events.set_preferences({"enabled": False})
    events.emit("completed", "chat", "two", target="chat")
    assert events.native_batch()["events"] == []
    events.set_preferences({"enabled": True})
    assert events.native_batch()["events"] == []


def test_answer_requires_live_matching_waiter_and_is_one_use(tmp_path):
    async def check():
        events = EventStore(tmp_path / "events.json")
        events.run("r", "desktop", "running")
        task = asyncio.create_task(events.ask("desktop", "r", "permission", {"action": "write"}))
        await asyncio.sleep(0)
        record = events.listing("desktop")["requests"][0]
        # Dismissing a notification is not a denial or a grant.
        events.mark("desktop", events.listing("desktop")["events"][0]["id"], "dismiss")
        assert not task.done()
        with pytest.raises(KeyError):
            events.answer("lan:other", record["id"], "yes")
        events.answer("desktop", record["id"], "no")
        assert await task == "no"
        with pytest.raises(ValueError):
            events.answer("desktop", record["id"], "yes")

    asyncio.run(check())


def test_restart_or_cancel_never_resumes_privileged_action(tmp_path):
    async def check():
        path = tmp_path / "events.json"
        events = EventStore(path)
        events.run("r", "desktop", "running", {"tasks": {}})
        task = asyncio.create_task(events.ask("desktop", "r", "permission", {}))
        await asyncio.sleep(0)
        record = events.listing("desktop")["requests"][0]
        recovered = EventStore(path)
        assert recovered.listing("desktop")["requests"][0]["status"] == "interrupted"
        assert recovered.listing("desktop")["runs"][0]["status"] == "interrupted"
        with pytest.raises(ValueError):
            recovered.answer("desktop", record["id"], "yes")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert events.listing("desktop")["requests"][0]["status"] == "cancelled"

    asyncio.run(check())


def test_concurrent_approval_askers_are_isolated():
    from uncloud_engine.agent.approval import _asker, asking

    async def check():
        async def run(value):
            async def asker(_):
                return value

            with asking(asker):
                await asyncio.sleep(0)
                assert await _asker.get()(None) == value

        await asyncio.gather(run("yes"), run("no"))
        assert _asker.get() is None

    asyncio.run(check())


def test_disabled_tool_groups_are_rechecked_after_permission_wait(monkeypatch):
    from uncloud_engine.agent import approval, tools

    assert tools.tools_for([]) == []
    settings = SimpleNamespace(agent_tool_groups=None, agent_device_access=False)
    monkeypatch.setattr(tools, "settings", settings)

    async def revoke(_):
        settings.agent_tool_groups = []

    monkeypatch.setattr(approval, "decide", revoke)
    with pytest.raises(PermissionError, match="disabled"):
        asyncio.run(tools.run_tool("fs_read", {"path": "never-read.txt"}))


def test_optional_job_notifications_do_not_change_job_outcome(monkeypatch):
    from uncloud_engine import job_events

    seen = []
    monkeypatch.setattr(job_events, "on_finished", lambda *event: seen.append(event))
    job_events.finished("image", SimpleNamespace(id="a", status="done"))
    job_events.finished("voice", SimpleNamespace(id="b", status="error"))
    job_events.finished("image", SimpleNamespace(id="c", status="cancelled"))
    assert seen == [("image", "a", "done"), ("voice", "b", "error")]

    def unavailable(*_):
        raise OSError("Store unavailable")

    monkeypatch.setattr(job_events, "on_finished", unavailable)
    job = SimpleNamespace(id="d", status="done")
    job_events.finished("image", job)
    assert job.status == "done"
