"""Native MLX-VLM server with a compact, schema-only tool header."""
from __future__ import annotations


def configure_cache() -> None:
    """Use native prefix reuse when the installed runtime supports it.

    Memory only: two native snapshots for hybrid models, a bounded block pool
    for ordinary attention. No prompt files or additional weights are loaded.
    Explicit operator environment values always take precedence.
    """
    import importlib.util
    import os

    if importlib.util.find_spec('mlx_vlm.apc') is not None:
        for name, value in {'APC_ENABLED': '1', 'APC_NUM_BLOCKS': '256',
                            'APC_EXACT_CACHE_ENTRIES': '2'}.items():
            os.environ.setdefault(name, value)


def main() -> None:
    configure_cache()
    import importlib.util

    from mlx_vlm import server

    if importlib.util.find_spec('mlx_vlm.apc') is not None:
        from mlx_vlm import apc

        from .prefix_cache import install

        install(apc)
    from .tool_template import install_vlm

    install_vlm(server)
    server.main()


if __name__ == '__main__':
    main()
