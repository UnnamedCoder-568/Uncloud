"""Benchmark cold and warm speech worker requests using existing local weights.

No model downloads, playback or network access. Run with the engine's Python.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sidecar"))

from uncloud_engine.core.speech.worker import Worker


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("kokoro", "kokoro-mlx"), required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--text", default=("Welcome to Uncloud. Your models run locally, "
                                         "and your work stays on this device."))
    args = parser.parse_args()
    if not args.model.is_dir() or not 2 <= args.runs <= 20:
        parser.error("Choose an existing model folder and between 2 and 20 runs")
    args.output.mkdir(parents=True, exist_ok=True)
    worker = Worker(args.python, env={"HF_HUB_OFFLINE": "1"}, idle_seconds=0)
    rows = []
    try:
        for index in range(args.runs):
            out = args.output / f"{args.engine}-{index}.wav"
            if out.exists():
                parser.error(f"Output already exists: {out}; choose a new output folder")
            started = time.perf_counter()
            result = worker.request({"op": "speak", "engine": args.engine,
                                     "folder": str(args.model.resolve()), "voice": args.voice,
                                     "text": args.text, "out": str(out.resolve())}, timeout=120)
            elapsed = time.perf_counter() - started
            rows.append({"phase": "cold" if index == 0 else "warm",
                         "seconds": round(elapsed, 4), "audio_seconds": result["duration"],
                         "device": result["device"]})
    finally:
        worker.stop()
    print(json.dumps({"platform": platform.system(), "architecture": platform.machine(),
                      "cpu_count": os.cpu_count(), "engine": args.engine,
                      "model": str(args.model.resolve()), "voice": args.voice,
                      "text": args.text, "runs": rows}, indent=2))


if __name__ == "__main__":
    main()
