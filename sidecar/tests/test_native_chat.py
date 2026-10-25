from __future__ import annotations

import asyncio
import hashlib
import io
import subprocess
import tarfile
import zipfile
from types import SimpleNamespace

import pytest

from uncloud_engine import native_chat, readiness


def test_gpu_probe_recognizes_real_backend_device_names(monkeypatch):
    devices = ('Available devices:\n  BLAS: Accelerate (0 MiB)\n'
               '  MTL0: Apple M5 (18186 MiB)\n  Metal: Apple GPU\n'
               '  CUDA0: NVIDIA GPU\n  Vulkan1: AMD GPU\n  SYCL0: Intel GPU\n')

    def run(command, **kwargs):
        return SimpleNamespace(returncode=0, stderr='', stdout=devices
            if command[-1] == '--list-devices' else '--fit-ctx --fit on --no-context-shift')

    monkeypatch.setattr(native_chat.subprocess, 'run', run)
    native_chat._inspect.cache_clear()
    try:
        result = native_chat._inspect('/native/server', 0, 0)
    finally:
        native_chat._inspect.cache_clear()
    assert [row.split(':')[0] for row in result['devices']] == [
        'MTL0', 'Metal', 'CUDA0', 'Vulkan1', 'SYCL0']
    assert result['auto_fit']


@pytest.mark.parametrize('failure', ['timeout', 'device_exit'])
def test_failed_cold_probe_is_retried_instead_of_cached_as_cpu_only(tmp_path, monkeypatch,
                                                                 failure):
    executable = tmp_path / 'server'
    executable.touch()
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if failure == 'timeout' and len(calls) == 1:
            raise subprocess.TimeoutExpired(command, 60)
        if failure == 'device_exit' and len(calls) == 2:
            return SimpleNamespace(returncode=1, stderr='GPU initialization failed', stdout='')
        return SimpleNamespace(returncode=0, stderr='', stdout=(
            '--fit-ctx --fit on --no-context-shift' if command[-1] == '--help'
            else 'MTL0: Apple GPU'))

    monkeypatch.setattr(native_chat.subprocess, 'run', run)
    native_chat._inspect.cache_clear()
    try:
        assert not native_chat.inspect_runtime(str(executable))['devices']
        assert native_chat.inspect_runtime(str(executable))['devices'] == ['MTL0: Apple GPU']
    finally:
        native_chat._inspect.cache_clear()


def test_unsupported_engine_does_not_unload_resident_model():
    from uncloud_engine import engines

    manager = engines.EngineManager()
    resident = SimpleNamespace(model_path='resident')
    manager.active = resident
    with pytest.raises(ValueError, match='launcher'):
        asyncio.run(manager.start('unsupported', 'invented'))
    assert manager.active is resident


def archive() -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as bundle:
        bundle.writestr("runtime/llama-server.exe", b"server")
        bundle.writestr("runtime/ggml.dll", b"library")
    return data.getvalue()


def test_verified_runtime_installs_executable_and_adjacent_libraries(tmp_path, monkeypatch):
    data = archive()
    monkeypatch.setattr(native_chat, "SHA256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(native_chat, "GPU_SHA256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(native_chat.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(data))
    native_chat.install_windows_runtime(tmp_path, say=lambda _: None)
    assert (tmp_path / "llama-server.exe").read_bytes() == b"server"
    assert (tmp_path / "ggml.dll").read_bytes() == b"library"
    assert (tmp_path / "vulkan/llama-server.exe").read_bytes() == b"server"


def test_corrupt_runtime_is_rejected_before_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        native_chat.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"corrupt download")
    )
    with pytest.raises(RuntimeError, match="checksum"):
        native_chat.install_windows_runtime(tmp_path, say=lambda _: None)
    assert not list(tmp_path.iterdir())


