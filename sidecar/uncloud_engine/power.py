"""Keep the machine awake while long jobs run.

A 45-minute narration or a multi-minute diffusion run will be suspended when
the display sleeps, so you come back to a stalled job rather than a finished
one. This holds a wake lock for the duration and releases it afterwards.

Reference-counted: several jobs can overlap, and the lock lifts only when the
last one finishes. Opt-in — off unless the user turns it on in Settings.
"""

from __future__ import annotations

import subprocess
import sys
import threading

_lock = threading.Lock()
_holders = 0
_proc: subprocess.Popen | None = None

# Windows: keep the system (and display) out of idle sleep.
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


def _begin() -> None:
    global _proc
    if sys.platform == "darwin":
        # -i idle sleep, -m disk, -s system. Not -d: no reason to force the
        # display on, only to stop the machine suspending the work.
        _proc = subprocess.Popen(
            ["caffeinate", "-ims"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    elif sys.platform.startswith("linux"):
        try:
            _proc = subprocess.Popen(
                ["systemd-inhibit", "--what=idle:sleep",
                 "--why=Uncloud is running a job", "sleep", "infinity"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            _proc = None          # no systemd; nothing to hold, carry on
    elif sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.SetThreadExecutionState(
            _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
        )


def _end() -> None:
    global _proc
    if _proc is not None:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _proc.kill()
        _proc = None
    elif sys.platform == "win32":
        import ctypes

        ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)


class keep_awake:
    """Context manager held for the length of a job.

    Does nothing unless the setting is on, so callers can wrap unconditionally.
    """

    def __init__(self, reason: str = "") -> None:
        self.reason = reason
        self._active = False

    def __enter__(self) -> "keep_awake":
        global _holders
        from .config import settings

        if not settings.keep_awake:
            return self
        with _lock:
            if _holders == 0:
                try:
                    _begin()
                except Exception:  # noqa: BLE001 - never fail a job over this
                    return self
            _holders += 1
            self._active = True
        return self

    def __exit__(self, *exc) -> None:
        global _holders
        if not self._active:
            return
        with _lock:
            _holders -= 1
            if _holders <= 0:
                _holders = 0
                try:
                    _end()
                except Exception:  # noqa: BLE001
                    pass


def is_held() -> bool:
    return _holders > 0
