"""Bounded repeat-use checks, isolated from the owner's stored conversations."""
import asyncio
import secrets


def test_hundred_conversations_keep_identity_and_context(tmp_path, monkeypatch):
    from uncloud_engine import conversations as c
    class Vault:
        is_secure = True
        backend = 'test'
        def key(self): return key
    key = secrets.token_bytes(32)
    monkeypatch.setattr(c, 'DIR', tmp_path / 'conversations')
    monkeypatch.setattr(c, 'vault', Vault())
    saved = []
    for i in range(100):
        message = [{'role': 'user', 'content': f'Project {i}: retain constraint {i * 7}.'}]
        record = c.save(c.create(message))
        saved.append((record.id, message))
    assert len({identity for identity, _ in saved}) == 100
    for identity, message in reversed(saved):
        assert c.load(identity).messages == message


def test_cancelled_queue_never_executes_in_repeated_batches():
    from uncloud_engine.image_engine import ImageEngine
    async def exercise():
        engine = ImageEngine()
        executed = []
        async def render(job, *args):
            executed.append(job.id)
            job.status = 'done'
        engine._run_now = render
        for round_ in range(20):
            jobs = [engine.start('test-model', 'mflux', 'test prompt', seed=round_*5+i) for i in range(5)]
            engine.cancel()
            for _ in range(100):
                if all(j.to_dict()['done'] for j in jobs): break
                await asyncio.sleep(.001)
            assert all(j.status == 'cancelled' for j in jobs)
        assert executed == []
    asyncio.run(exercise())


def test_concurrent_module_reads_and_unauthenticated_writes(monkeypatch):
    import httpx
    from uncloud_engine import main
    monkeypatch.setattr(main, 'scan_library_cached', lambda *args, **kwargs: [])
    routes = ['/api/settings', '/api/permissions', '/api/engine/status',
              '/api/training/presets', '/api/training', '/api/adapters',
              '/api/skills', '/api/recipes', '/api/automations', '/api/outputs']
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            for _ in range(5):
                results = await asyncio.gather(*[client.get(path, headers={'Authorization': f'Bearer {main.settings.token}'}) for path in routes])
                for path, response in zip(routes, results):
                    assert response.status_code == 200, (path, response.status_code, response.text)
            denied = await asyncio.gather(*[client.post('/api/engine/stop') for _ in range(20)])
            assert all(response.status_code == 401 for response in denied)
    asyncio.run(exercise())
