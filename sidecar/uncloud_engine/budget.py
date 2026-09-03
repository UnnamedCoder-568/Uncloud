"""What this machine can give a generation, and what one will ask for.

Running out of memory is not a uniform failure. macOS refuses the allocation
and the job dies with a message. A Linux box with a discrete GPU can lock up
hard enough to need a power cycle, and a machine paging 20GB to a slow disk is
unusable for as long as it takes. None of that is worth discovering after
pressing Generate, so the cost is estimated up front and the choice is the
user's rather than a surprise.

Estimates are deliberately rough. Being within a couple of gigabytes is enough
to tell "this fits" from "this will take the machine down".
"""

from __future__ import annotations


def memory_budget() -> dict:
    """Total and usable memory, and the accelerator's own ceiling if it has one."""
    import platform

    total = available = 0.0
    try:
        import psutil

        vm = psutil.virtual_memory()
        total, available = vm.total / 1e9, vm.available / 1e9
    except Exception:  # noqa: BLE001 - psutil is optional
        pass

    device, budget, unified = "cpu", available, False
    try:
        import torch

        if torch.backends.mps.is_available():
            device, unified = "mps", True
            # Apple Silicon shares one pool, and Metal will not hand out all of
            # it. This is the number that actually caps a generation.
            try:
                budget = torch.mps.recommended_max_memory() / 1e9
            except Exception:  # noqa: BLE001 - older torch
                budget = total * 0.75
        elif torch.cuda.is_available():
            device = "cuda"
            props = torch.cuda.get_device_properties(0)
            budget = props.total_memory / 1e9
    except Exception:  # noqa: BLE001 - torch may be missing
        pass

    return {
        "total_gb": round(total, 1),
        "available_gb": round(available, 1),
        "device": device,
        "budget_gb": round(budget, 1),
        "unified": unified,
        "platform": platform.system(),
    }


# LTX 2B: 32x spatial and 8x temporal compression, 28 layers, 2048 hidden.
_LTX = {"spatial": 32, "temporal": 8, "layers": 28, "dim": 2048, "heads": 32}


def estimate_video_gb(frames: int, width: int, height: int,
                      weights_gb: float = 6.0) -> dict:
    """Roughly what a clip will need, and where it goes.

    Weights dominate at ordinary lengths: a four-second clip needs about half a
    gigabyte of sequence against six of weights, which is why "make it shorter"
    is usually the wrong advice for a job that ran out of memory.
    """
    cfg = _LTX
    latent_frames = max(1, (frames - 1) // cfg["temporal"] + 1)
    tokens = latent_frames * (height // cfg["spatial"]) * (width // cfg["spatial"])

    hidden = tokens * cfg["dim"] * 2 * cfg["layers"] / 1e9
    # Memory-efficient attention does not materialise the full matrix; assume it
    # is available but leave headroom in case it is not.
    attention = (tokens * tokens * cfg["heads"] * 2 / 1e9) * 0.25
    sequence = hidden + attention

    return {
        "tokens": tokens,
        "weights_gb": round(weights_gb, 1),
        "sequence_gb": round(sequence, 1),
        "total_gb": round(weights_gb + sequence, 1),
    }
