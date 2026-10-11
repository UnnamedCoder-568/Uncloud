"""Same-file native/direct/Uncloud checks, with real continuity compaction.

Run in the sidecar environment with UNCLOUD_CONFIG_DIR pointing at an isolated
directory. Never loads personal conversations or executes agent tools.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import time
from pathlib import Path

from benchmark_chat import measure
from evaluate_chat_quality import CASES, factual_grade, fixture
from uncloud_engine import chat_transport, compaction, main
from uncloud_engine.agent import orchestrator as planning
from uncloud_engine.context_count import count
from uncloud_engine.engines import EngineManager


async def run(args):
    manager = EngineManager()
    report = {
        "model_file": args.model_path,
        "platform": platform.platform(),
        "records": [],
        "limitations": [
            "One Apple Silicon MLX model, not all model families",
            "Transport measurement excludes Rust/frontend dispatch",
            "No OS notification delivery or Windows/CUDA hardware claim",
        ],
        "sampling": {"temperature": 0, "seed": 42},
        "compaction": [],
    }

    def save():
        Path(args.output).write_text(json.dumps(report, indent=2))

    started = time.perf_counter()
    try:
        active = await manager.start(args.model_path, "mlx")
        report["cold_readiness_ms"] = (time.perf_counter() - started) * 1000
        report["capabilities"] = active.inference_profile["capabilities"]
        report["effective_context"] = active.context_limit
        save()
        for name, prompt, expected in [] if args.skip_quality else CASES:
            for mode in ("direct", "optimized"):
                result = await measure(
                    mode,
                    active,
                    [{"role": "user", "content": prompt}],
                    Path(args.model_path).parent,
                    args.reply_tokens,
                )
                result.update(
                    case=name,
                    expected=expected,
                    factual=factual_grade(result["answer"], expected),
                )
                report["records"].append(result)
                save()
                print(
                    json.dumps(
                        {
                            "case": name,
                            "mode": mode,
                            "ttft_ms": result["ttft_ms"],
                            "passed": result["factual"]["passed"],
                        }
                    ),
                    flush=True,
                )
        report["warmup"] = await measure(
            "direct",
            active,
            [{"role": "user", "content": "Return exactly: ready"}],
            Path(args.model_path).parent,
            args.reply_tokens,
        )
        report["balanced_benchmark"] = []
        for round_number in range(args.benchmark_rounds):
            modes = (
                ("direct", "optimized")
                if round_number % 2 == 0
                else ("optimized", "direct")
            )
            for mode in modes:
                result = await measure(
                    mode,
                    active,
                    [
                        {
                            "role": "user",
                            "content": 'Return exactly this JSON: {"ready":true,"count":3}',
                        }
                    ],
                    Path(args.model_path).parent,
                    args.reply_tokens,
                )
                result["round"] = round_number
                report["balanced_benchmark"].append(result)
                save()
        report["median_ttft_ms"] = {
            mode: statistics.median(
                r["ttft_ms"]
                for r in report["balanced_benchmark"]
                if r["mode"] == mode and r["ttft_ms"] is not None
            )
            for mode in ("direct", "optimized")
        } if args.benchmark_rounds else {}
        save()
        if args.quality_only:
            return
        # The production compactor receives only the older selected prefix.
        history = fixture()
        memory = await compaction.compact(
            active, history[:-2], inference={"temperature": 0, "seed": 42}
        )
        before = await count(active, history)
        compacted = [{"role": "system", "content": memory["summary"]}, *history[-2:]]
        after = await count(active, compacted)
        report["compaction"].append({**memory, "before": before, "after": after})
        save()
        question = {
            "role": "user",
            "content": "Return JSON only: project, owner, budget, release, database, export, workspace, reference, cloud_allowed and delete_original. Use the current authoritative decisions.",
        }
        expected = {
            "project": "Juniper",
            "owner": "Nila",
            "budget": 63,
            "release": "Tuesday",
            "database": "SQLite",
            "export": "CSV",
            "workspace": "/projects/juniper",
            "reference": "LIB-42",
            "cloud_allowed": False,
            "delete_original": False,
        }
        for label, turns in (
            ("full_context", history),
            ("compacted_context", compacted),
        ):
            result = await measure(
                "optimized",
                active,
                [*turns, question],
                Path(args.model_path).parent,
                args.reply_tokens,
            )
            result.update(
                case=label,
                expected=expected,
                factual=factual_grade(result["answer"], expected),
            )
            report["records"].append(result)
            save()
            print(
                json.dumps({"case": label, "passed": result["factual"]["passed"]}),
                flush=True,
            )
        report["exact_prohibition_retained"] = (
            "Never delete the original catalogue." in memory["summary"]
        )
        updates = [
            {
                "role": "user",
                "content": "Nila has now approved the migration. Test accented author names remains unresolved. Release moves to Wednesday. Preserve all other decisions.",
            },
            {"role": "assistant", "content": "Recorded."},
        ]
        incremental = await compaction.compact(
            active, updates, memory["summary"], inference={"temperature": 0, "seed": 42}
        )
        report["incremental_compaction"] = incremental
        expected["release"] = "Wednesday"
        result = await measure(
            "optimized",
            active,
            [{"role": "system", "content": incremental["summary"]}, question],
            Path(args.model_path).parent,
            args.reply_tokens,
        )
        result.update(
            case="incremental_compacted_context",
            expected=expected,
            factual=factual_grade(result["answer"], expected),
        )
        report["records"].append(result)
        save()
        # Plan only: no tool effects. Exact same contract/native controls.
        planning.engine_manager.active = active
        original_specs = planning._active_tool_specs
        planning._active_tool_specs = lambda: [
            {
                "id": "ask_user",
                "description": "Ask a question.",
                "args": ["question", "options"],
            }
        ]
        try:
            graph = await planning.Orchestrator().plan(
                "Ask which colour I prefer, red or green.",
                inference={
                    "temperature": 0,
                    "seed": 42,
                    "max_tokens": args.reply_tokens,
                },
            )
            report["chisel_native_plan"] = graph.to_dict()
        finally:
            planning._active_tool_specs = original_specs
            planning.engine_manager.active = None
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        save()
        manager.stop()
        await chat_transport.close()
        # The benchmark's completion events stay in its isolated configuration.
        main._chat_runs.clear()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--reply-tokens", type=int, default=1536)
    parser.add_argument("--skip-quality", action="store_true")
    parser.add_argument("--quality-only", action="store_true")
    parser.add_argument("--benchmark-rounds", type=int, default=4)
    asyncio.run(run(parser.parse_args()))
