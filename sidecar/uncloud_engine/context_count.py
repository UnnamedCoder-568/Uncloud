"""Count the actual model prompt using its native chat template and tokenizer.

Shared by the UI meter, evidence fitting and rolling conversation context.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from .chat_transport import connection


@lru_cache(maxsize=4)
def _mlx_tokenizer(model_path: str):
    from mlx_lm.tokenizer_utils import load

    # Use the same wrapper as mlx_lm.server, including its thinking prefix.
    # Raw AutoTokenizer can omit those tokens and undercount the prompt.
    return load(Path(model_path), {"trust_remote_code": False, "local_files_only": True})


def _count_mlx(model_path: str, messages: list[dict], template_kwargs: dict | None = None) -> int:
    tokenizer = _mlx_tokenizer(model_path)
    if any(not isinstance(m.get("content"), str) for m in messages):
        raise ValueError("Multimodal context requires backend token accounting")
    turns = messages
    if tokenizer.chat_template:
        encoded = tokenizer.apply_chat_template(
            turns, tokenize=True, add_generation_prompt=True, **(template_kwargs or {})
        )
        # Transformers versions differ: some return IDs, others BatchEncoding.
        ids = encoded["input_ids"] if isinstance(encoded, Mapping) else encoded
        if len(ids) and isinstance(ids[0], (list, tuple)):
            ids = ids[0]
        return len(ids)
    raise ValueError("The model does not provide a native chat template")


async def count(active, messages: list[dict], inference: dict | None = None,
                *, web_tools: bool = False, history_tools: bool = False,
                chart_tools: bool = False,
                native_tools: list[dict] | None = None) -> int | None:
    from .inference_controls import apply
    from .tool_template import template_kwargs
    from .web_tools import chat_turns, definitions

    messages = chat_turns(messages)
    # A fully compacted idle chat has only retained memory until the next user
    # message. Native templates may reject system-only input; count the empty
    # draft user turn in that case. This is accounting only, never inference.
    if messages and not any(message.get('role') == 'user' for message in messages):
        messages = [*messages, {'role': 'user', 'content': ''}]
    tools = (native_tools if native_tools is not None
             else definitions(active, web_tools, history_tools, chart_tools))

    # Input tokenization depends on the native template, not on sampling or
    # output ceilings. A stale reply preference must not disable the meter.
    template_controls = (
        {"reasoning": inference["reasoning"]} if inference and "reasoning" in inference else {}
    )
    controls = apply(active, {}, template_controls)
    kwargs = controls.get("chat_template_kwargs", {})
    kwargs = {**kwargs, **template_kwargs(active, tools)}
    if tools:
        kwargs = {**kwargs, 'tools': tools}
    if active.engine == "mlx":
        if kwargs:
            return await asyncio.to_thread(_count_mlx, active.model_path, messages, kwargs)
        return await asyncio.to_thread(_count_mlx, active.model_path, messages)
    if active.engine == "mlx-vlm":
        turns = []
        for message in messages:
            if message.get('tool_calls'):
                turns.extend({'type': 'function_call', 'call_id': call['id'],
                              'name': call['function']['name'],
                              'arguments': call['function']['arguments']
                              if isinstance(call['function']['arguments'], str)
                              else json.dumps(call['function']['arguments'])}
                             for call in message['tool_calls'])
                continue
            if message['role'] == 'tool':
                turns.append({'type': 'function_call_output', 'call_id': message['tool_call_id'],
                              'output': message['content']})
                continue
            content = message.get("content")
            if isinstance(content, list):
                parts = []
                for item in content:
                    if item.get("type") == "text":
                        parts.append({"type": "input_text", "text": item["text"]})
                    elif item.get("type") == "image_url":
                        parts.append({"type": "input_image", "image_url": item["image_url"]["url"]})
                    else:
                        return None  # Do not invent counts for unknown modalities.
                content = parts
            turns.append({"role": message["role"], "content": content})
        async with connection() as client:
            response = await client.post(
                f"{active.base_url}/v1/responses/input_tokens",
                json={"model": active.model_path, "input": turns,
                      **({'tools': tools} if tools else {}),
                      **({"enable_thinking": controls["enable_thinking"]}
                         if "enable_thinking" in controls else {})}, timeout=10,
            )
            if not response.is_success:
                return None
            value = response.json().get("input_tokens")
            return value if isinstance(value, int) else None
    if active.engine != "gguf":
        return None
    async with connection() as client:
        # Current llama.cpp counts the fully rendered chat template here.
        response = await client.post(
            f"{active.base_url}/v1/chat/completions/input_tokens",
            json={"messages": messages, **({'tools': tools} if tools else {}),
                  **({"chat_template_kwargs": controls.get('chat_template_kwargs')}
                     if controls.get('chat_template_kwargs') else {})}, timeout=10,
        )
        if response.is_success:
            data = response.json()
            value = data.get("input_tokens", data.get("tokens"))
            if isinstance(value, int):
                return value
            if isinstance(value, list):
                return len(value)
        # Older server builds expose these two endpoints instead. Keep the
        # model's template, rather than counting raw message text as if it
        # were the prompt the backend receives.
        template = await client.post(
            f"{active.base_url}/apply-template",
            json={"messages": messages, **({'tools': tools} if tools else {}),
                  **({"chat_template_kwargs": controls.get('chat_template_kwargs')}
                     if controls.get('chat_template_kwargs') else {})}, timeout=10,
        )
        template.raise_for_status()
        prompt = template.json()["prompt"]
        tokens = await client.post(
            f"{active.base_url}/tokenize",
            json={"content": prompt, "add_special": False, "parse_special": True}, timeout=10,
        )
        tokens.raise_for_status()
        return len(tokens.json()["tokens"])
