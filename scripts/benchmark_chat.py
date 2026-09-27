"""Repeatable chat transport comparison against the same resident model.

Run using the sidecar environment. The legacy mode reproduces the prior library
scan, client construction and 180 ms UI polling; it does not change model input.
No model downloads, external APIs or user conversation data are used.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sidecar"))
from uncloud_engine import (
    chat_transport,
    inference_profile,
    library,
    main,
)
from uncloud_engine.chat import model_payload

CASES = [
    (
        "reasoning",
        ("A box has 3 red and 2 blue balls. Two are drawn without replacement. "
         "What is the probability both are red? Reply with only the simplified fraction."),
        "3/10",
    ),
    (
        "instruction",
        'Return exactly this JSON, with no explanation: {"ready":true,"count":3}',
        '{"ready":true,"count":3}',
    ),
    (
        "context",
        ("Project facts: code name Cedar, release Friday, budget 73 credits. "
         "Which code name and budget were specified? Answer in one sentence."),
        "73",
    ),
    (
        "coding",
        "Write only a Python function called add that returns the sum of its two arguments.",
        "return",
    ),
]


async def measure(mode, active, messages, model_dir, maximum):
    start = time.perf_counter()
    frames = []
    first = None
    payload = model_payload(
        active, messages, overrides={"temperature": 0, "seed": 42}, max_tokens=maximum
    )
    scan_ms = 0

    def accept(data):
        nonlocal first
        try:
            frame = json.loads(data)
        except ValueError:
            return
        delta = (frame.get("choices") or [{}])[0].get("delta", {})
        if first is None and any(
            delta.get(k) for k in ("content", "reasoning_content", "reasoning")
        ):
            first = (time.perf_counter() - start) * 1000
        frames.append(frame)

    if mode == "optimized":
        run = main.ChatRun(id="bench", owner="benchmark", started=start)
        task = asyncio.create_task(
            main._run_chat(
                run,
                main.ChatBody(
                    messages=messages,
                    sampling={"temperature": 0, "seed": 42},
                    max_tokens=maximum,
                    effort="balanced",
                ),
                active,
            )
        )
        cursor = 0
        while run.status == "running" or cursor < len(run.frames):
            for data in run.frames[cursor:]:
                accept(data)
            cursor = len(run.frames)
            if run.status == "running" and cursor == len(run.frames):
                run.changed.clear()
                await run.changed.wait()
        await task
        if run.error:
            raise RuntimeError(run.error)
    else:
        if mode == "legacy":
            tick = time.perf_counter()
            library.scan_library(model_dir)
            scan_ms = (time.perf_counter() - tick) * 1000
        buffered = []

        async def read():
            async with (
                httpx.AsyncClient(timeout=None, trust_env=False) as client,
                client.stream("POST", active.base_url + "/v1/chat/completions",
                              json=payload) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        if mode == "direct":
                            accept(line[6:])
                        else:
                            buffered.append(line[6:])

        task = asyncio.create_task(read())
        if mode == "legacy":
            cursor = 0
            while not task.done() or cursor < len(buffered):
                for data in buffered[cursor:]:
                    accept(data)
                cursor = len(buffered)
                if not task.done():
                    await asyncio.sleep(0.18)
        await task
    total = (time.perf_counter() - start) * 1000
    answer = "".join(
        (f.get("choices") or [{}])[0].get("delta", {}).get("content") or ""
        for f in frames
    )
    usage = next((f["usage"] for f in reversed(frames) if f.get("usage")), {})
    return {
        "mode": mode,
        "ttft_ms": first,
        "total_ms": total,
        "library_scan_ms": scan_ms,
        "usage": usage,
        "answer": answer,
        "finish_reason": next(((f.get("choices") or [{}])[0].get("finish_reason")
                               for f in reversed(frames)
                               if (f.get("choices") or [{}])[0].get("finish_reason")), None),
    }


async def run(args):
    profile, defaults = inference_profile.load(args.model_path, args.engine)
    active = SimpleNamespace(
        base_url=args.base_url,
        engine=args.engine,
        model_profile=profile,
        inference_profile=defaults,
    )
    records = []
    # Exclude the first request's model load and kernels from warm comparisons.
    cold = await measure(
        "direct",
        active,
        [{"role": "user", "content": "Say hello."}],
        Path(args.model_path).parent,
        args.max_tokens,
    )
    for index, (name, prompt, expected) in enumerate(CASES):
        # Rotate order to reduce cache/thermal ordering bias.
        modes = ["legacy", "optimized", "direct"]
        modes = modes[index % 3 :] + modes[: index % 3]
        for mode in modes:
            result = await measure(
                mode,
                active,
                [{"role": "user", "content": prompt}],
                Path(args.model_path).parent,
                args.max_tokens,
            )
            result.update(case=name, basic_check=expected in result["answer"])
            records.append(result)
            print(
                json.dumps(
                    {k: result[k] for k in ("case", "mode", "ttft_ms", "basic_check")}
                ),
                flush=True,
            )
    await chat_transport.close()
    quality = []
    if args.system_prompts:
        prompts = json.loads(Path(args.system_prompts).read_text())
        for name, system in prompts.items():
            for case, prompt, expected in CASES:
                result = await measure("direct", active, [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}],
                    Path(args.model_path).parent, args.max_tokens)
                result.update(prompt_version=name, case=case,
                              basic_check=expected in result["answer"])
                quality.append(result)
                print(json.dumps({"prompt": name, "case": case,
                                  "basic_check": result["basic_check"]}), flush=True)
    config = Path(args.model_path) / "config.json"
    report = {
        "model": Path(args.model_path).name,
        "engine": args.engine,
        "hardware": platform.machine(),
        "platform": platform.platform(),
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest()
        if config.is_file()
        else None,
        "sampling": {"temperature": 0, "seed": 42, "max_tokens": args.max_tokens},
        "cold_request": cold,
        "records": records,
        "prompt_quality": quality,
        "median_ttft_ms": {
            m: statistics.median(
                r["ttft_ms"]
                for r in records
                if r["mode"] == m and r["ttft_ms"] is not None
            )
            for m in ("direct", "legacy", "optimized")
        },
        "limits": [
            "One local model; not a cross-family intelligence evaluation",
            "Transport comparison excludes browser rendering and HTTP hop into sidecar",
            "Legacy path reconstructed with identical inference payload",
            "Basic checks do not establish general model intelligence",
        ],
    }
    Path(args.output).write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--engine", default="mlx", choices=["mlx", "gguf", "mlx-vlm"])
    parser.add_argument("--max-tokens", type=int, default=384)
    parser.add_argument("--output", required=True)
    parser.add_argument("--system-prompts", help="JSON of named system prompts to compare")
    asyncio.run(run(parser.parse_args()))
