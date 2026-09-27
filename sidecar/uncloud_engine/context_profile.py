"""Model context windows, constrained by the backend and local KV memory."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .core.models.headers import read_gguf


def _positive_int(value: object) -> int | None:
    return (
        int(value) if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
    )


@lru_cache(maxsize=32)
def describe(model_path: str, engine: str, total_memory_gb: float) -> dict:
    path = Path(model_path)
    native: int | None = None
    kv_bytes_per_token: int | None = None
    source = "Runtime fallback; model context metadata is unavailable"
    if engine == "gguf" and path.is_file():
        header = read_gguf(path)
        if header:
            arch = header.architecture
            fields = header.fields
            native = _positive_int(fields.get(f"{arch}.context_length"))
            if native:
                source = f"GGUF {arch}.context_length"
            blocks = _positive_int(fields.get(f"{arch}.block_count"))
            width = _positive_int(fields.get(f"{arch}.embedding_length"))
            heads = _positive_int(fields.get(f"{arch}.attention.head_count"))
            kv_heads = _positive_int(fields.get(f"{arch}.attention.head_count_kv")) or heads
            key_length = _positive_int(fields.get(f"{arch}.attention.key_length"))
            value_length = _positive_int(fields.get(f"{arch}.attention.value_length"))
            if blocks and kv_heads and (key_length or (width and heads)):
                head_width = width // heads if width and heads else 0
                kv_bytes_per_token = (
                    blocks
                    * kv_heads
                    * ((key_length or head_width) + (value_length or head_width))
                    * 2
                )
    elif engine in ("mlx", "mlx-vlm") and path.is_dir():
        try:
            data = json.loads((path / "config.json").read_text())
            text = data.get("text_config", data)
            native = next(
                (
                    number
                    for key in (
                        "max_position_embeddings",
                        "max_sequence_length",
                        "model_max_length",
                    )
                    if (number := _positive_int(text.get(key))) is not None
                ),
                None,
            )
            if native:
                source = "Model config.json"
            blocks = _positive_int(text.get("num_hidden_layers"))
            heads = _positive_int(text.get("num_attention_heads"))
            kv_heads = _positive_int(text.get("num_key_value_heads")) or heads
            width = _positive_int(text.get("hidden_size"))
            head_width = _positive_int(text.get("head_dim")) or (
                width // heads if width and heads else None
            )
            if blocks and kv_heads and head_width:
                kv_bytes_per_token = blocks * kv_heads * head_width * 4
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    # llama.cpp receives this exact size at launch. The KV estimate is
    # conservative fp16 and leaves room for weights, OS, prompt and output.
    # A model with no reliable KV metadata uses the previous safe runtime cap.
    effective = native or 8192
    if engine in ("gguf", "mlx", "mlx-vlm"):
        if kv_bytes_per_token and total_memory_gb > 0:
            weights_gb = (
                path.stat().st_size
                if path.is_file()
                else sum(p.stat().st_size for p in path.glob("*.safetensors"))
            ) / 1e9
            kv_budget = max(0.5, (total_memory_gb - weights_gb - 3) * 0.5) * 1e9
            memory_limit = max(1024, int(kv_budget / kv_bytes_per_token) // 256 * 256)
            effective = min(effective, memory_limit)
        else:
            effective = min(effective, 8192)
    return {
        "native_limit": native,
        "effective_limit": effective,
        "source": source,
        "limited_by_memory": bool(native and effective < native),
    }


@lru_cache(maxsize=32)
def for_model(model_path: str, engine: str) -> dict:
    from .core.hardware import detect

    memory = detect().usable_memory_gb
    return describe(model_path, engine, memory)
