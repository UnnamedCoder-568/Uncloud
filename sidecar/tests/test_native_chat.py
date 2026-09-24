from __future__ import annotations

import hashlib
import io
import zipfile
from types import SimpleNamespace

import pytest

from uncloud_engine import native_chat, readiness


def archive() -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as bundle:
        bundle.writestr('runtime/llama-server.exe', b'server')
        bundle.writestr('runtime/ggml.dll', b'library')
    return data.getvalue()


def test_verified_runtime_installs_executable_and_adjacent_libraries(tmp_path, monkeypatch):
    data = archive()
    monkeypatch.setattr(native_chat, 'SHA256', hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(native_chat.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(data))
    native_chat.install_windows_runtime(tmp_path, say=lambda _: None)
    assert (tmp_path / 'llama-server.exe').read_bytes() == b'server'
    assert (tmp_path / 'ggml.dll').read_bytes() == b'library'


def test_corrupt_runtime_is_rejected_before_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(native_chat.urllib.request, 'urlopen',
                        lambda *a, **k: io.BytesIO(b'corrupt download'))
    with pytest.raises(RuntimeError, match='checksum'):
        native_chat.install_windows_runtime(tmp_path, say=lambda _: None)
    assert not list(tmp_path.iterdir())


def test_windows_readiness_executes_bundled_server_without_python_binding(monkeypatch):
    monkeypatch.setattr(readiness.sys, 'platform', 'win32')
    monkeypatch.setattr(readiness, 'server_path', lambda: 'C:/Uncloud/llama-server.exe')
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(readiness.subprocess, 'run', run)
    assert readiness.check('chat')['ready']
    assert commands == [['C:/Uncloud/llama-server.exe', '--version']]


def test_missing_windows_server_is_repairable(monkeypatch):
    monkeypatch.setattr(readiness.sys, 'platform', 'win32')
    monkeypatch.setattr(readiness, 'server_path', lambda: None)
    row = readiness.check('chat')
    assert row['supported'] and not row['ready']
    assert 'repair' in row['detail']
