"""Sequential native/app comparisons, with one resident model and fixed inputs.

The before phase reuses an existing pre-update worker. The after phase refuses
any existing model worker and owns/stops exactly one worker at a time. No browser
is opened, no models are downloaded, and every output is preserved for inspection.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sidecar"))

import httpx
from uncloud_engine.chat import model_payload
from uncloud_engine.context_profile import for_model
from uncloud_engine.engines import EngineManager
from uncloud_engine.inference_profile import for_backend, load
from verify_web_reply import other_models

HISTORY = [
    {"role": "user", "content": "Hi. How are we doing today?"},
    {"role": "assistant", "content": "We are doing well, thank you for asking! How about you?"},
    {"role": "user", "content": "I'm doing good. Who are you?"},
]


async def measure(client, url, name, payload):
    start = time.perf_counter()
    first = first_answer = None
    answer = thinking = ""
    frames = []
    error = None
    try:
        async with asyncio.timeout(60):
            async with client.stream("POST", url + "/v1/chat/completions", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: ") or line[6:].strip() == "[DONE]":
                        continue
                    frame = json.loads(line[6:])
                    frames.append(frame)
                    delta = (frame.get("choices") or [{}])[0].get("delta", {})
                    text = delta.get("content") or ""
                    reason = delta.get("reasoning_content") or delta.get("reasoning") or ""
                    elapsed = (time.perf_counter() - start) * 1000
                    if first is None and (text or reason):
                        first = elapsed
                    if first_answer is None and text:
                        first_answer = elapsed
                    answer += text
                    thinking += reason
    except (httpx.HTTPError, TimeoutError, ValueError) as exc:
        error = str(exc) or type(exc).__name__
    return {"case": name, "payload": payload, "error": error,
            "first_token_ms": first, "first_answer_ms": first_answer,
            "total_ms": (time.perf_counter() - start) * 1000,
            "answer": answer, "thinking": thinking,
            "finish_reason": next((choice["finish_reason"] for frame in reversed(frames)
                for choice in frame.get("choices", []) if choice.get("finish_reason")), None),
            "usage": next((frame["usage"] for frame in reversed(frames) if frame.get("usage")), {})}


async def run(args):
    path = Path(args.model)
    _, profile = load(str(path), args.engine)
    context = for_model(str(path), args.engine)["effective_limit"]
    report = {"phase": "before" if args.port else "after", "model": str(path),
              "config_sha256": hashlib.sha256((path / "config.json").read_bytes()).hexdigest(),
              "weights": {p.name: {"bytes": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns}
                          for p in path.glob("*.safetensors")}, "context_limit": context,
              "requested_engine": args.engine, "records": [], "limitations": ["One Apple Silicon device", "Fixed seed 42",
                  "Small regression sample, not a broad intelligence benchmark"]}
    output = Path(args.output)

    def save(record):
        report["records"].append(record)
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({key: record[key] for key in
                         ("case", "first_token_ms", "total_ms", "finish_reason", "error")}), flush=True)

    manager = EngineManager()
    try:
        if args.port:
            url = f"http://127.0.0.1:{args.port}"
        else:
            if other_models():
                raise RuntimeError("Another model worker is resident; no second model was started.")
            active = await manager.start(str(path), args.engine)
            url = active.base_url
            report["engine"] = active.engine
            report["profile"] = active.inference_profile
        async with httpx.AsyncClient(timeout=None, trust_env=False) as client:
            if args.port:
                common = {"stream": True, "stream_options": {"include_usage": True}, "seed": 42,
                          **for_backend(profile["parameters"], {}, "mlx")}
                before = {**common, "messages": [{"role": "system", "content":
                    "You are being read aloud. Answer in one or two sentences. No lists, no "
                    "markdown, no headings — none of it survives being spoken."}, *HISTORY],
                    "max_tokens": 512, "thinking_budget_tokens": 64}
                save(await measure(client, url, "reported_old_style_and_automatic_budget", before))
                baseline = {**common, "messages": HISTORY, "max_tokens": context - 1}
                save(await measure(client, url, "native_identity_without_app_rules", baseline))
            else:
                levels = active.inference_profile.get("capabilities", {}).get(
                    "reasoning", {}).get("levels", ["auto"])
                cases = [
                    ("auto_greeting", [{"role": "user", "content": HISTORY[0]["content"]}], {}),
                    ("auto_identity_followup", HISTORY, {}),
                    ("auto_probability", [{"role": "user", "content":
                        "A bag has 3 red balls and 2 blue balls. Draw two without replacement. "
                        "What is the probability both are red? Give the exact fraction and one short explanation."}], {}),
                    ("auto_code", [{"role": "user", "content":
                        "Write a Python function square(x) that returns x multiplied by itself. Return only code."}], {}),
                    ("manual_identity", HISTORY,
                     {"max_tokens": 128, **({"reasoning": "off"} if "off" in levels else {})}),
                    ("context_recall", [
                        {"role": "user", "content": "The project is Cedar, the budget is 48 dollars, "
                            "and the deadline is Tuesday. Publishing is prohibited."},
                        {"role": "assistant", "content": "Understood."},
                        {"role": "user", "content": "State the project, budget, deadline, "
                            "and whether publishing is permitted."},
                    ], {}),
                    ("native_thinking_probability", [{"role": "user", "content":
                        "A bag has 3 red balls and 2 blue balls. Draw two without replacement. "
                        "What is the probability both are red? Give the exact fraction and one short explanation."}],
                     {"reasoning": "high"}),
                ]
                # Warmup is recorded separately; it is not compared to a warm baseline.
                warm = model_payload(active, [{"role": "user", "content": "Hello"}],
                                     inference={"max_tokens": 32, "seed": 42,
                                                **({"reasoning": "off"} if "off" in levels else {})})
                save(await measure(client, url, "cold_warmup", warm))
                for name, messages, overrides in cases:
                    if args.case and name not in args.case:
                        continue
                    if name == "native_thinking_probability" and "high" not in levels:
                        report.setdefault("skipped", []).append({"case": name,
                            "reason": "The native template does not support thinking controls."})
                        continue
                    if other_models(active.process.pid):
                        raise RuntimeError("Another worker appeared; stopping this test to protect RAM.")
                    payload = model_payload(active, messages, inference={"seed": 42, **overrides})
                    record = await measure(client, url, name, payload)
                    save(record)
                    if name == "auto_identity_followup":
                        # Direct native HTTP with identical prompt/sampling/template controls.
                        # No app router, project, history store or model pass participates.
                        baseline = await measure(client, url, "matched_native_identity", copy.deepcopy(payload))
                        baseline["same_answer"] = baseline["answer"] == record["answer"]
                        save(baseline)
                if args.compact:
                    from uncloud_engine.compaction import compact
                    from uncloud_engine.context_count import count

                    context = [{"role": "user", "content": "The project is Cedar. The budget is "
                        "48 dollars. The deadline is Tuesday. Do not publish anything."}]
                    for index in range(30):
                        context.extend([
                            {"role": "user", "content": f"Completed review {index}: we checked "
                                "the draft layout, confirmed its spacing and archived the obsolete note. "
                                "There is no new task or budget change."},
                            {"role": "assistant", "content": f"Review {index} is complete. "
                                "The old layout note is archived and the current constraints still apply."},
                        ])
                    started = time.perf_counter()
                    before = await count(active, context)
                    async with asyncio.timeout(90):
                        result = await compact(active, context, inference={"seed": 42})
                    memory = result["summary"]
                    recall = [{"role": "system", "content": memory},
                        {"role": "user", "content": "State the project, budget, deadline, "
                            "and whether publishing is permitted."}]
                    after = await count(active, recall)
                    report["compaction"] = {"summary": memory, "before_tokens": before,
                        "after_tokens": after, "seconds": time.perf_counter()-started,
                        "reduced_context": after < before, "stages": len(result['stages'])}
                    save(await measure(client, url, "compacted_context_recall",
                        model_payload(active, recall, inference={"seed": 42})))
    finally:
        manager.stop()
        output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--port", type=int)
    parser.add_argument("--engine", choices=["mlx", "mlx-vlm"], default="mlx")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--compact", action="store_true")
    asyncio.run(run(parser.parse_args()))
