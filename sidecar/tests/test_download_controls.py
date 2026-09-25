import asyncio

import httpx
import pytest

from uncloud_engine import downloader
from uncloud_engine.downloader import DownloadManager, DownloadState


@pytest.mark.parametrize('range_supported', [True, False])
def test_resume_handles_servers_that_ignore_range(tmp_path, monkeypatch, range_supported):
    target = tmp_path / 'weights.bin'
    target.with_suffix('.bin.part').write_bytes(b'abc')
    def respond(request):
        assert request.headers['Range'] == 'bytes=3-'
        if range_supported:
            return httpx.Response(206, content=b'def', headers={'Content-Range': 'bytes 3-5/6'})
        return httpx.Response(200, content=b'abcdef')
    client = httpx.AsyncClient
    monkeypatch.setattr(downloader.httpx, 'AsyncClient',
        lambda **kw: client(transport=httpx.MockTransport(respond), **kw))
    state = DownloadState('1', 'test', 'Test')
    asyncio.run(DownloadManager()._download_file(state, 'org/repo', 'weights.bin', target))
    assert target.read_bytes() == b'abcdef'
    assert not target.with_suffix('.bin.part').exists()


def test_pause_waits_for_transfer_to_stop_and_survives_restart(tmp_path):
    async def exercise():
        manager = DownloadManager(tmp_path / 'downloads.json')
        state = DownloadState('1', 'test', 'Test', status='downloading')
        manager.downloads[state.id] = state
        stopped = asyncio.Event()
        async def transfer():
            try:
                await asyncio.sleep(100)
            finally:
                stopped.set()
        state._task = asyncio.create_task(transfer())
        await asyncio.sleep(0)
        await manager.cancel('1')
        assert stopped.is_set()
        assert state.status == 'paused'
        restored = DownloadManager(manager.state_file)
        assert restored.downloads['1'].status == 'paused'
    asyncio.run(exercise())
