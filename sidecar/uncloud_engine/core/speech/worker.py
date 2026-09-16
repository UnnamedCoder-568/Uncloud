"""The host side of a speech worker: start it, give it work, stop it.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Standard library only.

A worker is started lazily, reused while it is in use, and stopped after it
has been idle a while — a loaded speech model holds gigabytes, and a person
who asked for one sentence an hour ago should not still be paying for it.
One request at a time per worker: the models are not re-entrant, and two
long reads racing on one GPU are slower than the same two in turn.
"""

from __future__ import annotations

import collections
import itertools
import json
import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

RUNNER = Path(__file__).resolve().with_name("runner.py")

#: Seconds a worker may sit unused before its model is released.
IDLE_SECONDS = 600
#: How long a worker may take to start before it is declared broken.
START_SECONDS = 120


class WorkerError(RuntimeError):
    """The worker refused the request or died; the message says why."""


class Worker:
    def __init__(self, python: Path | str, *, env: dict[str, str] | None = None,
                 idle_seconds: float = IDLE_SECONDS) -> None:
        self.python = str(python)
        self.env = env or {}
        self.idle_seconds = idle_seconds
        self._process: subprocess.Popen | None = None
        self._lines: queue.Queue = queue.Queue()
        self._stderr: collections.deque[str] = collections.deque(maxlen=60)
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._timer: threading.Timer | None = None

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def tail(self) -> str:
        """The last lines the worker wrote to stderr, for an error message."""
        return "\n".join(self._stderr)

    def _start(self) -> None:
        env = dict(os.environ)
        env.update(self.env)
        env["PYTHONUNBUFFERED"] = "1"
        self._lines = queue.Queue()
        self._stderr.clear()
        self._process = subprocess.Popen(
            [self.python, "-u", str(RUNNER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env, bufsize=1,
        )
        process = self._process

        def read_stdout() -> None:
            for line in process.stdout or []:
                self._lines.put(line)
            self._lines.put(None)

        def read_stderr() -> None:
            # Drained continuously: a full stderr pipe blocks the worker, and a
            # progress bar fills one in seconds.
            for line in process.stderr or []:
                self._stderr.append(line.rstrip())

        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=read_stderr, daemon=True).start()
        first = self._next(START_SECONDS)
        if not first.get("ready"):
            self.stop()
            raise WorkerError(f"The speech worker did not start.\n{self.tail()}")

    def _next(self, timeout: float | None) -> dict:
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                self.stop()
                raise WorkerError("The speech worker stopped responding.") from None
            if line is None:
                code = self._process.poll() if self._process else None
                raise WorkerError(
                    f"The speech worker exited ({code}).\n{self.tail()}".rstrip())
            try:
                return json.loads(line)
            except ValueError:
                continue  # not protocol; the runner guards stdout, but be tolerant

    def request(self, message: dict, *, on_progress: Callable[[int, int], None] | None = None,
                timeout: float | None = None) -> dict:
        """Send one request and wait for its answer. Raises WorkerError."""
        with self._lock:
            if self._timer:
                self._timer.cancel()
            if not self.alive:
                self._start()
            ident = str(next(self._ids))
            assert self._process and self._process.stdin
            try:
                self._process.stdin.write(json.dumps({**message, "id": ident}) + "\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self.stop()
                raise WorkerError(f"The speech worker is not running.\n{self.tail()}") from exc
            try:
                while True:
                    reply = self._next(timeout)
                    if reply.get("id") != ident:
                        continue
                    if "progress" in reply:
                        if on_progress:
                            done, total = reply["progress"]
                            on_progress(int(done), int(total))
                        continue
                    if reply.get("error"):
                        raise WorkerError(str(reply["error"]))
                    return reply
            finally:
                self._arm_idle()

    def _arm_idle(self) -> None:
        if self.idle_seconds <= 0:
            return
        self._timer = threading.Timer(self.idle_seconds, self.stop)
        self._timer.daemon = True
        self._timer.start()

    def stop(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None
        process, self._process = self._process, None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
            process.terminate()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()


class Pool:
    """Workers keyed by interpreter, so engines sharing one share a process."""

    def __init__(self) -> None:
        self._workers: dict[str, Worker] = {}
        self._lock = threading.Lock()

    def get(self, python: Path | str, *, env: dict[str, str] | None = None) -> Worker:
        key = str(python)
        with self._lock:
            worker = self._workers.get(key)
            if worker is None:
                worker = self._workers[key] = Worker(python, env=env)
            return worker

    def stop_all(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
        for worker in workers:
            worker.stop()

    def resident_count(self) -> int:
        """Number of live voice worker processes, without changing them."""
        with self._lock:
            workers = list(self._workers.values())
        return sum(
            1 for worker in workers
            if worker._process is not None and worker._process.poll() is None  # noqa: SLF001
        )
