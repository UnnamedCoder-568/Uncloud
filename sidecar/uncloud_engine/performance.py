"""On-demand runtime measurements. No prompts, answers, or model loading."""
from __future__ import annotations

import httpx


async def snapshot(active) -> dict:
    result = {'running': True, 'model_path': active.model_path, 'engine': active.engine,
              'context_limit': active.context_limit}
    if active.engine == 'mlx-vlm':
        from .chat_transport import client

        try:
            response = await client().get(f'{active.base_url}/metrics', timeout=3)
            response.raise_for_status()
            data = response.json()
            result['native'] = {key: data.get(key) for key in ('latest', 'summary', 'server')}
        except (httpx.HTTPError, ValueError):
            result['native'] = None
    return result