def test_mac_archive_is_verified_and_preserves_executable_and_libraries(tmp_path, monkeypatch):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as bundle:
        for name, body in [('llama-server', b'server'), ('libllama.dylib', b'library')]:
            entry = tarfile.TarInfo(f'llama-{native_chat.VERSION}/{name}')
            entry.size = len(body)
            entry.mode = 0o755
            bundle.addfile(entry, io.BytesIO(body))
    raw = data.getvalue()
    monkeypatch.setattr(native_chat.sys, 'platform', 'darwin')
    monkeypatch.setattr(native_chat.platform, 'machine', lambda: 'arm64')
    monkeypatch.setitem(native_chat.MAC_SHA256, 'arm64', hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(native_chat.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(raw))
    native_chat.install_native_runtime(tmp_path, say=lambda _: None)
    root = tmp_path / f'llama-{native_chat.VERSION}'
    assert (root / 'llama-server').stat().st_mode & 0o111
    assert (root / 'libllama.dylib').read_bytes() == b'library'
    monkeypatch.setattr(native_chat, 'RUNTIME_DIR', tmp_path)
    monkeypatch.delenv('UNCLOUD_LLAMA_SERVER', raising=False)
    assert native_chat.server_path() == str(root / 'llama-server')


def test_corrupt_mac_archive_cannot_replace_an_existing_runtime(tmp_path, monkeypatch):
    root = tmp_path / f'llama-{native_chat.VERSION}'
    root.mkdir()
    (root / 'llama-server').write_bytes(b'working')
    monkeypatch.setattr(native_chat.sys, 'platform', 'darwin')
    monkeypatch.setattr(native_chat.platform, 'machine', lambda: 'arm64')
    monkeypatch.setattr(native_chat.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(b'bad'))
    with pytest.raises(RuntimeError, match='checksum'):
        native_chat.install_native_runtime(tmp_path, say=lambda _: None)
    assert (root / 'llama-server').read_bytes() == b'working'


def test_windows_readiness_executes_bundled_server_without_python_binding(monkeypatch):
    monkeypatch.setattr(readiness.sys, "platform", "win32")
    monkeypatch.setattr(readiness, "server_path", lambda: "C:/Uncloud/llama-server.exe")
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(readiness.subprocess, "run", run)
    assert readiness.check("chat")["ready"]
    assert commands == [["C:/Uncloud/llama-server.exe", "--version"]]


def test_missing_windows_server_is_repairable(monkeypatch):
    monkeypatch.setattr(readiness.sys, "platform", "win32")
    monkeypatch.setattr(readiness, "server_path", lambda: None)
    row = readiness.check("chat")
    assert row["supported"] and not row["ready"]
    assert "repair" in row["detail"]


def test_native_chat_has_one_slot_so_context_is_not_split(monkeypatch):
    from uncloud_engine import engines

    monkeypatch.setattr(engines, "LLAMA_SERVER_BIN", "/native/llama-server")
    commands = []
    monkeypatch.setattr(
        engines.subprocess, "Popen", lambda command, **kwargs: commands.append(command)
    )
    engines.EngineManager()._spawn_llama_cpp("model.gguf", 8080, 8192)
    assert commands[0][-2:] == ["--parallel", "1"]
    assert commands[0][commands[0].index("-c") + 1] == "8192"


def test_context_override_rejected_before_unloading_current_model(monkeypatch):
    from uncloud_engine import engines

    manager = engines.EngineManager()
    current = SimpleNamespace(model_path="other", engine="gguf", adapter_path=None,
                              process=SimpleNamespace(poll=lambda: None), context_limit=1024)
    manager.active = current
    monkeypatch.setattr(engines, "for_model", lambda *args: {
        "native_limit": 8192, "effective_limit": 1024,
    })
    with pytest.raises(ValueError, match="supported"):
        asyncio.run(manager.start("new", "gguf", context_length=16384))
    assert manager.active is current


def test_normal_turn_keeps_explicitly_loaded_window_and_resident_model():
    from uncloud_engine import engines

    manager = engines.EngineManager()
    current = SimpleNamespace(model_path="model", engine="gguf", adapter_path=None,
                              process=SimpleNamespace(poll=lambda: None), context_limit=8192)
    manager.active = current
    assert asyncio.run(manager.start("model", "gguf")) is current
