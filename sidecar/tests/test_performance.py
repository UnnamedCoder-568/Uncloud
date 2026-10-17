import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from uncloud_engine import performance, prefix_cache, vlm_server


def test_prefix_cache_is_optional_and_respects_explicit_preferences(monkeypatch):
    for key in ('APC_ENABLED', 'APC_NUM_BLOCKS', 'APC_EXACT_CACHE_ENTRIES'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr('importlib.util.find_spec', lambda _: None)
    vlm_server.configure_cache()
    import os
    assert 'APC_ENABLED' not in os.environ
    monkeypatch.setattr('importlib.util.find_spec', lambda _: object())
    vlm_server.configure_cache()
    assert os.environ['APC_ENABLED'] == '1'
    monkeypatch.setenv('APC_ENABLED', '0')
    vlm_server.configure_cache()
    assert os.environ['APC_ENABLED'] == '0'


def test_hybrid_cache_cap_checks_tensor_metadata_before_native_copy():
    calls = []

    class Manager:
        def store_exact_cache(self, tokens, cache, **kwargs):
            calls.append(tokens)
            return True

    prefix_cache.install(SimpleNamespace(APCManager=Manager))
    manager = Manager()
    assert manager.store_exact_cache([1], [SimpleNamespace(state=[SimpleNamespace(nbytes=16)])])
    assert not manager.store_exact_cache([2], [SimpleNamespace(state={
        'a': SimpleNamespace(nbytes=prefix_cache.SNAPSHOT_BYTES),
        'b': SimpleNamespace(nbytes=1)})])
    assert not manager.store_exact_cache([3], [SimpleNamespace(state=object())])
    assert calls == [[1]]


def test_native_metrics_are_on_demand_and_contain_no_chat_transcript(monkeypatch):
    from uncloud_engine import chat_transport
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, json={'latest': {'prompt_tokens': 12},
            'summary': {'in_flight': 0}, 'server': {}, 'unexpected': 'not forwarded'})

    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(chat_transport, 'client', lambda: client)
            active = SimpleNamespace(model_path='/model', engine='mlx-vlm',
                                     context_limit=8192, base_url='http://native')
            result = await performance.snapshot(active)
            assert result['native']['latest']['prompt_tokens'] == 12
            assert 'unexpected' not in result['native']
            active.engine = 'gguf'
            assert 'native' not in await performance.snapshot(active)

    asyncio.run(check())
    assert requests == ['http://native/metrics']


def test_benchmark_uses_one_resident_model_and_rejects_overlapping_work(monkeypatch):
    from uncloud_engine import main
    monkeypatch.setattr(main, '_chat_runs', {})
    monkeypatch.setattr(main, '_legacy_chat_active', 0)
    monkeypatch.setattr(main, 'principal_of', lambda _: 'local')
    monkeypatch.setattr(main.automations_service, 'current', None)
    active = SimpleNamespace(process=SimpleNamespace(poll=lambda: None),
        model_path='/loaded', engine='gguf', context_limit=8192)
    monkeypatch.setattr(main.engine_manager, 'active', active)
    seen = []
    release = None

    async def execute(run, body, selected):
        seen.append((body, selected))
        await release.wait()
        run.status = 'done'

    monkeypatch.setattr(main, '_run_chat', execute)

    async def check():
        nonlocal release
        release = asyncio.Event()
        run = await main.benchmark_model(None)
        with pytest.raises(HTTPException) as conflict:
            await main.benchmark_model(None)
        assert conflict.value.status_code == 409
        with pytest.raises(HTTPException):
            await main.start_chat_run(main.ChatBody(messages=[]), None)
        release.set()
        await main._chat_runs[run['id']].task
        body, selected = seen[0]
        assert selected is active and body.max_tokens == 128
        assert not body.web_tools and not body.history_tools and not body.chart_tools
        assert body.inference == {} and body.sampling == {}
        assert len(body.messages) == 1 and body.messages[0]['role'] == 'user'
        assert main._chat_runs[run['id']].timings['runtime']['model_path'] == '/loaded'

    asyncio.run(check())
