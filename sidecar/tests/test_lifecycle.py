"""Status inspection is read-only; the explicit stop path owns teardown."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from uncloud_engine import lifecycle, speech


def test_reading_resident_models_does_not_stop_voice(monkeypatch) -> None:
    stopped = False

    def stop() -> None:
        nonlocal stopped
        stopped = True

    monkeypatch.setattr(speech, "resident_count", lambda: 2)
    monkeypatch.setattr(speech, "stop", stop)

    state = lifecycle.resident()

    assert state["speech_workers"] == 2
    assert state["anything"] is True
    assert stopped is False


def test_unload_all_stops_voice_workers(monkeypatch) -> None:
    stopped = False

    def stop() -> None:
        nonlocal stopped
        stopped = True

    monkeypatch.setattr(speech, "resident_count", lambda: 1)
    monkeypatch.setattr(speech, "stop", stop)

    released = asyncio.run(lifecycle.stop_all(close_browser=False))

    assert released.speech_workers is True
    assert stopped is True


def test_resident_lists_all_cached_models_and_excludes_a_dead_text_worker(monkeypatch):
    from uncloud_engine import voice_engine
    from uncloud_engine.engines import engine_manager
    from uncloud_engine.narration_engine import narration_engine

    monkeypatch.setattr(engine_manager, 'active', SimpleNamespace(
        model_path='old.gguf', process=SimpleNamespace(poll=lambda: 0)))
    monkeypatch.setattr(voice_engine, '_whisper', {'path': '/models/whisper', 'model': object()})
    monkeypatch.setattr(voice_engine, '_kokoro', {'pipeline': object()})
    monkeypatch.setattr(narration_engine, '_model', object())
    monkeypatch.setattr(narration_engine, '_model_dir', '/models/narrator')
    state = lifecycle.resident()
    paths = {row['path'] for row in state['models']}
    assert {'/models/whisper', 'hexgrad/Kokoro-82M', '/models/narrator'} <= paths
    assert 'old.gguf' not in paths
    assert state['anything']


def test_unload_all_releases_in_process_voice_and_narration_caches(monkeypatch):
    from uncloud_engine import voice_engine
    from uncloud_engine.narration_engine import narration_engine

    monkeypatch.setattr(voice_engine, '_whisper', {'model': object(), 'path': '/models/asr'})
    monkeypatch.setattr(voice_engine, '_kokoro', {'pipeline': object()})
    monkeypatch.setattr(narration_engine, '_model', object())
    monkeypatch.setattr(narration_engine, '_model_dir', '/models/narration')
    released = asyncio.run(lifecycle.stop_all(close_browser=False))
    assert released.voice_models and released.narration_model
    assert not voice_engine.resident_models()
    assert narration_engine._model is None
