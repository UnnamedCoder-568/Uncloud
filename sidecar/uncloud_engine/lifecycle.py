"""Release everything the engine is holding.

Models are the expensive thing here: a chat server can sit on twenty gigabytes,
and it is spawned as a child process, so nothing reclaims it just because the
window closed. This is the single place that lets go of all of it — used both by
the stop button and by the shutdown path, so the two can never drift.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class Released:
    text_model: bool = False
    image_pipeline: bool = False
    mflux_model: bool = False
    video_pipeline: bool = False
    browser: bool = False
    wake_lock: bool = False

    def to_dict(self) -> dict:
        return {
            "text_model": self.text_model,
            "image_pipeline": self.image_pipeline,
            "mflux_model": self.mflux_model,
            "video_pipeline": self.video_pipeline,
            "browser": self.browser,
            "wake_lock": self.wake_lock,
            "anything": any(vars(self).values()),
        }


def resident() -> dict:
    """What is currently holding memory, for the UI to show before stopping."""
    out: dict = {"text_model": None, "image_pipeline": None,
                 "mflux_model": None, "video_pipeline": None}
    try:
        from .engines import engine_manager

        if engine_manager.active:
            out["text_model"] = engine_manager.active.model_path
    except Exception:  # noqa: BLE001
        pass
    try:
        from .image_engine import image_engine

        out["image_pipeline"] = getattr(image_engine, "_pipe_path", None)
    except Exception:  # noqa: BLE001
        pass
    try:
        from .mflux_runtime import mflux_runtime

        out["mflux_model"] = mflux_runtime.loaded
    except Exception:  # noqa: BLE001
        pass
    try:
        from .video_engine import video_engine

        out["video_pipeline"] = getattr(video_engine, "_loaded_path", None)
    except Exception:  # noqa: BLE001
        pass
    out["anything"] = any(v for v in out.values())
    return out


async def stop_all(*, close_browser: bool = True) -> Released:
    """Unload every model and stop every child process.

    Deliberately tolerant: this runs during shutdown, when parts of the engine
    may already be gone, and one failure must not prevent the rest from being
    released.
    """
    freed = Released()

    try:
        from .engines import engine_manager

        if engine_manager.active:
            engine_manager.stop()
            freed.text_model = True
    except Exception:  # noqa: BLE001
        pass

    try:
        from .image_engine import image_engine

        if getattr(image_engine, "_pipe", None) is not None:
            image_engine.unload()
            freed.image_pipeline = True
    except Exception:  # noqa: BLE001
        pass

    try:
        from .mflux_runtime import mflux_runtime

        if mflux_runtime.loaded:
            mflux_runtime.unload()
            freed.mflux_model = True
    except Exception:  # noqa: BLE001
        pass

    try:
        from .video_engine import video_engine

        if getattr(video_engine, "_pipe", None) is not None:
            video_engine.unload()
            freed.video_pipeline = True
    except Exception:  # noqa: BLE001
        pass

    if close_browser:
        try:
            from .agent import browser

            # Only claim this if something was actually open; shutdown() is a
            # no-op otherwise, and reporting a phantom release would make the
            # stop button look like it did work it did not.
            was_open = browser._browser is not None or browser._page is not None  # noqa: SLF001
            await browser.shutdown()
            freed.browser = was_open
        except Exception:  # noqa: BLE001
            pass

    try:
        from . import power

        if power.is_held():
            power._end()          # noqa: SLF001 - the module is ours
            power._holders = 0    # noqa: SLF001
            freed.wake_lock = True
    except Exception:  # noqa: BLE001
        pass

    # Anything still running that we spawned — a stray mflux render, an
    # acestep worker — belongs to this process group and goes with it.
    return freed


def stop_all_blocking() -> None:
    """Signal-handler-safe wrapper: no event loop is guaranteed here."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        loop.create_task(stop_all())
    else:
        asyncio.run(stop_all())
