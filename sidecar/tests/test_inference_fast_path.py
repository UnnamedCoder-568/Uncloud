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


def qwen_config(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({
        "model_type": "qwen3_5", "text_config": {
            "num_hidden_layers": 32, "hidden_size": 4096,
            "intermediate_size": 12288, "vocab_size": 248320,
        },
    }))


def test_architecture_recommendations_with_native_thinking_and_override_precedence(tmp_path):
    qwen_config(tmp_path)
    model, profile = inference_profile.load(str(tmp_path), "mlx")
    active = SimpleNamespace(engine="mlx", inference_profile=profile, model_profile=model)
    native = model_payload(active, [])
    assert native["temperature"] == 1.0
    assert native["top_p"] == 0.95
    assert native["top_k"] == 20
    assert native["presence_penalty"] == 1.5
    assert "chat_template_kwargs" not in native
    assert profile["recommendation"]["source"].startswith("https://huggingface.co/Qwen/")
    assert model_payload(active, [], inference={"temperature": 0})["temperature"] == 0
    (tmp_path / "generation_config.json").write_text('{"temperature": 0.4, "top_p": 0.7}')
    (tmp_path / "uncloud-inference.json").write_text('{"temperature": 0.2}')
    _, active.inference_profile = inference_profile.load(str(tmp_path), "mlx")
    assert model_payload(active, [])["temperature"] == 0.2
    assert model_payload(active, [], overrides={"temperature": 0.3})["temperature"] == 0.3
    assert model_payload(active, [], inference={"temperature": 0.9})["temperature"] == 0.9


def test_mode_recommendations_do_not_override_metadata_or_user_controls(tmp_path):
    qwen_config(tmp_path)
    _, profile = inference_profile.load(str(tmp_path), "mlx")
    profile["capabilities"] = {"fields": ["temperature", "top_p", "seed"],
                               "reasoning": {"levels": ["auto", "off", "high"]}}
    active = SimpleNamespace(engine="mlx", inference_profile=profile)
    off = model_payload(active, [], inference={"reasoning": "off"})
    assert off["temperature"] == 0.7
    assert off["top_p"] == 0.8
    assert off["chat_template_kwargs"] == {"enable_thinking": False}
    assert model_payload(active, [], inference={"reasoning": "high"})["temperature"] == 1.0
    profile["explicit_parameters"]["temperature"] = 0
    assert model_payload(active, [], inference={"reasoning": "off"})["temperature"] == 0
    assert model_payload(active, [], inference={"reasoning": "off", "top_p": 0.6})["top_p"] == 0.6


def test_no_architecture_guess_from_filename_or_partial_signature(tmp_path):
    misleading = tmp_path / "Qwen3.5-9B"
    misleading.mkdir()
    _, profile = inference_profile.load(str(misleading), "mlx")
    assert profile["parameters"] == {}
    qwen_config(misleading)
    data = json.loads((misleading / "config.json").read_text())
    data["text_config"]["num_hidden_layers"] = 40
    (misleading / "config.json").write_text(json.dumps(data))
    _, profile = inference_profile.load(str(misleading), "mlx")
    assert profile["parameters"] == {}


def test_recommendations_require_no_file_access_on_chat_turn(tmp_path, monkeypatch):
    qwen_config(tmp_path)
    _, profile = inference_profile.load(str(tmp_path), "mlx")
    active = SimpleNamespace(engine="mlx", inference_profile=profile)
    def forbidden(*args, **kwargs):
        raise AssertionError("Sampling resolution must use cached model metadata")
    monkeypatch.setattr(inference_profile, "_json", forbidden)
    assert model_payload(active, [])["temperature"] == 1.0


def test_gguf_architecture_fallback_and_embedded_sampling_priority(tmp_path, monkeypatch):
    from uncloud_engine.core.models.headers import GgufHeader

    weights = tmp_path / "renamed.gguf"
    weights.write_bytes(b"fixture")
    fields = {"general.architecture": "qwen35", "qwen35.block_count": 32,
              "qwen35.embedding_length": 4096, "qwen35.feed_forward_length": 12288,
              "general.sampling.temperature": 0.5}
    monkeypatch.setattr(inference_profile, "read_gguf", lambda path: GgufHeader(3, 1, fields))
    model, profile = inference_profile.load(str(weights), "gguf")
    active = SimpleNamespace(engine="gguf", inference_profile=profile)
    assert model.family == "qwen35"
    payload = model_payload(active, [])
    assert payload["temperature"] == 0.5
    assert payload["top_p"] == 0.95
    assert payload["repeat_penalty"] == 1.0
    assert profile["sources"]["temperature"] == "GGUF sampling metadata"
    del fields["qwen35.block_count"]
    _, profile = inference_profile.load(str(weights), "gguf")
    assert profile["parameters"] == {"temperature": 0.5}


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
    (tmp_path / "generation_config.json").write_text('{"max_new_tokens": 4096}')
    model, profile = inference_profile.load(str(tmp_path), "mlx")
    active = SimpleNamespace(
        engine="mlx", inference_profile=profile, model_profile=model, context_limit=16384
    )
    assert model_payload(active, [])["max_tokens"] == 4096
    assert model_payload(active, [], max_tokens=3072)["max_tokens"] == 3072
    profile["max_output_tokens"] = None
    active.context_limit = 32768
    assert model_payload(active, [])["max_tokens"] == 8192


def test_gguf_automatic_budget_uses_native_eos_not_quarter_context():
    active = SimpleNamespace(engine="gguf", inference_profile={}, context_limit=1024)
    assert "max_tokens" not in model_payload(active, [{"role": "user", "content": "Hi"}])
    assert model_payload(active, [], max_tokens=256)["max_tokens"] == 256


def test_backend_rejection_preserves_actual_reason_without_httpx_url(monkeypatch):
    from uncloud_engine import main

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    400, json={"error": {"message": "Template requires alternating roles"}}
                )
            )
        ) as client:
            monkeypatch.setattr(chat_transport, "client", lambda: client)
            active = SimpleNamespace(engine="gguf", base_url="http://backend", inference_profile={})
            run = main.ChatRun(id="rejection", owner="local")
            await main._run_chat(
                run, main.ChatBody(messages=[{"role": "user", "content": "Hi"}]), active
            )
            assert run.status == "error"
            assert "Template requires alternating roles" in run.error
            assert "http://backend" not in run.error
            assert run.timings["backend_error"]["status"] == 400

    asyncio.run(exercise())
