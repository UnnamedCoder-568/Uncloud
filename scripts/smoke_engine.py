"""Exercise first-run setup and the engine handshake using packaged files."""

from __future__ import annotations

import argparse
import collections
import json
import os
import queue
import shutil
import signal
import subprocess
import threading
import time
import urllib.request
from pathlib import Path


def stop_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uv", required=True, type=Path)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()

    uv = args.uv.resolve()
    source = args.engine.resolve()
    if not uv.is_file():
        raise SystemExit(f"bundled uv is missing: {uv}")
    for relative in ("pyproject.toml", "uv.lock", "uncloud_engine/main.py"):
        if not (source / relative).is_file():
            raise SystemExit(f"packaged engine is missing {relative}")

    if args.work_dir.exists():
        shutil.rmtree(args.work_dir)
    engine = args.work_dir / "engine"
    state = args.work_dir / "state"
    cache = args.work_dir / "cache"
    python_dir = args.work_dir / "python"
    shutil.copytree(source, engine)
    state.mkdir(parents=True)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(state),
            "USERPROFILE": str(state),
            "UNCLOUD_PARENT_PID": str(os.getpid()),
            "UNCLOUD_UV": str(uv),
            "UV_CACHE_DIR": str(cache),
            "UV_PYTHON_INSTALL_DIR": str(python_dir),
            "UV_PYTHON_DOWNLOADS": "automatic",
            "UV_NO_PROGRESS": "1",
        }
    )

    subprocess.run(
        [str(uv), "sync", "--locked", "--no-dev"],
        cwd=engine,
        env=env,
        check=True,
        timeout=5400,
    )

    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        [str(uv), "run", "--locked", "--no-dev", "python", "-m", "uncloud_engine.main"],
        cwd=engine,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=flags,
        start_new_session=os.name != "nt",
    )
    stderr_tail: collections.deque[str] = collections.deque(maxlen=40)
    first_line: queue.Queue[str] = queue.Queue(maxsize=1)

    def read_stdout() -> None:
        assert process.stdout is not None
        first_line.put(process.stdout.readline())
        for _ in process.stdout:
            pass

    def read_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            stderr_tail.append(line.rstrip())

    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=read_stderr, daemon=True).start()

    try:
        try:
            handshake_line = first_line.get(timeout=180)
        except queue.Empty as exc:
            raise RuntimeError("engine did not produce a handshake within 180 seconds") from exc
        if not handshake_line:
            raise RuntimeError("engine exited before producing a handshake")
        handshake = json.loads(handshake_line)
        port = int(handshake["port"])
        if not handshake.get("token"):
            raise RuntimeError("engine handshake did not contain an authentication token")

        deadline = time.monotonic() + 120
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
                    if response.status == 200:
                        if os.name == "nt":
                            request = urllib.request.Request(
                                f"http://127.0.0.1:{port}/api/readiness?names=chat",
                                headers={"Authorization": f"Bearer {handshake['token']}"},
                            )
                            with urllib.request.urlopen(request, timeout=40) as ready:
                                rows = json.load(ready)
                            if not rows or not all(row['ready'] for row in rows):
                                raise RuntimeError(f"Packaged chat runtime is not ready: {rows}")
                        print(f"Packaged engine became healthy on localhost port {port}.")
                        return
            except Exception as exc:  # noqa: BLE001 - retry until the deadline
                last_error = exc
                time.sleep(1)
        raise RuntimeError(f"engine health check timed out: {last_error}")
    except Exception as exc:
        tail = "\n".join(stderr_tail)
        raise SystemExit(f"engine smoke test failed: {exc}\n{tail}") from exc
    finally:
        stop_process_tree(process)


if __name__ == "__main__":
    main()
