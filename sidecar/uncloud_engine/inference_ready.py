"""Initialize native inference during model loading, without saved answers."""
from __future__ import annotations

import time

import httpx


async def prepare(active) -> dict:
    # llama.cpp already runs its own warm-up before its health check succeeds.
    if active.engine not in {'mlx', 'mlx-vlm'}:
        return {'source': 'native runtime'}
    started = time.perf_counter()
    payload = {
        'messages': [{'role': 'user', 'content': '.'}],
        'stream': False, 'max_tokens': 1, 'temperature': 0,
    }
    if active.engine == 'mlx-vlm':
        payload['model'] = active.model_path
        if active.adapter_path:
            payload['adapter_path'] = active.adapter_path
    # MLX-LM's default_model alias preserves its CLI-selected adapter. Naming
    # the raw checkpoint here would bypass that mapping and reload base weights.
    # No tool schemas, history, system instructions or user request is sent.
    # Greedy initialization does not consume the model's sampling RNG. Its
    # one-token result is discarded and never becomes a chat message.
    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            response = await client.post(f'{active.base_url}/v1/chat/completions', json=payload)
            response.raise_for_status()
            if not response.json().get('choices'):
                raise ValueError('Native initialization returned no completion.')
        from .context_count import count

        # MLX-LM's meter owns a separate CPU tokenizer. Initialize that here
        # too, so loading it cannot delay the user's first Send.
        if active.engine == 'mlx':
            await count(active, payload['messages'])
        return {'source': 'one-token initialization', 'ready': True,
                'duration_ms': (time.perf_counter() - started) * 1000}
    except (httpx.HTTPError, ValueError, OSError) as exc:
        # An older runtime may reject minimal input. Keep it usable and report
        # the failed initialization; never retry or generate a hidden answer.
        return {'source': 'one-token initialization', 'ready': False,
                'duration_ms': (time.perf_counter() - started) * 1000,
                'error': type(exc).__name__}
