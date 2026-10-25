"""Read plans incrementally; repeated reasoning must not occupy the runtime forever."""
from __future__ import annotations

import asyncio
import json as codec

import httpx


def repeated_reasoning(text: str) -> bool:
    tail = text[-4096:]
    for width in range(32, min(1024, len(tail) // 4) + 1):
        unit = tail[-width:]
        if len(unit.strip()) >= 16 and tail.endswith(unit * 4):
            return True
    return False


async def completion(client: httpx.AsyncClient, url: str, *, json: dict,
                     timeout: float) -> httpx.Response:
    content, reasoning, checked = '', '', 0
    calls = {}
    finish = None
    try:
        async with asyncio.timeout(timeout):
            async with client.stream('POST', url, json=json, timeout=timeout) as response:
                response.raise_for_status()
                # A backend may return a complete JSON response even when streaming
                # was requested. Keep that compatible path without guessing fields.
                if 'application/json' in response.headers.get('content-type', ''):
                    await response.aread()
                    return response
                async for line in response.aiter_lines():
                    if not line.startswith('data:'):
                        continue
                    data = line[5:].strip()
                    if data == '[DONE]':
                        break
                    chunk = codec.loads(data)
                    if chunk.get('error'):
                        raise RuntimeError(f"Planning backend error: {chunk['error']}")
                    for choice in chunk.get('choices', []):
                        if choice.get('index', 0) != 0:
                            continue
                        delta = choice.get('delta', {})
                        content += delta.get('content') or ''
                        for part in delta.get('tool_calls') or []:
                            index = part.get('index', 0)
                            if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                                raise ValueError('Invalid streamed tool-call index.')
                            call = calls.setdefault(index, {
                                'id': '', 'type': 'function',
                                'function': {'name': '', 'arguments': ''}})
                            if part.get('id'):
                                call['id'] = part['id']
                            for field in ('name', 'arguments'):
                                value = part.get('function', {}).get(field, '')
                                if not isinstance(value, str):
                                    raise ValueError('Invalid streamed tool-call fragment.')
                                call['function'][field] += value
                        reasoning += delta.get('reasoning_content') or delta.get('reasoning') or ''
                        if len(reasoning) - checked >= 128:
                            checked = len(reasoning)
                            if repeated_reasoning(reasoning):
                                raise ValueError('Repeated reasoning detected. '
                                                 'No usable plan returned.')
                            reasoning = reasoning[-8192:]
                            checked = len(reasoning)
                        if choice.get('finish_reason'):
                            finish = choice['finish_reason']
                if finish is None:
                    raise ValueError('The planning stream ended before a complete response.')
                message = {'content': content}
                if calls:
                    message['tool_calls'] = [calls[index] for index in sorted(calls)]
                return httpx.Response(200, request=response.request, json={'choices': [{
                    'message': message, 'finish_reason': finish,
                }]})
    except TimeoutError as exc:
        raise httpx.ReadTimeout('Planning exceeded its overall time limit.') from exc
