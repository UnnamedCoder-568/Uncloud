"""Choose a native MLX runtime from the checkpoint's declared components."""

from __future__ import annotations

import json
from pathlib import Path


def for_mlx_model(path: str | Path) -> str:
    path = Path(path)
    try:
        config = json.loads((path / "config.json").read_text())
        vision = config.get("vision_config")
        processor = (path / "processor_config.json").is_file() or (
            path / "preprocessor_config.json").is_file()
        if isinstance(vision, dict) and vision and processor:
            return "mlx-vlm"
    except (OSError, ValueError, AttributeError):
        pass
    return "mlx"
