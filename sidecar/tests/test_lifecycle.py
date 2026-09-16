"""Status inspection is read-only; the explicit stop path owns teardown."""

from __future__ import annotations

import asyncio

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
