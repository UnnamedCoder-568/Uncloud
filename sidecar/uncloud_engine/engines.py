from __future__ import annotations

import asyncio
import contextlib
import socket
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass, field

import httpx

from .context_profile import for_model
from .inference_profile import load as load_inference_profile
from .native_chat import server_path

LLAMA_SERVER_BIN = server_path()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class ActiveEngine:
    model_path: str
    engine: str  # gguf | mlx
    port: int
    process: subprocess.Popen
    adapter_path: str | None = None
    context_limit: int = 8192
    model_profile: object = None
    inference_profile: dict = field(default_factory=dict)
    logs: deque = field(default_factory=lambda: deque(maxlen=80), repr=False)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


class EngineManager:
    """Owns at most one running text-inference backend at a time.

    Both llama.cpp and mlx-lm expose an OpenAI-compatible /v1/chat/completions
    endpoint, so once a backend is up the rest of the app talks one dialect.
    """

    def __init__(self) -> None:
        self.active: ActiveEngine | None = None
        self._lock = asyncio.Lock()

    async def start(self, model_path: str, engine: str,
                    adapter_path: str | None = None) -> ActiveEngine:
        async with self._lock:
            if (self.active and self.active.model_path == model_path
                    and self.active.engine == engine
                    and self.active.adapter_path == adapter_path
                    and self.active.process.poll() is None):
                return self.active
            if self.active:
                self._stop_process(self.active)
                self.active = None

            port = _free_port()
            profile = for_model(model_path, engine)
            model_profile, inference_profile = load_inference_profile(model_path, engine)
            if engine == "gguf":
                proc = self._spawn_llama_cpp(model_path, port, profile["effective_limit"])
            elif engine == "mlx":
                proc = self._spawn_mlx(model_path, port, adapter_path)
            elif engine == "mlx-vlm":
                proc = self._spawn_mlx_vlm(model_path, port)
            else:
                raise ValueError(f"No text-inference launcher for engine: {engine}")

            active = ActiveEngine(model_path=model_path, engine=engine, port=port,
                                  process=proc, adapter_path=adapter_path,
                                  context_limit=profile["effective_limit"],
                                  model_profile=model_profile, inference_profile=inference_profile)
            threading.Thread(target=self._drain_logs, args=(active,), daemon=True).start()
            try:
                await self._wait_healthy(active)
                if engine == "gguf":
                    # The native server may cap the usable per-slot context.
                    # Read it once at startup, never on the send-to-token path.
                    try:
                        async with httpx.AsyncClient(timeout=5) as client:
                            response = await client.get(f"{active.base_url}/props")
                            response.raise_for_status()
                            effective = response.json().get("default_generation_settings", {}).get("n_ctx")
                            if isinstance(effective, int) and effective > 0:
                                active.context_limit = min(active.context_limit, effective)
                    except (httpx.HTTPError, ValueError, AttributeError):
                        pass  # Python and older native servers need not expose props.
            except BaseException:
                self._stop_process(active)
                raise
            self.active = active
            return active

    def _spawn_llama_cpp(self, model_path: str, port: int,
                         context_limit: int) -> subprocess.Popen:
        native = LLAMA_SERVER_BIN or server_path()
        if native:
            command = [native, "-m", model_path, "--port", str(port),
                       "--host", "127.0.0.1", "-ngl", "999", "-c", str(context_limit), "--parallel", "1"]
        else:
            try:
                import llama_cpp  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "The local text runtime is missing. Open Settings and repair the "
                    "Uncloud engine."
                ) from exc
            command = [sys.executable, "-m", "llama_cpp.server", "--model", model_path,
                       "--port", str(port), "--host", "127.0.0.1",
                       "--n_gpu_layers", "999", "--n_ctx", str(context_limit)]
        return subprocess.Popen(
            command,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )

    def _spawn_mlx(self, model_path: str, port: int,
                   adapter_path: str | None = None) -> subprocess.Popen:
        command = [sys.executable, "-m", "mlx_lm", "server", "--model", model_path,
                   "--port", str(port), "--host", "127.0.0.1"]
        if adapter_path:
            command += ["--adapter-path", adapter_path]
        return subprocess.Popen(
            command,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )

    def _spawn_mlx_vlm(self, model_path: str, port: int) -> subprocess.Popen:
        """Vision-language models carry an image encoder alongside the text stack,
        which mlx_lm's server can't drive — mlx_vlm serves the same OpenAI-shaped
        API but accepts image content parts in messages."""
        return subprocess.Popen(
            [sys.executable, "-m", "mlx_vlm.server", "--model", model_path,
             "--port", str(port), "--host", "127.0.0.1"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )

    @property
    def supports_vision(self) -> bool:
        return self.active is not None and self.active.engine == "mlx-vlm"

    @staticmethod
    def _drain_logs(active: ActiveEngine) -> None:
        # A full unread stdout pipe blocks generation, not just logging.
        if active.process.stdout:
            for line in active.process.stdout:
                active.logs.append(line.decode(errors="replace").rstrip()[-2000:])

    async def _wait_healthy(self, active: ActiveEngine, timeout: float = 120.0) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        async with httpx.AsyncClient() as client:
            while asyncio.get_event_loop().time() < deadline:
                if active.process.poll() is not None:
                    out = "\n".join(active.logs)
                    raise RuntimeError(f"Engine process exited early:\n{out[-2000:]}")
                try:
                    r = await client.get(f"{active.base_url}/v1/models", timeout=2.0)
                    if r.is_success:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)
        raise RuntimeError("Timed out waiting for the inference engine to become healthy.")

    def _stop_process(self, active: ActiveEngine) -> None:
        try:
            active.process.terminate()
            active.process.wait(timeout=5)
        except Exception:  # noqa: BLE001
            with contextlib.suppress(Exception):
                active.process.kill()

    def stop(self) -> None:
        if self.active:
            self._stop_process(self.active)
            self.active = None

    def status(self) -> dict:
        if not self.active or self.active.process.poll() is not None:
            return {"running": False}
        return {
            "running": True, "model_path": self.active.model_path,
            "engine": self.active.engine, "port": self.active.port,
            "adapter_path": self.active.adapter_path,
            "context_limit": self.active.context_limit,
            "context_profile": for_model(self.active.model_path, self.active.engine),
            "inference_profile": self.active.inference_profile,
            # So the interface can offer image attachment against a model that
            # can actually receive one, and say why when it cannot — rather
            # than accepting the picture and having the model ignore it.
            "supports_vision": self.supports_vision,
        }


engine_manager = EngineManager()
