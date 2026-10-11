import asyncio
import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from uncloud_engine import downloader
from uncloud_engine.catalog import CatalogEntry
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


def test_model_progress_is_cumulative_and_completion_cannot_restart(tmp_path, monkeypatch):
    entry = CatalogEntry('test', 'Test', 'text', 'mlx', 'org/repo')
    metadata = SimpleNamespace(sha='pinned-revision', siblings=[
        SimpleNamespace(rfilename='one.bin', size=3),
        SimpleNamespace(rfilename='two.bin', size=3),
    ])
    monkeypatch.setitem(sys.modules, 'huggingface_hub', SimpleNamespace(
        HfApi=lambda: SimpleNamespace(model_info=lambda **kw: metadata)))
    monkeypatch.setattr(downloader, 'get_entry', lambda _: entry)
    monkeypatch.setattr(downloader, 'settings', SimpleNamespace(
        models_dir=tmp_path, hidden_models=[]))
    client = httpx.AsyncClient
    requests = []
    def respond(request):
        requests.append(str(request.url))
        assert '/pinned-revision/' in str(request.url)
        return httpx.Response(200, content=b'abc')
    monkeypatch.setattr(downloader.httpx, 'AsyncClient',
        lambda **kw: client(transport=httpx.MockTransport(respond), **kw))

    async def exercise():
        manager = DownloadManager(tmp_path / 'downloads.json')
        samples = []
        original = manager._download_file
        async def transfer(*args, **kw):
            await original(*args, **kw)
            samples.append((args[0].downloaded_bytes, args[0].percent))
        monkeypatch.setattr(manager, '_download_file', transfer)
        state = manager.start('test')
        await state._task
        assert state.status == 'done'
        assert state.total_bytes == state.downloaded_bytes == 6
        assert samples == [(3, 50.0), (6, 99.9)]
        assert state.percent == 100 and state.stage == 'Complete'
        assert manager.start('test') is state
        assert len(requests) == 2
        restored = DownloadManager(manager.state_file)
        assert restored.downloads[state.id].files == state.files
        assert restored.downloads[state.id].status == 'done'
    asyncio.run(exercise())


def test_resume_preserves_other_shards_and_partial_bytes(tmp_path, monkeypatch):
    (tmp_path / 'one.bin').write_bytes(b'abc')
    (tmp_path / 'two.bin.part').write_bytes(b'a')
    state = DownloadState('1', 'test', 'Test', status='paused', dest=str(tmp_path), files=[
        {'repo': 'org/repo', 'filename': 'one.bin', 'size': 3, 'revision': 'pinned'},
        {'repo': 'org/repo', 'filename': 'two.bin', 'size': 3, 'revision': 'pinned'},
    ])
    entry = CatalogEntry('test', 'Test', 'text', 'mlx', 'org/repo')
    monkeypatch.setattr(downloader, 'get_entry', lambda _: entry)
    monkeypatch.setattr(downloader, 'settings', SimpleNamespace(hidden_models=[]))
    client = httpx.AsyncClient
    def respond(request):
        assert request.url.path.endswith('/pinned/two.bin')
        assert request.headers['Range'] == 'bytes=1-'
        return httpx.Response(206, content=b'bc', headers={'Content-Range': 'bytes 1-2/3'})
    monkeypatch.setattr(downloader.httpx, 'AsyncClient',
        lambda **kw: client(transport=httpx.MockTransport(respond), **kw))
    async def exercise():
        manager = DownloadManager(tmp_path / 'state.json')
        manager.downloads[state.id] = state
        manager.resume('1')
        await state._task
        assert state.status == 'done'
        assert state.downloaded_bytes == state.total_bytes == 6
        assert (tmp_path / 'one.bin').read_bytes() == b'abc'
        assert (tmp_path / 'two.bin').read_bytes() == b'abc'
    asyncio.run(exercise())


def test_short_response_stays_partial_and_never_claims_completion(tmp_path, monkeypatch):
    client = httpx.AsyncClient
    monkeypatch.setattr(downloader.httpx, 'AsyncClient', lambda **kw: client(
        transport=httpx.MockTransport(lambda _: httpx.Response(
            200, content=b'abc', headers={'Content-Length': '6'})), **kw))
    target = tmp_path / 'weights.bin'
    state = DownloadState('1', 'test', 'Test', total_bytes=6)
    with pytest.raises(ValueError, match='incomplete'):
        asyncio.run(DownloadManager()._download_file(
            state, 'org/repo', 'weights.bin', target, size=6))
    assert not target.exists()
    assert target.with_suffix('.bin.part').read_bytes() == b'abc'
    assert state.percent < 100


def test_partial_catalogue_download_is_not_an_installed_model(tmp_path, monkeypatch):
    from uncloud_engine import library

    entry = CatalogEntry('test-model', 'Test', 'text', 'mlx', 'org/repo')
    model = tmp_path / entry.id
    model.mkdir()
    (model / 'config.json').write_text('{"model_type":"qwen3"}')
    (model / 'weights.safetensors.part').write_bytes(b'incomplete')
    marker = model / '.uncloud-download.json'
    marker.write_text(json.dumps({'status': 'downloading'}))
    monkeypatch.setattr(library, 'get_catalog', lambda: [entry])
    assert not any(item.catalog_id == entry.id for item in library.scan_library(tmp_path))
    marker.unlink()
    assert not any(item.catalog_id == entry.id for item in library.scan_library(tmp_path))
    (model / 'weights.safetensors.part').unlink()
    (model / 'weights.safetensors').write_bytes(b'complete')
    marker.write_text(json.dumps({'status': 'done'}))
    assert any(item.catalog_id == entry.id for item in library.scan_library(tmp_path))
