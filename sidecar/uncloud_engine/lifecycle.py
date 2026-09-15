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
    flux2_profile: bool = False
    video_pipeline: bool = False
    browser: bool = False
    wake_lock: bool = False

    def to_dict(self) -> dict:
        return {
            "text_model": self.text_model,
            "image_pipeline": self.image_pipeline,
            "mflux_model": self.mflux_model,
            "flux2_profile": self.flux2_profile,
            "video_pipeline": self.video_pipeline,
            "browser": self.browser,
            "wake_lock": self.wake_lock,
            "anything": any(vars(self).values()),
        }


def resident() -> dict:
    """What is currently holding memory, for the UI to show before stopping."""
    out: dict = {"text_model": None, "image_pipeline": None,
                 "mflux_model": None, "flux2_profile": None,
                 "video_pipeline": None}
    try:
        from .engines import engine_manager

        if engine_manager.active:
            out["text_model"] = engine_manager.active.model_path
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import speech

        speech.stop()
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
        from .flux2_profile import flux2_profile_runtime

        out["flux2_profile"] = flux2_profile_runtime.loaded
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
        from .flux2_profile import flux2_profile_runtime

        if flux2_profile_runtime.holding:
            flux2_profile_runtime.unload()
            freed.flux2_profile = True
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


def watch_parent() -> None:
    """Shut down when the app that launched this engine is gone.

    The desktop app terminates the engine when it quits, but that only covers
    the exits where it gets to run code. A force quit, a crash, or `kill -9`
    leaves the engine alive with whatever models it had loaded — twenty
    gigabytes with no window left to release it from. The launcher passes its
    own pid; when that pid stops existing, so does this process.

    Started by hand there is no pid to shadow and this does nothing, so running
    the engine standalone still works.
    """
    import os
    import threading
    import time

    raw = os.environ.get("UNCLOUD_PARENT_PID", "")
    if not raw.isdigit():
        return
    parent = int(raw)

    def alive() -> bool:
        try:
            import psutil
        except ImportError:
            try:
                os.kill(parent, 0)
            except ProcessLookupError:
                return False
            except OSError:
                pass  # exists but is not ours to signal
            return True

        try:
            # A zombie has already exited — its table entry just lingers until
            # something reaps it, and pid_exists() cannot tell the two apart.
            return psutil.Process(parent).status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False
        except psutil.Error:
            return True

    def poll() -> None:
        while alive():
            time.sleep(2.0)
        stop_all_blocking()
        _end_process_group()

    threading.Thread(target=poll, daemon=True, name="parent-watchdog").start()


def _end_process_group() -> None:
    """Take down anything we spawned that stop_all did not know about.

    The engine is its own process group leader, so one signal reaches every
    model server and render worker beneath it. SIGTERM is ignored here first —
    the signal lands on this process too, and the handler that would catch it
    has already done its work.
    """
    import os
    import signal
    import time

    try:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        os.killpg(os.getpgid(0), signal.SIGTERM)
        time.sleep(0.5)
    except (AttributeError, OSError, ValueError):
        pass  # not POSIX, or no group of our own — exiting is still correct
    os._exit(0)


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
