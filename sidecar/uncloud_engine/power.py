"""Opt-in system sleep protection for the app session and overlapping jobs."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import threading
from pathlib import Path

_lock = threading.Lock()
_holders = 0
_proc: subprocess.Popen | None = None
_session_lock: keep_awake | None = None
_epoch = 0
_win_stop = threading.Event()
_win_thread: threading.Thread | None = None
_win_active = False

# Windows: keep the system (and display) out of idle sleep.
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


def _begin() -> bool:
    global _proc
    if sys.platform == "darwin":
        # -i idle sleep, -m disk, -s system. Not -d: no reason to force the
        # display on, only to stop the machine suspending the work.
        binary = Path("/usr/bin/caffeinate")
        _proc = subprocess.Popen(
            [str(binary), "-ims", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return _proc.poll() is None
    elif sys.platform.startswith("linux"):
        try:
            _proc = subprocess.Popen(
                ["systemd-inhibit", "--what=idle:sleep",
                 "--why=Uncloud is running a job", "sleep", "infinity"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return _proc.poll() is None
        except FileNotFoundError:
            _proc = None
            return False
    elif sys.platform == "win32":
        # Windows assertions are thread-owned. FastAPI calls may run on
        # different workers, so acquire and release on one dedicated thread.
        global _win_thread
        ready = threading.Event()
        _win_stop.clear()

        def hold():
            global _win_active
            import ctypes

            try:
                _win_active = bool(ctypes.windll.kernel32.SetThreadExecutionState(
                    _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED))
                ready.set()
                _win_stop.wait()
            finally:
                ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
                _win_active = False
                ready.set()

        _win_thread = threading.Thread(target=hold, daemon=True)
        _win_thread.start()
        ready.wait(timeout=2)
        return _win_active
    return False


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
        _win_stop.set()
        if _win_thread:
            _win_thread.join(timeout=2)


class keep_awake:
    """Context manager held for the length of a job.

    Does nothing unless the setting is on, so callers can wrap unconditionally.
    """

    def __init__(self, reason: str = "") -> None:
        self.reason = reason
        self._active = False
        self._epoch = _epoch

    def __enter__(self) -> keep_awake:
        global _holders
        from .config import settings

        if not settings.keep_awake:
            return self
        with _lock:
            if not is_held():
                try:
                    if not _begin():
                        return self
                except Exception:  # noqa: BLE001 - never fail a job over this
                    return self
            _holders += 1
            self._epoch = _epoch
            self._active = True
        return self

    def __exit__(self, *exc) -> None:
        global _holders
        if not self._active or self._epoch != _epoch:
            return
        self._active = False
        with _lock:
            _holders -= 1
            if _holders <= 0:
                _holders = 0
                with contextlib.suppress(Exception):
                    _end()


def is_held() -> bool:
    return _holders > 0 and (_win_active if sys.platform == "win32" else
                             _proc is not None and _proc.poll() is None)


def set_session_awake(enabled: bool) -> bool:
    """Hold a wake assertion for the entire app session while enabled."""
    global _session_lock, _holders, _epoch
    if not enabled:
        with _lock:
            _end()
            _epoch += 1
            _holders = 0
            _session_lock = None
        return is_held()
    if _session_lock is None:
        lock = keep_awake("app session")
        lock.__enter__()
        if lock._active:
            _session_lock = lock
    return is_held()
