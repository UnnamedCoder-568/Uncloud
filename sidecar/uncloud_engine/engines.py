from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass, field

import httpx

from .context_profile import for_model
from .inference_profile import load as load_inference_profile
from .native_chat import host_fit_margin_mb, inspect_runtime, server_path

LLAMA_SERVER_BIN = os.environ.get('UNCLOUD_LLAMA_SERVER')


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
    context_details: dict = field(default_factory=dict)
    runtime: dict = field(default_factory=dict)
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
        self.loading: ActiveEngine | None = None
        self._lock = asyncio.Lock()

    async def start(
        self, model_path: str, engine: str, adapter_path: str | None = None,
        context_length: int | None = None,
        reload: bool = False,
    ) -> ActiveEngine:
        async with self._lock:
            if engine == "mlx":
                from .text_runtime import for_mlx_model

                engine = for_mlx_model(model_path)
            if (
                self.active
                and self.active.model_path == model_path
                and self.active.engine == engine
                and self.active.adapter_path == adapter_path
                and self.active.process.poll() is None
                and not reload
                and (context_length is None or self.active.context_limit == context_length)
            ):
                return self.active
            profile = for_model(model_path, engine)
            if context_length is not None:
                native = profile.get("native_limit")
                if (
                    isinstance(context_length, bool) or not isinstance(context_length, int)
                    or context_length < 256
                    or (native and context_length > native)
                ):
                    raise ValueError(
                        'Context must fit the supported window: a whole number from 256 '
                        f"to {native or 'the native limit'}.")
                profile = {**profile, "effective_limit": context_length}
                if engine != "gguf" or not native:
                    raise ValueError("Context overrides require GGUF context metadata.")
            if self.active:
                self._stop_process(self.active)
                self.active = None

            port = _free_port()
            model_profile, inference_profile = load_inference_profile(model_path, engine)
            from .inference_controls import discover
            native = (LLAMA_SERVER_BIN or server_path()) if engine == 'gguf' else None
            runtime = inspect_runtime(native)
            automatic_context = engine == 'gguf' and context_length is None and runtime['auto_fit']
            inference_profile["capabilities"] = discover(model_path, engine, native=bool(native))
            if engine == "gguf":
                from .tool_template import compact

                original_template = inference_profile['capabilities'].get('template', '')
                tool_template = compact(original_template)
                proc = self._spawn_llama_cpp(
                    model_path, port, None if automatic_context else profile["effective_limit"],
                    **({'tool_template': tool_template} if runtime.get('template_file')
                       and tool_template != original_template else {}))
            elif engine == "mlx":
                proc = self._spawn_mlx(model_path, port, adapter_path, profile["effective_limit"])
                # The library's generic 512-token default is not a model limit.
                # Auto may use the available native window; EOS still ends early.
                defaults = inference_profile["capabilities"].setdefault("runtime_defaults", {})
                defaults["max_tokens"] = profile["effective_limit"]
            elif engine == "mlx-vlm":
                proc = self._spawn_mlx_vlm(
                    model_path, port, profile["effective_limit"], adapter_path)
            else:
                raise ValueError(f"No text-inference launcher for engine: {engine}")

            active = ActiveEngine(
                model_path=model_path,
                engine=engine,
                port=port,
                process=proc,
                adapter_path=adapter_path,
                context_limit=(profile.get('native_limit') or profile['effective_limit'])
                              if automatic_context else profile['effective_limit'],
                model_profile=model_profile,
                inference_profile=inference_profile,
                context_details={**profile, 'requested_limit': context_length,
                                 'source': 'Native runtime memory fitting'
                                 if automatic_context else profile.get('source', 'Model metadata')},
                runtime={**runtime, 'executable': native},
            )
            self.loading = active
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
                            effective = (
                                response.json().get("default_generation_settings", {}).get("n_ctx")
                            )
                            if isinstance(effective, int) and effective > 0:
                                active.context_limit = effective
                            elif automatic_context:
                                raise RuntimeError(
                                    'The runtime did not report its fitted context window.')
                            predicted = response.json().get("default_generation_settings", {}).get(
                                "params", {}).get("n_predict")
                            if isinstance(predicted, int) and predicted > 0:
                                inference_profile["capabilities"].setdefault(
                                    "runtime_defaults", {})["max_tokens"] = predicted
                            else:
                                # Native -1 means unlimited generation. Bound the total reply
                                # to the loaded window, without splitting thinking vs answer.
                                inference_profile['capabilities'].setdefault(
                                    'runtime_defaults', {})['max_tokens'] = active.context_limit
                            # Count this model's native boundary once at load.
                            # Never assume every tokenizer closes thinking in one token.
                            budget = inference_profile["capabilities"]["reasoning"].get("budget")
                            if budget:
                                ending = await client.post(f"{active.base_url}/tokenize", json={
                                    "content": budget["end_sequence"], "add_special": False,
                                    "parse_special": True,
                                })
                                ending.raise_for_status()
                                token_ids = ending.json().get("tokens")
                                if not isinstance(token_ids, list) or not token_ids:
                                    raise ValueError(
                                        "The native thinking boundary could not be counted.")
                                budget["closing_tokens"] = len(token_ids)
                    except (httpx.HTTPError, ValueError, AttributeError):
                        if automatic_context:
                            raise RuntimeError(
                                'Could not confirm the runtime context window.') from None
                        # Python/older servers need not expose native metadata.
                        cap = inference_profile["capabilities"]
                        reason = cap["reasoning"]
                        if reason.pop("budget", None):
                            cap["fields"] = [key for key in cap["fields"]
                                             if key != "reasoning_budget"]
                            if reason["mechanism"] == "template_toggle":
                                reason["levels"] = ["auto", "off", "high"]
                                reason["explanation"] = (
                                    "Thinking on/off is available; a separate native thinking "
                                    "limit could not be verified.")
                            elif reason["mechanism"] != "template_effort":
                                reason["levels"] = ["auto"]
                                reason["explanation"] = (
                                    "A native thinking limit could not be verified.")
            except BaseException:
                self._stop_process(active)
                self.loading = None
                raise
            self.loading = None
            self.active = active
            return active

    def _spawn_llama_cpp(self, model_path: str, port: int,
                         context_limit: int | None, *, tool_template: str = '') -> subprocess.Popen:
        native = LLAMA_SERVER_BIN or server_path()
        if native:
            command = [
                native,
                "-m",
                model_path,
                "--port",
                str(port),
                "--host",
                "127.0.0.1",
            ]
            options = inspect_runtime(native)
            if context_limit is not None:
                command += ['-c', str(context_limit)]
            if options['auto_fit']:
                command += ['--fit', 'on']
                if not options['devices'] and (margin := host_fit_margin_mb()) is not None:
                    command += ['--fit-target', str(margin)]
            if options['context_stop']:
                command += ['--no-context-shift']
            command += ['--parallel', '1']
            if tool_template:
                from .tool_template import cache_file

                command += ['--jinja', '--chat-template-file', cache_file(tool_template)]
        else:
            try:
                import llama_cpp  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "The local text runtime is missing. Open Settings and repair the "
                    "Uncloud engine."
                ) from exc
            command = [
                sys.executable,
                "-m",
                "llama_cpp.server",
                "--model",
                model_path,
                "--port",
                str(port),
                "--host",
                "127.0.0.1",
                "--n_gpu_layers",
                "999",
                "--n_ctx",
                str(context_limit or 8192),
            ]
        return subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

    def _spawn_mlx(
        self, model_path: str, port: int, adapter_path: str | None = None,
        context_limit: int | None = None,
    ) -> subprocess.Popen:
        command = [
            sys.executable,
            "-m",
            "uncloud_engine.mlx_server",
            "--model",
            model_path,
            "--port",
            str(port),
            "--host",
            "127.0.0.1",
        ]
        if adapter_path:
            command += ["--adapter-path", adapter_path]
        if context_limit is not None:
            command += ["--max-tokens", str(context_limit)]
        environment = dict(os.environ)
        if context_limit is not None:
            environment["UNCLOUD_CONTEXT_LIMIT"] = str(context_limit)
        return subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=environment,
        )

    def _spawn_mlx_vlm(self, model_path: str, port: int,
                       context_limit: int | None = None,
                       adapter_path: str | None = None) -> subprocess.Popen:
        """Vision-language models carry an image encoder alongside the text stack,
        which mlx_lm's server can't drive — mlx_vlm serves the same OpenAI-shaped
        API but accepts image content parts in messages."""
        command = [
            sys.executable, "-m", "uncloud_engine.vlm_server", "--model", model_path,
            "--port", str(port), "--host", "127.0.0.1",
        ]
        if context_limit is not None:
            command += ["--max-kv-size", str(context_limit)]
        if adapter_path:
            command += ["--adapter-path", adapter_path]
        return subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
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
        process = active.process
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            raise RuntimeError('The previous model could not be unloaded. No new model was loaded.')

    def stop(self) -> None:
        if self.loading:
            self._stop_process(self.loading)
            self.loading = None
        if self.active:
            self._stop_process(self.active)
            self.active = None

    def status(self) -> dict:
        if not self.active or self.active.process.poll() is not None:
            return {"running": False}
        return {
            "running": True,
            "model_path": self.active.model_path,
            "engine": self.active.engine,
            "port": self.active.port,
            "adapter_path": self.active.adapter_path,
            "context_limit": self.active.context_limit,
            "context_profile": {
                **(getattr(self.active, 'context_details', {}) or for_model(
                    self.active.model_path, self.active.engine)),
                "effective_limit": self.active.context_limit,
                'limited_by_memory': bool(getattr(self.active, 'context_details', {}).get(
                    'native_limit') and self.active.context_limit < self.active.context_details[
                        'native_limit']),
            },
            'runtime': getattr(self.active, 'runtime', {}),
            "inference_profile": self.active.inference_profile,
            # So the interface can offer image attachment against a model that
            # can actually receive one, and say why when it cannot — rather
            # than accepting the picture and having the model ignore it.
            "supports_vision": self.supports_vision,
        }


engine_manager = EngineManager()
