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

from pathlib import Path


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


# Per-family architecture. "spatial" is the effective stride from pixels to
# tokens, which for Wan is its 16x VAE times a 2x2 patch, landing on the same
# 32 as LTX. The temporal figure does not match: Wan keeps twice as many latent
# frames per second of clip, so the same two seconds is twice the tokens and,
# attention being quadratic, four times the sequence cost. Smaller weights, not
# a smaller sequence.
_ARCH = {
    "ltx": {"spatial": 32, "temporal": 8, "layers": 28, "dim": 2048, "heads": 32},
    "wan": {"spatial": 32, "temporal": 4, "layers": 30, "dim": 3072, "heads": 24},
}
_LTX = _ARCH["ltx"]


def resident_weights_gb(model_path: str) -> float:
    """What a video pipeline actually holds while it denoises.

    Not the folder size. LTX ships an 18GB fp32 text encoder that is loaded as
    bfloat16 — halving it — and then released before denoising begins, so it
    contributes nothing to the peak. Using the directory size instead estimated
    24GB for a clip that measured 6.5GB, and refused jobs that run comfortably.
    """
    import json

    root = Path(model_path)
    if not root.is_dir():
        return 6.0

    # A GGUF component stays packed in memory, so the file size on disk is what
    # it costs. The encoder is excluded: it is dropped before denoising, and
    # counting it is what previously refused clips that run comfortably.
    marker = root / "uncloud-video.json"
    if marker.is_file():
        try:
            declared = json.loads(marker.read_text())
        except (OSError, ValueError):
            declared = {}
        transformer = declared.get("transformer_gguf")
        if transformer and (root / transformer).is_file():
            total = (root / transformer).stat().st_size / 1e9
            vae = root / "vae"
            if vae.is_dir():
                size = sum(f.stat().st_size for f in vae.rglob("*.safetensors"))
                try:
                    dtype = json.loads((vae / "config.json").read_text()).get("torch_dtype")
                except (OSError, ValueError):
                    dtype = None
                total += (size / 2 if str(dtype) in ("float32", "fp32") else size) / 1e9
            return round(total + 0.5, 1)

    total = 0.0
    for component in ("transformer", "vae"):
        folder = root / component
        if not folder.is_dir():
            continue
        size = sum(f.stat().st_size for f in folder.rglob("*.safetensors"))
        # fp32 on disk becomes bfloat16 in memory.
        try:
            dtype = json.loads((folder / "config.json").read_text()).get("torch_dtype")
        except (OSError, ValueError):
            dtype = None
        if str(dtype) in ("float32", "fp32"):
            size /= 2
        total += size / 1e9
    # A little headroom for the scheduler, latents and decode buffers.
    return round(total + 0.5, 1) if total else 6.0


# What a VAE decode costs, per megapixel of output frame. Measured twice on
# this stack and it came out the same both times: 9.6 GB/Mpx decoding Wan video
# at bfloat16, 9.8 GB/Mpx decoding a FLUX.2 image. The decode expands a latent
# through wide convolutions at full resolution, and that dominates everything
# else in both cases.
DECODE_GB_PER_MPX = 9.6

# The phases add rather than replace each other. Freeing the transformer before
# the decode returns it to MPS, which keeps the pages rather than handing them
# back, so the driver's high-water — the number that meets the ceiling — tracks
# denoise plus decode, not the larger of the two. Two end-to-end runs of the
# same job, Wan at 25 frames and 1280x704: 17.1 GB of parts measured 19.31, and
# 9.0 GB of parts measured 10.07. Ratios of 1.13 and 1.12.
#
# Taking the larger of the phases instead gave 1.91 and 1.44 for the same two
# runs, which is a way of saying that model was wrong and the constant was
# absorbing the error.
_ALLOCATOR_OVERHEAD = 1.12

# The decode is tiled, so its cost is set by one tile rather than the frame.
_DECODE_TILE_PX = 256 * 256


