import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from uncloud_engine.generation_guard import ReasoningLoop


def test_sustained_reasoning_cycle_stops_without_another_model_request():
    block = ' '.join(f'thought-{number}' for number in range(100)) + '\n'
    guard = ReasoningLoop()
    with pytest.raises(RuntimeError, match='same thinking'):
        for offset in range(0, len(block * 8), 19):
            guard.push((block * 8)[offset:offset + 19])


def test_long_nonrepeating_thinking_is_not_cut_off_by_a_time_or_word_budget():
    guard = ReasoningLoop()
    for index in range(2000):
        guard.push(f'Distinct intermediate result number {index}: value {index * index}.\n')
    assert len(guard.tail) <= 24000


def test_a_single_restatement_does_not_trigger_the_cycle_guard():
    block = ' '.join(f'working-{number}' for number in range(100))
    ReasoningLoop().push(block * 2)


def test_repeated_native_reasoning_closes_the_stream_without_a_retry(monkeypatch):
    from uncloud_engine import chat_transport, main

    block = ' '.join(f'thought-{number}' for number in range(100)) + '\n'
    data = ''.join('data: ' + json.dumps({'choices': [{'delta': {
        'reasoning_content': block}}]}) + '\n\n' for _ in range(12))
    requests = []

    async def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, text=data)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr(chat_transport, 'client', lambda: client)
            active = SimpleNamespace(engine='gguf', base_url='http://model', context_limit=8192,
                                     inference_profile={'parameters': {}})
            run = main.ChatRun(id='cycle-test', owner='local')
            await main._run_chat(run, main.ChatBody(
                messages=[{'role': 'user', 'content': 'A task'}]), active)
            assert run.status == 'error' and 'same thinking' in run.error
            assert len(run.frames) < 12

    asyncio.run(exercise())
    assert len(requests) == 1
    assert requests[0]['messages'] == [{'role': 'user', 'content': 'A task'}]
