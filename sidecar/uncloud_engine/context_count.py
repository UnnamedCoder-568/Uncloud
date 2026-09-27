"""Count the actual model prompt using its native chat template and tokenizer.

Called only for the optional UI meter; ordinary chat never waits for it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

import httpx


@lru_cache(maxsize=4)
def _mlx_tokenizer(model_path: str):
    from mlx_lm.tokenizer_utils import load

    # Use the same wrapper as mlx_lm.server, including its thinking prefix.
    # Raw AutoTokenizer can omit those tokens and undercount the prompt.
    return load(Path(model_path), {"trust_remote_code": False, "local_files_only": True})


def _count_mlx(model_path: str, messages: list[dict]) -> int:
    tokenizer = _mlx_tokenizer(model_path)
    if any(not isinstance(m.get("content"), str) for m in messages):
        raise ValueError("Multimodal context requires backend token accounting")
    turns = [{"role": m["role"], "content": m["content"]}
             for m in messages if m.get("role") in ("system", "user", "assistant")
             and isinstance(m.get("content"), str)]
    if tokenizer.chat_template:
        encoded = tokenizer.apply_chat_template(
            turns, tokenize=True, add_generation_prompt=True)
        # Transformers versions differ: some return IDs, others BatchEncoding.
        ids = encoded["input_ids"] if isinstance(encoded, Mapping) else encoded
        if len(ids) and isinstance(ids[0], (list, tuple)):
            ids = ids[0]
        return len(ids)
    raise ValueError("The model does not provide a native chat template")


async def count(active, messages: list[dict]) -> int | None:
    if active.engine == "mlx":
        return await asyncio.to_thread(_count_mlx, active.model_path, messages)
    if active.engine != "gguf":
        return None
    async with httpx.AsyncClient(timeout=10) as client:
        # Current llama.cpp counts the fully rendered chat template here.
        response = await client.post(
            f"{active.base_url}/v1/chat/completions/input_tokens",
            json={"messages": messages})
        if response.is_success:
            data = response.json()
            value = data.get("input_tokens") or data.get("tokens")
            if isinstance(value, int):
                return value
            if isinstance(value, list):
                return len(value)
        # Older server builds expose these two endpoints instead. Keep the
        # model's template, rather than counting raw message text as if it
        # were the prompt the backend receives.
        template = await client.post(
            f"{active.base_url}/apply-template", json={"messages": messages})
        template.raise_for_status()
        prompt = template.json()["prompt"]
        tokens = await client.post(
            f"{active.base_url}/tokenize", json={"content": prompt,
                                                   "add_special": False,
                                                   "parse_special": True})
        tokens.raise_for_status()
        return len(tokens.json()["tokens"])
