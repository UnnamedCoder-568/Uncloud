from __future__ import annotations

import asyncio
import hashlib
import io
import zipfile
from types import SimpleNamespace

import pytest

from uncloud_engine import native_chat, readiness


def archive() -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as bundle:
        bundle.writestr("runtime/llama-server.exe", b"server")
        bundle.writestr("runtime/ggml.dll", b"library")
    return data.getvalue()


def test_verified_runtime_installs_executable_and_adjacent_libraries(tmp_path, monkeypatch):
    data = archive()
    monkeypatch.setattr(native_chat, "SHA256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(native_chat.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(data))
    native_chat.install_windows_runtime(tmp_path, say=lambda _: None)
    assert (tmp_path / "llama-server.exe").read_bytes() == b"server"
    assert (tmp_path / "ggml.dll").read_bytes() == b"library"


def test_corrupt_runtime_is_rejected_before_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        native_chat.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"corrupt download")
    )
    with pytest.raises(RuntimeError, match="checksum"):
        native_chat.install_windows_runtime(tmp_path, say=lambda _: None)
    assert not list(tmp_path.iterdir())


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