def estimate_video_gb(frames: int, width: int, height: int,
                      weights_gb: float = 6.0, family: str = "ltx",
                      vae_gb: float = 1.4) -> dict:
    """Roughly what a clip will need at its worst moment, and where it goes.

    A generation has two peaks, not one, and they do not overlap: denoising
    holds the transformer and the sequence, then the transformer is released
    and the decode holds the VAE and a full-resolution frame. The larger of the
    two is what has to fit.

    Guessing that the transformer is the expensive half is wrong. At 1280x704
    denoising measured 6.5 GB of parts against 10.1 GB for the decode — the
    decode is the wall, and it is why quantising the weights does not buy a
    machine into range on its own.
    """
    cfg = _ARCH.get(family, _LTX)
    latent_frames = max(1, (frames - 1) // cfg["temporal"] + 1)
    tokens = latent_frames * (height // cfg["spatial"]) * (width // cfg["spatial"])

    hidden = tokens * cfg["dim"] * 2 * cfg["layers"] / 1e9
    # Memory-efficient attention does not materialise the full matrix; assume it
    # is available but leave headroom in case it is not.
    attention = (tokens * tokens * cfg["heads"] * 2 / 1e9) * 0.25
    sequence = hidden + attention

    denoise = weights_gb + sequence
    # Both families decode a tile at a time, so the frame's size sets how long
    # it takes and not how much it costs.
    decode = vae_gb + DECODE_GB_PER_MPX * (_DECODE_TILE_PX / 1e6)
    total = (denoise + decode) * _ALLOCATOR_OVERHEAD

    return {
        "tokens": tokens,
        "weights_gb": round(weights_gb, 1),
        "sequence_gb": round(sequence, 1),
        "denoise_gb": round(denoise * _ALLOCATOR_OVERHEAD, 1),
        "decode_gb": round(decode * _ALLOCATOR_OVERHEAD, 1),
        "total_gb": round(total, 1),
    }


# What the Video tab offers, smallest first. Kept here rather than in the view
# because whether a machine can run video at all is a question about the
# machine, and the answer has to be the same in both places.
VIDEO_FRAMES = (25, 49, 97, 145, 193, 241)
VIDEO_SIZES = ((448, 256), (512, 320), (640, 384), (704, 480), (960, 544),
               (1216, 704), (1280, 704))

# Below this many output pixels a family stops producing anything usable, as
# distinct from running out of memory. Zero means it degrades gracefully.
_USABLE_PIXELS = {"wan": 1216 * 704, "ltx": 0}


def video_capability(weights_gb: float = 6.0, family: str = "ltx") -> dict:
    """How far this machine gets with video, if anywhere.

    A machine that cannot hold even the shortest draft clip should not be shown
    a Video tab. Every job there fails the same way, and a hardware limit hit
    six times reads as a broken feature rather than a machine that is too
    small — which is worse than not offering it, for anyone who paid.

    Returns the largest length and size that fit, so the answer can be "2s at
    512x320" rather than a bare yes or no.
    """
    budget = memory_budget()["budget_gb"]
    if not budget:
        return {"runnable": True, "budget_gb": 0.0, "reason": "unknown"}

    # Fitting is not the same as being worth running. Wan collapses into
    # coloured smear below its native size — verified at 1280x704 (good) and
    # 448x256 (unusable, same prompt, seed and steps). Sizes in between were
    # not swept, so the floor is set at the one that is known good rather than
    # at a guess about where it breaks.
    usable = _USABLE_PIXELS.get(family, 0)

    def fits(frames: int, width: int, height: int) -> bool:
        return estimate_video_gb(frames, width, height, weights_gb, family)["total_gb"] <= budget

    smallest_frames, (smallest_w, smallest_h) = VIDEO_FRAMES[0], VIDEO_SIZES[0]
    if not fits(smallest_frames, smallest_w, smallest_h):
        return {
            "runnable": False,
            "budget_gb": round(budget, 1),
            "weights_gb": round(weights_gb, 1),
            "reason": "The shortest, smallest clip this app offers needs more "
                      "memory than this machine can give a single job.",
        }

    # Length and size trade against each other — attention cost is quadratic in
    # tokens, and tokens are frames times area. Reporting the longest clip and
    # the largest frame independently would promise the combination of the two,
    # which is exactly the job that does not fit. Each is reported against the
    # other held at its smallest.
    longest = max(f for f in VIDEO_FRAMES if fits(f, smallest_w, smallest_h))
    largest = max((s for s in VIDEO_SIZES if fits(smallest_frames, *s)),
                  key=lambda s: s[0] * s[1])
    out = {
        "runnable": True,
        "budget_gb": round(budget, 1),
        "weights_gb": round(weights_gb, 1),
        "longest_frames_at_min_size": longest,
        "largest_size_at_min_frames": list(largest),
    }
    if usable and largest[0] * largest[1] < usable:
        out["runnable"] = False
        out["reason"] = (
            "This machine can hold a clip, but only at sizes below the one "
            "this model needs. Run it smaller and it does not degrade — it "
            "returns moving colour with no subject in it."
        )
    return out
