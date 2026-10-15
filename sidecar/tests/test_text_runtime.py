"""Runtime selection follows actual components, not names or a prompt rule."""

import json
from types import SimpleNamespace

from uncloud_engine.chat import model_payload
from uncloud_engine.engines import EngineManager
from uncloud_engine.text_runtime import for_mlx_model


def test_renamed_vision_checkpoint_uses_its_processor(tmp_path):
    model = tmp_path / "renamed-anything"
    model.mkdir()
    (model / "config.json").write_text(json.dumps({"model_type": "example",
                                                  "vision_config": {"hidden_size": 16}}))
    assert for_mlx_model(model) == "mlx"
    (model / "processor_config.json").write_text('{}')
    assert for_mlx_model(model) == "mlx-vlm"
    (model / "config.json").write_text('{"model_type":"example","vision_config":null}')
    assert for_mlx_model(model) == "mlx"


def test_decoder_only_weights_stay_on_native_lm(tmp_path):
    (tmp_path / "config.json").write_text('{"model_type":"example"}')
    (tmp_path / "preprocessor_config.json").write_text('{}')
    assert for_mlx_model(tmp_path) == "mlx"


def test_vlm_request_names_the_selected_model_without_changing_the_prompt():
    active = SimpleNamespace(engine="mlx-vlm", model_path='/chosen/vision', context_limit=4096,
        inference_profile={"capabilities": {"fields": ["max_tokens"],
            "reasoning": {"levels": ["auto"]}}})
    messages = [{"role": "user", "content": "Who are you?"}]
    payload = model_payload(active, messages)
    assert payload["model"] == '/chosen/vision'
    assert payload["messages"] is messages
    assert "enable_thinking" not in payload
    assert "thinking_budget" not in payload


def test_decoder_launcher_scales_auto_to_the_runtime_window(monkeypatch):
    import uncloud_engine.engines as engines

    calls = []
    monkeypatch.setattr(engines.subprocess, "Popen",
                        lambda command, **kwargs: calls.append((command, kwargs)))
    EngineManager()._spawn_mlx('/decoder', 12345, context_limit=8192)
    command, options = calls[0]
    assert command[command.index('--max-tokens') + 1] == '8192'
    assert options['env']['UNCLOUD_CONTEXT_LIMIT'] == '8192'


def test_vlm_keeps_the_selected_adapter_resident_and_on_each_request(monkeypatch):
    import uncloud_engine.engines as engines

    calls = []
    monkeypatch.setattr(engines.subprocess, "Popen",
                        lambda command, **kwargs: calls.append(command))
    EngineManager()._spawn_mlx_vlm('/vision', 12345, 8192, '/my/adapter')
    command = calls[0]
    assert command[command.index('--adapter-path') + 1] == '/my/adapter'
    assert command[command.index('--max-kv-size') + 1] == '8192'
    active = SimpleNamespace(engine='mlx-vlm', model_path='/vision',
        adapter_path='/my/adapter', context_limit=8192, inference_profile={})
    assert model_payload(active, [])['adapter_path'] == '/my/adapter'


def test_auto_sampling_uses_the_native_runtime_mode_without_inventing_a_toggle():
    profile = {"recommendation": {"native_mode": "thinking"},
        "mode_parameters": {"thinking": {"temperature": 1.0}, "off": {"temperature": 0.7}},
        "capabilities": {"fields": ["temperature"],
            "reasoning": {"default": "off", "levels": ["auto", "off", "high"],
                          "mechanism": "template_toggle"}}}
    active = SimpleNamespace(engine="mlx-vlm", model_path='/chosen/vision',
                              context_limit=4096, inference_profile=profile)
    automatic = model_payload(active, [{"role": "user", "content": "Hello"}])
    assert automatic['temperature'] == 0.7
    assert 'enable_thinking' not in automatic
    on = model_payload(active, [], inference={'reasoning': 'high'})
    assert on['temperature'] == 1.0
    assert on['enable_thinking'] is True
