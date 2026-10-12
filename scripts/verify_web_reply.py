"""Bounded same-file checks for web handoff, final answers and native thinking.

Export actual frontend prompts to JSON; each case supplies messages and optional
inference overrides. Uses one isolated local engine and supplied evidence fixtures.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import dataclasses
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sidecar"))
from uncloud_engine import chat_transport, main
from uncloud_engine.chat import model_payload
from uncloud_engine.engines import EngineManager


def contains_expected(answer, value):
    # Mathematical formatting must not fail an otherwise identical fraction.
    normalized = re.sub(r"\\frac\s*\{\s*(\d+)\s*\}\s*\{\s*(\d+)\s*\}",
                        r"\1/\2", answer)
    return str(value).casefold() in normalized.casefold()


def correct_probability(answer, expected):
    """Reject a contradictory stated result, but allow intermediate fractions."""
    normalized = re.sub(r"\\frac\s*\{\s*(\d+)\s*\}\s*\{\s*(\d+)\s*\}",
                        r"\1/\2", answer).replace('**', '').replace('$', '')
    stated = re.search(r"(?:the probability is|answer\s*:)\s*(\d+\s*/\s*\d+)",
                       normalized, re.IGNORECASE)
    return contains_expected(answer, expected) and (
        stated is None or stated.group(1).replace(' ', '') == expected)


def other_models(owned_pid=None):
    rows = subprocess.check_output(["ps", "-axo", "pid=,ppid=,command="], text=True)
    return [int(parts[0]) for row in rows.splitlines()
            if len(parts := row.strip().split(None, 2)) == 3
            and int(parts[0]) != owned_pid and re.search(
                r"(?:-m\s+(?:mlx_lm|mlx_vlm|uncloud_engine\.mlx_server)\b|/llama-server\b)",
                parts[2])]


async def measure(active, case, maximum, deadline):
    if case.get("native_baseline"):
        profile = copy.deepcopy(active.inference_profile)
        profile["capabilities"]["reasoning"].pop("budget", None)
        active = dataclasses.replace(active, inference_profile=profile)
    messages = case["messages"]
    inference = {**({} if case.get("unseeded") else {"seed": 42}), **case.get("inference", {})}
    maximum = None if case.get("use_default_output") else maximum
    payload = model_payload(active, messages, max_tokens=maximum, inference=inference)
    started = time.perf_counter()
    first = None
    final_first = None
    frames = []
    run = main.ChatRun(id="web-reply-check", owner="benchmark", started=started)
    task = asyncio.create_task(main._run_chat(
        run, main.ChatBody(messages=messages, max_tokens=maximum, inference=inference), active,
    ))
    cursor = 0
    timed_out = False
    try:
        async with asyncio.timeout(deadline):
            while run.status == "running" or cursor < len(run.frames):
                for data in run.frames[cursor:]:
                    try:
                        frame = json.loads(data)
                    except ValueError:
                        continue
                    delta = (frame.get("choices") or [{}])[0].get("delta", {})
                    elapsed = (time.perf_counter() - started) * 1000
                    if first is None and any(delta.get(k) for k in ("content", "reasoning_content", "reasoning")):
                        first = elapsed
                    if final_first is None and delta.get("content"):
                        final_first = elapsed
                    frames.append(frame)
                cursor = len(run.frames)
                if case.get("cancel_after_first_token") and first is not None:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    break
                if run.status == "running" and cursor == len(run.frames):
                    run.changed.clear()
                    await run.changed.wait()
            if not case.get("cancel_after_first_token"):
                await task
    except TimeoutError:
        timed_out = True
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    if timed_out:
        run.status = 'timeout'
        run.error = f'Diagnostic deadline reached after {deadline} seconds.'
    deltas = [(f.get("choices") or [{}])[0].get("delta", {}) for f in frames]
    answer = "".join(d.get("content") or "" for d in deltas)
    thinking = "".join(d.get("reasoning_content") or d.get("reasoning") or "" for d in deltas)
    # Some native servers keep the think tags inside content.
    if "</think>" in answer:
        prefix, answer = answer.split("</think>", 1)
        thinking = prefix.removeprefix("<think>") + thinking
        answer = answer.strip()
    finish = next(((f.get("choices") or [{}])[0].get("finish_reason") for f in reversed(frames)
                   if (f.get("choices") or [{}])[0].get("finish_reason")), None)
    expected = case.get("expected", [])
    probability = case.get("expected_probability")
    return {
        "case": case["name"], "payload": payload, "status": run.status, "error": run.error,
        "first_frame_ms": first, "first_answer_ms": final_first,
        "total_ms": (time.perf_counter() - started) * 1000,
        "answer": answer, "thinking": thinking, "thinking_words": len(thinking.split()),
        "finish_reason": finish,
        "usage": next((f["usage"] for f in reversed(frames) if f.get("usage")), {}),
        "timings": run.timings,
        "checks": ({"cancelled": run.status == "cancelled", "stream_started": first is not None}
                   if case.get("cancel_after_first_token") else {
                       "final_answer": bool(answer.strip()), "finished": finish == "stop",
                       "expected": all(contains_expected(answer, value) for value in expected),
                       **({"probability": correct_probability(answer, probability)}
                          if probability else {})}),
        "expected_failure": bool(case.get("expected_failure")),
    }


async def run(args):
    if other_models():
        raise RuntimeError("Another local model is resident. Unload it before this test.")
    cases = json.loads(Path(args.cases).read_text())
    manager = EngineManager()
    config = Path(args.model_path) / "config.json"
    report = {
        "model": args.model_path, "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "platform": platform.platform(), "reply_tokens": args.reply_tokens, "seed": 42,
        "records": [], "limitations": ["One local Apple Silicon MLX model", "Synthetic web fixtures are not real product specifications",
                                          "Bounded diagnostic reply budget, not an intelligence benchmark"],
    }
    def save():
        Path(args.output).write_text(json.dumps(report, indent=2))
    async def watch(pid):
        while True:
            await asyncio.sleep(2)
            if other_models(pid):
                raise RuntimeError("Another local model started; this test stopped to protect RAM.")
    try:
        active = await manager.start(args.model_path, "mlx")
        report["profile"] = active.inference_profile
        report["context_limit"] = active.context_limit
        save()
        for case in cases:
            test = asyncio.create_task(measure(active, case, args.reply_tokens, args.deadline))
            watcher = asyncio.create_task(watch(active.process.pid))
            try:
                done, _ = await asyncio.wait({test, watcher}, return_when=asyncio.FIRST_COMPLETED)
                if watcher in done:
                    await watcher
                result = await test
            finally:
                test.cancel()
                watcher.cancel()
                await asyncio.gather(test, watcher, return_exceptions=True)
            report["records"].append(result)
            save()
            print(json.dumps({k: result[k] for k in ("case", "total_ms", "thinking_words", "finish_reason", "checks")}), flush=True)
    finally:
        save()
        manager.stop()
        await chat_transport.close()
        main._chat_runs.clear()
    return all(all(record["checks"].values()) or record["expected_failure"]
               for record in report["records"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--reply-tokens", type=int, default=2048)
    parser.add_argument("--deadline", type=int, default=120)
    sys.exit(0 if asyncio.run(run(parser.parse_args())) else 1)
