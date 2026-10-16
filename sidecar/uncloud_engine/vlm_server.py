"""Native MLX-VLM server with a compact, schema-only tool header."""
from __future__ import annotations


def main() -> None:
    from mlx_vlm import server

    from .tool_template import install_vlm

    install_vlm(server)
    server.main()


if __name__ == '__main__':
    main()
