import asyncio
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from uncloud_engine import engines, inference_controls, native_chat


class Process:
    stdout = None

    def __init__(self, events):
        self.events = events
        self.alive = True

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.events.append('terminate')
        self.alive = False

    def wait(self, timeout):
        self.events.append('wait')
        return 0


@pytest.mark.parametrize('requested', [None, 32768])
def test_native_window_replaces_the_estimate_and_switch_waits_for_unload(monkeypatch, requested):
    events, commands = [], []
    options = {'auto_fit': True, 'context_stop': True, 'devices': ['Vulkan0: GPU']}
    monkeypatch.setattr(engines, 'LLAMA_SERVER_BIN', '/native/server')
    monkeypatch.setattr(engines, 'inspect_runtime', lambda path: options)
    monkeypatch.setattr(engines, 'for_model', lambda *args: {
        'native_limit': 131072, 'effective_limit': 1024, 'source': 'metadata',
    })
    monkeypatch.setattr(engines, 'load_inference_profile', lambda *args: (None, {}))
    monkeypatch.setattr(inference_controls, 'discover', lambda *args, **kwargs: {
        'fields': [], 'reasoning': {'levels': ['auto']},
    })
    manager = engines.EngineManager()
    old = Process(events)
    manager.active = SimpleNamespace(model_path='new' if requested is None else 'old',
                                     process=old, engine='gguf', adapter_path=None,
                                     context_limit=8192)
    monkeypatch.setattr(manager, '_wait_healthy', AsyncMock())
    monkeypatch.setattr(engines, '_free_port', lambda: 12345)

    def spawn(command, **kwargs):
        assert not old.alive
        assert events == ['terminate', 'wait']
        commands.append(command)
        return Process(events)

    monkeypatch.setattr(engines.subprocess, 'Popen', spawn)
    actual = requested or 98304

    async def response(request):
        return httpx.Response(200, json={'default_generation_settings': {
            'n_ctx': actual, 'params': {'n_predict': -1},
        }})

    client = httpx.AsyncClient
    monkeypatch.setattr(engines.httpx, 'AsyncClient',
                        lambda **kwargs: client(transport=httpx.MockTransport(response), **kwargs))
    active = asyncio.run(manager.start('new', 'gguf', context_length=requested,
                                      reload=requested is None))
    assert active.context_limit == actual
    assert active.inference_profile['capabilities']['runtime_defaults']['max_tokens'] == actual
    assert '--no-context-shift' in commands[0]
    assert '-ngl' not in commands[0]  # Native auto-offload can fit across CPU and GPU.
    if requested is None:
        assert '-c' not in commands[0]  # Unset allows native context fitting.
    else:
        assert commands[0][commands[0].index('-c') + 1] == str(requested)
    assert manager.loading is None


def test_killed_model_is_reaped_before_another_can_load():
    events = []
    process = Process(events)

    def wait(timeout):
        events.append('wait')
        if events.count('wait') == 1:
            raise subprocess.TimeoutExpired('model', timeout)

    process.wait = wait
    process.terminate = lambda: events.append('terminate')

    def kill():
        events.append('kill')
        process.alive = False

    process.kill = kill
    engines.EngineManager()._stop_process(SimpleNamespace(process=process))
    assert events == ['terminate', 'wait', 'kill', 'wait']


@pytest.mark.parametrize('available', [True, False])
def test_windows_chooses_verified_gpu_or_cpu_fallback(tmp_path, monkeypatch, available):
    cpu = tmp_path / 'llama-server.exe'
    gpu = tmp_path / 'vulkan/llama-server.exe'
    gpu.parent.mkdir()
    cpu.write_bytes(b'cpu')
    gpu.write_bytes(b'gpu')
    monkeypatch.setattr(native_chat, 'RUNTIME_DIR', tmp_path)
    monkeypatch.setattr(native_chat.sys, 'platform', 'win32')
    monkeypatch.delenv('UNCLOUD_LLAMA_SERVER', raising=False)
    monkeypatch.setattr(native_chat, 'inspect_runtime', lambda path: {
        'devices': ['Vulkan0: GPU'] if available else [],
    })
    assert native_chat.server_path() == str(gpu if available else cpu)
    monkeypatch.setenv('UNCLOUD_LLAMA_SERVER', str(cpu))
    assert native_chat.server_path() == str(cpu)


def test_cpu_native_fit_reserves_ram_already_used_by_other_apps(monkeypatch):
    commands = []
    monkeypatch.setattr(engines, 'LLAMA_SERVER_BIN', '/native/server')
    monkeypatch.setattr(engines, 'inspect_runtime', lambda path: {
        'auto_fit': True, 'context_stop': True, 'devices': [],
    })
    monkeypatch.setattr(engines, 'host_fit_margin_mb', lambda: 5120)
    monkeypatch.setattr(engines.subprocess, 'Popen',
                        lambda command, **kwargs: commands.append(command))
    engines.EngineManager()._spawn_llama_cpp('model.gguf', 12345, None)
    assert commands[0][commands[0].index('--fit-target') + 1] == '5120'
    assert '-c' not in commands[0]
