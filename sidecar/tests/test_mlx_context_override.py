import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from uncloud_engine import engines, inference_controls


@pytest.mark.parametrize('engine', ['mlx', 'mlx-vlm'])
def test_mlx_override_reloads_with_requested_native_window(monkeypatch, engine):
    monkeypatch.setattr('uncloud_engine.text_runtime.for_mlx_model', lambda _: engine)
    monkeypatch.setattr(engines, 'for_model', lambda *args: {
        'native_limit': 131072, 'effective_limit': 8192, 'source': 'config'})
    monkeypatch.setattr(engines, 'load_inference_profile', lambda *args: (None, {}))
    monkeypatch.setattr(inference_controls, 'discover', lambda *args, **kw: {
        'fields': [], 'reasoning': {'levels': ['auto']}})
    manager = engines.EngineManager()
    events = []
    old = SimpleNamespace(model_path='old', process=SimpleNamespace(poll=lambda: None))
    manager.active = old
    monkeypatch.setattr(manager, '_stop_process', lambda active: events.append('unload'))
    monkeypatch.setattr(manager, '_wait_healthy', AsyncMock())

    def spawn(*args):
        assert events == ['unload']
        assert args[3 if engine == 'mlx' else 2] == 65536
        return SimpleNamespace(stdout=None, poll=lambda: None)

    monkeypatch.setattr(manager, '_spawn_mlx' if engine == 'mlx' else '_spawn_mlx_vlm', spawn)
    active = asyncio.run(manager.start('/checkpoint', engine, context_length=65536))
    assert active.context_limit == 65536
    assert active.context_details['requested_limit'] == 65536


def test_override_above_native_limit_never_unloads_current_model(monkeypatch):
    monkeypatch.setattr(engines, 'for_model', lambda *args: {
        'native_limit': 32768, 'effective_limit': 8192})
    manager = engines.EngineManager()
    old = SimpleNamespace(model_path='old', engine='mlx-vlm')
    manager.active = old
    with pytest.raises(ValueError):
        asyncio.run(manager.start('/checkpoint', 'mlx-vlm', context_length=65536))
    assert manager.active is old
