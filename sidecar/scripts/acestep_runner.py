"""One-shot ACE-Step generation, executed by the isolated .venv-acestep interpreter.

The `acestep` console script launches a server/UI rather than generating once, so we
drive the documented Python API instead. Parameters arrive as a JSON blob on argv to
avoid quoting problems with lyrics, and the resulting path is printed on the last line.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    import os

    cfg = json.loads(sys.argv[1])

    # ACE-Step resolves weights from ACESTEP_CHECKPOINTS_DIR, falling back to
    # <project_root>/checkpoints. Without this it ignores the model we already
    # downloaded and pulls a second ~10GB copy of its own. Must be set before the
    # package is imported, since the path is captured at import time.
    os.environ.setdefault("ACESTEP_CHECKPOINTS_DIR", cfg["model_dir"])
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from acestep.llm_inference import LLMHandler

    checkpoint_dir = cfg["model_dir"]
    save_dir = cfg["save_dir"]
    Path(save_dir).mkdir(parents=True, exist_ok=True)

    device = cfg.get("device") or "mps"

    dit = AceStepHandler()
    init_status, enable_generate = dit.initialize_service(
        project_root=checkpoint_dir,
        config_path=cfg.get("dit_model", "acestep-v15-turbo"),
        device=device,
        use_flash_attention=False,   # not available on Metal
        compile_model=False,         # ACE-Step disables compile on Apple Silicon anyway
        offload_to_cpu=False,
        offload_dit_to_cpu=False,
        quantization=None,
        prefer_source="local",
    )
    if not enable_generate:
        print(f"[runner] DiT init failed: {init_status}", file=sys.stderr)
        return 1

    # The planner LM improves song structure but isn't required; on a memory-tight
    # machine it's the first thing worth dropping.
    llm = None
    if cfg.get("use_lm", True):
        try:
            llm = LLMHandler()
            _, lm_ok = llm.initialize(
                checkpoint_dir=checkpoint_dir,
                lm_model_path=cfg.get("lm_model", "acestep-5Hz-lm-1.7B"),
                backend=cfg.get("backend", "mlx"),
                device=device,
                offload_to_cpu=False,
                dtype=None,
            )
            if not lm_ok:
                llm = None
        except Exception as exc:  # noqa: BLE001
            print(f"[runner] planner LM unavailable, continuing without it: {exc}", file=sys.stderr)
            llm = None

    params = GenerationParams(
        task_type="text2music",
        caption=cfg["prompt"],
        lyrics="" if cfg.get("instrumental") else cfg.get("lyrics", ""),
        instrumental=bool(cfg.get("instrumental")),
        duration=float(cfg.get("duration", 180.0)),
        bpm=cfg.get("bpm") or None,
        keyscale=cfg.get("keyscale", "") or "",
        inference_steps=int(cfg.get("steps", 8)),
        guidance_scale=float(cfg.get("guidance", 7.0)),
        seed=int(cfg.get("seed", -1)),
    )

    generate_music(dit, llm, params, GenerationConfig(), save_dir=save_dir)

    produced = [p for ext in ("*.wav", "*.flac", "*.mp3") for p in Path(save_dir).rglob(ext)]
    if not produced:
        print("[runner] no audio produced", file=sys.stderr)
        return 1

    newest = max(produced, key=lambda p: p.stat().st_mtime)
    print(f"OUTPUT::{newest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
