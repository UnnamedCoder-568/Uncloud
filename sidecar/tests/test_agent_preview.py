import asyncio
import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image

from uncloud_engine import agent_preview


def test_preview_is_bounded_and_transient(monkeypatch):
    async def capture(source):
        out = io.BytesIO()
        Image.new('RGB', (2000, 1500)).save(out, format='PNG')
        return out.getvalue()
    monkeypatch.setattr(agent_preview, '_capture', capture)
    session = agent_preview.PreviewSession('browser')

    async def check():
        import base64
        result = await agent_preview.capture_frame(session)
        assert result['source'] == 'browser'
        assert result['captured_at'] > 0
        image = Image.open(io.BytesIO(base64.b64decode(result['image'])))
        assert image.width <= 1200 and image.height <= 750
        with pytest.raises(ValueError, match='one frame per second'):
            await agent_preview.capture_frame(session)
    asyncio.run(check())


def test_browser_capture_does_not_open_a_page(monkeypatch):
    from uncloud_engine.agent import browser
    monkeypatch.setattr(browser, '_page', None)
    with pytest.raises(RuntimeError, match='Waiting for Chisel'):
        asyncio.run(agent_preview._capture('browser'))


def test_preview_requires_active_owned_run(monkeypatch):
    from uncloud_engine import main
    monkeypatch.setattr(main, 'require_desktop', lambda request: None)
    monkeypatch.setattr(main, 'principal_of', lambda request: 'desktop')
    monkeypatch.setattr(main, '_agent_runs', {'a': ('other', SimpleNamespace(done=lambda: False))})
    with pytest.raises(HTTPException) as error:
        main._require_preview_run('a', None)
    assert error.value.status_code == 404
    monkeypatch.setattr(main, '_agent_runs', {'a': ('desktop', SimpleNamespace(done=lambda: True))})
    with pytest.raises(HTTPException):
        main._require_preview_run('a', None)


def test_preview_cannot_bypass_device_policy(monkeypatch):
    from uncloud_engine import main
    monkeypatch.setattr(main, '_require_preview_run', lambda *args: None)
    monkeypatch.setattr(main, 'settings', SimpleNamespace(agent_device_access=False))
    with pytest.raises(HTTPException) as error:
        main.enable_agent_preview('a', main.AgentPreviewBody(source='desktop'), None)
    assert error.value.status_code == 403


def test_preview_grant_required_and_deny_revokes(monkeypatch):
    from uncloud_engine import main
    monkeypatch.setattr(main, '_require_preview_run', lambda *args: None)
    monkeypatch.setattr(main, '_agent_previews', {})
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.agent_preview_frame('a', None))
    assert error.value.status_code == 403
    main._agent_previews['a'] = agent_preview.PreviewSession('browser')
    monkeypatch.setattr(main, 'gate', SimpleNamespace(mode_for=lambda category: main.Mode.DENY))
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.agent_preview_frame('a', None))
    assert error.value.status_code == 403
    assert 'a' not in main._agent_previews


def test_enable_uses_gate_once_and_stop_removes_grant(monkeypatch):
    from uncloud_engine import main
    monkeypatch.setattr(main, '_require_preview_run', lambda *args: None)
    monkeypatch.setattr(main, '_agent_previews', {})
    calls = []
    monkeypatch.setattr(main, 'gated', lambda *args, **kwargs: calls.append(args))
    main.enable_agent_preview('a', main.AgentPreviewBody(source='browser'), None)
    assert len(calls) == 1 and calls[0][1] == main.Risk.NETWORK
    assert main._agent_previews['a'].source == 'browser'
    main.disable_agent_preview('a', None)
    assert not main._agent_previews


def test_refused_enable_creates_no_capture_grant(monkeypatch):
    from uncloud_engine import main
    monkeypatch.setattr(main, '_require_preview_run', lambda *args: None)
    monkeypatch.setattr(main, '_agent_previews', {})
    def refuse(*args, **kwargs):
        raise HTTPException(status_code=428)
    monkeypatch.setattr(main, 'gated', refuse)
    with pytest.raises(HTTPException):
        main.enable_agent_preview('a', main.AgentPreviewBody(source='browser'), None)
    assert not main._agent_previews


def test_authorized_frames_do_not_reask_and_stopping_drops_inflight_frame(monkeypatch):
    from uncloud_engine import main
    monkeypatch.setattr(main, '_require_preview_run', lambda *args: None)
    session = agent_preview.PreviewSession('browser')
    monkeypatch.setattr(main, '_agent_previews', {'a': session})
    monkeypatch.setattr(main, 'gate', SimpleNamespace(mode_for=lambda category: main.Mode.ASK))
    async def frame(current):
        assert current is session
        return {'image': 'example'}
    monkeypatch.setattr(agent_preview, 'capture_frame', frame)
    assert asyncio.run(main.agent_preview_frame('a', None)) == {'image': 'example'}
    async def stopped(current):
        main._agent_previews.pop('a')
        return {'image': 'example'}
    monkeypatch.setattr(agent_preview, 'capture_frame', stopped)
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.agent_preview_frame('a', None))
    assert error.value.status_code == 403
