"""Bound optional native hybrid-cache snapshots without copying tensors."""
from __future__ import annotations

SNAPSHOT_BYTES = 512 * 1024 * 1024


def state_bytes(value) -> int:
    if isinstance(value, dict):
        return sum(state_bytes(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return sum(state_bytes(item) for item in value)
    if value is None or isinstance(value, (int, float, bool, str)):
        return 0
    size = getattr(value, 'nbytes', None)
    if isinstance(size, int) and size >= 0:
        return size
    raise ValueError('Unknown native cache tensor')


def install(apc) -> None:
    """Skip oversized snapshots; native generation simply recomputes them.

    Native exact caching keeps two entries. Limiting each to 512 MiB caps
    their extra tensor storage at 1 GiB, including manually enlarged windows.
    There is no disk cache and no changes to model state or sampling.
    """
    manager = getattr(apc, 'APCManager', None)
    if manager is None or not hasattr(manager, 'store_exact_cache'):
        return
    store = manager.store_exact_cache

    def bounded(self, token_ids, prompt_cache, **kwargs):
        try:
            size = sum(state_bytes(entry.state) for entry in prompt_cache)
        except (AttributeError, TypeError, ValueError):
            return False
        if size > SNAPSHOT_BYTES:
            return False
        return store(self, token_ids, prompt_cache, **kwargs)

    manager.store_exact_cache = bounded
