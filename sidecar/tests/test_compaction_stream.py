import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from uncloud_engine import compaction


class Stream(httpx.AsyncByteStream):
    def __init__(self, frames=(), stall=False):
        self.frames, self.stall, self.closed = frames, stall, False

    async def __aiter__(self):
        for frame in self.frames:
            yield ('data: ' + json.dumps({'choices': [frame]}) + '\n\n').encode()
        if self.stall:
            await asyncio.sleep(100)

    async def aclose(self):
        self.closed = True


def install_client(monkeypatch, stream):
    requests = []
    original = httpx.AsyncClient

    async def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, stream=stream)

    monkeypatch.setattr(compaction.httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(handle), **kwargs))

    async def count(*args):
        return 100

    monkeypatch.setattr(compaction, 'count', count)
    return requests


def active():
    return SimpleNamespace(engine='gguf', base_url='http://model', context_limit=8192,
                           inference_profile={})


def test_compaction_stream_returns_structured_memory_and_releases_its_slot(monkeypatch):
    memory = json.dumps({'current_facts': {'code': 42}, 'active_constraints': [],
                         'open_tasks': [], 'references': []})
    stream = Stream([{'delta': {'reasoning_content': 'A short reasoning step.'}},
                     {'delta': {'content': memory}, 'finish_reason': 'stop'}])
    requests = install_client(monkeypatch, stream)
    result = asyncio.run(compaction.compact(active(), [{'role': 'user', 'content': 'Code 42.'}]))
    assert json.loads(result['summary'])['current_facts']['code'] == 42
    assert stream.closed and not compaction.is_running()
    assert len(requests) == 1 and requests[0]['stream'] is True
    assert 'tools' not in requests[0]  # Summary work does not browse or change identity.


def test_compaction_deadline_closes_a_stalled_stream_without_retry(monkeypatch):
    stream = Stream(stall=True)
    requests = install_client(monkeypatch, stream)
    monkeypatch.setattr(compaction, 'TIMEOUT_SECONDS', 0.02)
    with pytest.raises(ValueError, match='timed out'):
        asyncio.run(compaction.compact(active(), [{'role': 'user', 'content': 'A fact'}]))
    assert stream.closed and not compaction.is_running() and len(requests) == 1


def test_compaction_stops_exact_thinking_cycles_before_the_deadline(monkeypatch):
    thought = ' '.join(f'repeated-{index}' for index in range(100)) + '\n'
    stream = Stream([{'delta': {'reasoning_content': thought}}] * 12)
    requests = install_client(monkeypatch, stream)
    with pytest.raises(ValueError, match='same thinking'):
        asyncio.run(compaction.compact(active(), [{'role': 'user', 'content': 'A fact'}]))
    assert stream.closed and not compaction.is_running() and len(requests) == 1


def test_user_cancellation_closes_the_summary_stream_and_allows_another_request(monkeypatch):
    stream = Stream(stall=True)
    requests = install_client(monkeypatch, stream)

    async def exercise():
        task = asyncio.create_task(compaction.compact(
            active(), [{'role': 'user', 'content': 'A fact'}]))
        while not requests:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert stream.closed and not compaction.is_running() and len(requests) == 1
