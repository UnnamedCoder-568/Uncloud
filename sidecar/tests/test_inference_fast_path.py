import asyncio
import json
from types import SimpleNamespace

import httpx

from uncloud_engine import chat_transport, inference_profile, library
from uncloud_engine.chat import model_payload


def test_model_recommendations_and_override_precedence(tmp_path):
    (tmp_path / "generation_config.json").write_text(
        json.dumps({"temperature": 1.0, "top_p": 0.95, "do_sample": True})
    )
    (tmp_path / "uncloud-inference.json").write_text('{"top_p": 0.9}')
    model, profile = inference_profile.load(str(tmp_path), "mlx")
    active = SimpleNamespace(engine="mlx", inference_profile=profile, model_profile=model)
    messages = [{"role": "user", "content": "hello"}]
    payload = model_payload(active, messages, overrides={"temperature": 0})
    assert payload["temperature"] == 0
    assert payload["top_p"] == 0.9
    assert payload["messages"] is messages
    assert "chat_template_kwargs" not in payload
    assert "max_tokens" not in payload


def test_missing_metadata_does_not_invent_sampling(tmp_path):
    _, profile = inference_profile.load(str(tmp_path), "gguf")
    assert profile["parameters"] == {}
    assert inference_profile.clean({"temperature": float("nan"), "top_p": 3}) == {}


def test_chat_does_not_scan_library_and_records_actual_stream(monkeypatch):
    from uncloud_engine import main

    def forbidden(*args, **kwargs):
        raise AssertionError("A chat turn must not scan models")

    monkeypatch.setattr(library, "scan_library", forbidden)
    active = SimpleNamespace(
        engine="mlx",
        base_url="http://backend",
        model_profile=None,
        inference_profile={"parameters": {"temperature": 1.0}},
    )
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"42"}}]}\n\n'
            'data: {"usage":{"prompt_tokens":5,"completion_tokens":1}}\n\ndata: [DONE]\n\n',
        )

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(chat_transport, "client", lambda: client)
            run = main.ChatRun(id="test", owner="local")
            await main._run_chat(
                run, main.ChatBody(messages=[{"role": "user", "content": "6*7"}]), active
            )
            assert run.status == "done"
            assert run.timings["first_token_ms"] >= 0
            assert run.timings["usage"]["completion_tokens"] == 1
            assert run.changed.is_set()
            assert len(run.frames) == 3

    asyncio.run(exercise())
    assert requests[0]["temperature"] == 1.0
    assert "tools" not in requests[0]


def test_waiting_client_wakes_on_first_frame(monkeypatch):
    from uncloud_engine import main

    monkeypatch.setattr(main, "principal_of", lambda request: "local")

    async def exercise():
        run = main.ChatRun(id="wait-test", owner="local")
        monkeypatch.setitem(main._chat_runs, run.id, run)
        waiter = asyncio.create_task(main.chat_run_status(run.id, None, 0, True))
        await asyncio.sleep(0)
        run.frames.append("first")
        run.changed.set()
        state = await asyncio.wait_for(waiter, timeout=0.1)
        assert state["frames"] == ["first"]

    asyncio.run(exercise())


def test_output_budget_uses_metadata_then_runtime_window_with_user_override(tmp_path):
    (tmp_path / 'generation_config.json').write_text('{"max_new_tokens": 4096}')
    model, profile = inference_profile.load(str(tmp_path), 'mlx')
    active = SimpleNamespace(engine='mlx', inference_profile=profile,
                             model_profile=model, context_limit=16384)
    assert model_payload(active, [])['max_tokens'] == 4096
    assert model_payload(active, [], max_tokens=3072)['max_tokens'] == 3072
    profile['max_output_tokens'] = None
    active.context_limit = 32768
    assert model_payload(active, [])['max_tokens'] == 8192
