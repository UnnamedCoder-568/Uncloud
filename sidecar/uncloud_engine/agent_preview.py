"""Transient, bounded observation of a running agent, never desktop control."""
from __future__ import annotations

import asyncio
import base64
import io
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PreviewSession:
    source: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_frame: float = 0.0


async def capture_frame(session: PreviewSession) -> dict:
    # One frame at a time; callers cannot build an unbounded capture queue.
    if session.lock.locked() or time.monotonic() - session.last_frame < 1.0:
        raise ValueError("Preview refresh is limited to one frame per second")
    async with session.lock:
        session.last_frame = time.monotonic()
        raw = await asyncio.wait_for(_capture(session.source), timeout=8)
        from PIL import Image

        def encode():
            with Image.open(io.BytesIO(raw)) as image:
                image.thumbnail((1200, 750))
                out = io.BytesIO()
                image.convert("RGB").save(out, format="JPEG", quality=70)
                return base64.b64encode(out.getvalue()).decode("ascii")

        return {"image": await asyncio.to_thread(encode), "captured_at": time.time(),
                "source": session.source}


async def _capture(source: str) -> bytes:
    if source == "browser":
        from .agent import browser
        page = browser._page
        if page is None or page.is_closed():
            raise RuntimeError("Waiting for Chisel to open its browser")
        return await page.screenshot(type="png", timeout=6000)
    if source != "desktop":
        raise ValueError("Unknown preview source")
    if sys.platform != "darwin":
        def shot():
            import pyautogui
            out = io.BytesIO()
            pyautogui.screenshot().save(out, format="PNG")
            return out.getvalue()
        return await asyncio.to_thread(shot)
    # OS permission remains authoritative. The temporary image is removed even
    # when capture fails or the requesting task is cancelled.
    with tempfile.TemporaryDirectory(prefix="uncloud-preview-") as directory:
        target = Path(directory) / "frame.png"
        proc = await asyncio.create_subprocess_exec(
            "screencapture", "-x", str(target),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await proc.wait()
            if proc.returncode or not target.exists():
                raise RuntimeError(
                    "Allow Screen Recording in macOS Privacy & Security to preview this device"
                )
            return target.read_bytes()
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
