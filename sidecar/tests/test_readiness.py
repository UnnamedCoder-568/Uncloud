from types import SimpleNamespace

import pytest

from uncloud_engine import readiness


def test_quantization_and_training_are_explicitly_platform_limited(monkeypatch):
    monkeypatch.setattr(readiness.sys, 'platform', 'win32')
    for name in ('train', 'quantize', 'mlx'):
        row = readiness.check(name)
        assert not row['supported']
        assert not row['ready']
        assert 'Apple silicon' in row['detail']


def test_interpreter_alone_does_not_count_as_ready(monkeypatch):
    monkeypatch.setattr(readiness.subprocess, 'run',
                        lambda *args, **kwargs: SimpleNamespace(returncode=1))
    assert not readiness.check('music')['ready']


def test_successful_installer_requires_successful_postcheck(monkeypatch):
    from uncloud_engine import music_engine
    monkeypatch.setenv('UNCLOUD_UV', '/fake/uv')
    monkeypatch.setattr(readiness, 'check', lambda name: {'supported': True, 'ready': False})
    monkeypatch.setattr(music_engine, 'install_acestep', lambda say: None)
    with pytest.raises(RuntimeError, match='verification failed'):
        readiness.install('music', lambda line: None)
    assert not readiness._LOCK.locked()


def test_second_install_cannot_modify_a_busy_environment(monkeypatch):
    monkeypatch.setattr(readiness, 'check', lambda name: {'supported': True})
    readiness._LOCK.acquire()
    try:
        with pytest.raises(RuntimeError, match='Another installation'):
            readiness.install('chat', lambda line: None)
    finally:
        readiness._LOCK.release()


def test_unknown_capability_is_rejected():
    with pytest.raises(ValueError, match='Unknown capability'):
        readiness.install('arbitrary-package', lambda line: None)
