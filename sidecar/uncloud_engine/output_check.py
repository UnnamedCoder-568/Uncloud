"""Reject degenerate output instead of reporting it as a finished picture.

Diffusion fails quietly. A NaN in the latents, a bad quantisation, a VAE that
never got its weights, an out-of-memory that silently produced nothing useful —
all of these end with a file on disk and a job that thinks it succeeded. The
result is a flat grey rectangle presented with full confidence, which is worse
than an error, because the error at least tells you to try something else.

These checks are deliberately conservative. A legitimately minimal image — a
near-black night scene, a white product on white — must not be rejected, so the
thresholds sit well below anything a real generation produces.
"""

from __future__ import annotations

from pathlib import Path


class DegenerateOutput(RuntimeError):
    """Raised when a generation finished but produced nothing usable."""


# Thresholds are set to catch a flat fill and nothing else. A false positive
# here — rejecting a legitimately dark or minimal picture — is worse than
# letting a bad one through, because it throws away real work and teaches the
# user to distrust the check. A genuine render, however plain, clears these by
# a wide margin; a uniform slab scores at or near zero on all three.
MIN_STDDEV = 0.6
MIN_DISTINCT = 3
MAX_SINGLE_COLOUR_SHARE = 0.997


def describe(path: str | Path) -> dict:
    """Cheap statistics used to decide whether an image is real output."""
    from PIL import Image, ImageStat

    with Image.open(path) as im:
        im = im.convert("RGB")
        # Downscale first: this runs on every generation and full-resolution
        # statistics would cost more than they are worth.
        small = im.resize((160, 160))
        stat = ImageStat.Stat(small)
        stddev = sum(stat.stddev) / len(stat.stddev)
        quant = small.quantize(colors=64, method=Image.Quantize.FASTOCTREE)
        hist = quant.histogram()
        total = sum(hist) or 1
        distinct = sum(1 for c in hist if c > total * 0.001)
        top_share = max(hist) / total
        return {
            "stddev": round(stddev, 2),
            "distinct": distinct,
            "top_share": round(top_share, 4),
            "size": im.size,
        }


def verify_image(path: str | Path, *, what: str = "image") -> dict:
    """Raise DegenerateOutput if this file is not a real picture."""
    p = Path(path)
    if not p.exists():
        raise DegenerateOutput(f"The {what} pipeline reported success but wrote no file.")
    if p.stat().st_size < 1024:
        raise DegenerateOutput(
            f"The {what} file is {p.stat().st_size} bytes — nothing was rendered."
        )
    try:
        s = describe(p)
    except Exception as exc:  # noqa: BLE001 - unreadable is itself a failure
        raise DegenerateOutput(f"The {what} file could not be read back: {exc}") from exc

    if (s["stddev"] < MIN_STDDEV or s["distinct"] < MIN_DISTINCT
            or s["top_share"] > MAX_SINGLE_COLOUR_SHARE):
        raise DegenerateOutput(
            f"The model produced a blank {what} (variation {s['stddev']:.1f}, "
            f"{s['distinct']} distinct tones, {s['top_share']*100:.1f}% one colour). "
            "This usually means the pipeline ran out of memory, or a component — "
            "commonly the VAE or text encoder — did not load. The run is being "
            "reported as failed rather than handed to you as a picture."
        )
    return s


def verify_video(path: str | Path, min_frames: int = 4) -> dict:
    """Same idea for video: enough frames, and not a uniform slab."""
    import json
    import subprocess

    p = Path(path)
    if not p.exists() or p.stat().st_size < 4096:
        raise DegenerateOutput("The video pipeline reported success but wrote no usable file.")
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-count_packets", "-show_entries", "stream=nb_read_packets,width,height",
             "-of", "json", str(p)],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(out.stdout or "{}")
        st = (data.get("streams") or [{}])[0]
        frames = int(st.get("nb_read_packets", 0) or 0)
    except Exception as exc:  # noqa: BLE001
        raise DegenerateOutput(f"The video could not be read back: {exc}") from exc

    if frames < min_frames:
        raise DegenerateOutput(
            f"The video has only {frames} frame(s) — generation did not complete."
        )
    return {"frames": frames, "size": (st.get("width"), st.get("height"))}


def summarise_traceback(text: str, *, limit: int = 400) -> str:
    """Pull the part of a Python traceback a person can act on.

    A subprocess that dies prints twenty frames of library internals and then,
    on the last line, the thing that actually went wrong. Showing the whole wall
    buries the sentence that matters — so lead with it, and keep a little
    context behind it.
    """
    lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return "The process failed without printing anything."

    # The final `SomeError: message` line is the useful one.
    for ln in reversed(lines):
        stripped = ln.strip()
        if stripped.startswith(("File \"", "^", "Traceback", "During handling", "The above")):
            continue
        if ":" in stripped and stripped.split(":", 1)[0].replace(".", "").isidentifier():
            return stripped[:limit]
        if stripped and not stripped.startswith(("  ", "\t")):
            return stripped[:limit]
    return lines[-1][:limit]
