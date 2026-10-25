"""Build a pre-quantised MLX checkpoint from a model already on disk.

A diffusion model shipped at bf16 is stored in a form this machine cannot hold:
FLUX.2 Klein is 34GB against 24GB of memory, so every prompt evicts half the
pipeline and reloads it. Quantising once and saving the result turns that into
a single fast read of something that fits.

Precision is uniform across components, and not by choice. Splitting it — an
8-bit transformer beside a 4-bit encoder — is the obviously appealing trade,
since the transformer decides every pixel while the encoder only points it in a
direction. This builder used to do exactly that, and the result was quietly
wrong: mflux reads one quantization_level per checkpoint, from the first
component that records one, and passes that single value to nn.quantize for all
of them. For FLUX.2 the first component is the VAE. So a mixed build had its
4-bit encoder rebuilt as 8-bit modules and then filled with 4-bit-packed arrays
by model.update(strict=False) — no shape check, no warning, garbage embeddings.

The encoder swap looking like it made no difference was this, not the encoder.

Uniform 6-bit costs what the 8/4 split was meant to cost and actually loads, so
that is the trade to reach for when 8-bit will not fit.

Note that lower precision does not run faster here. On an M5 a bf16 matmul
measured 13.57 TFLOPS against 11.94 for int4 — quantisation is cheaper to hold
and slightly more expensive to compute. Pick the highest precision that fits.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .library import MLX_MARKER, invalidate_library_cache

# What mflux will quantise to. 3 and 5 exist but are rarely worth it.
BITS = (3, 4, 5, 6, 8)
GGUF_TYPES = {2: (10, "Q2_K"), 3: (12, "Q3_K_M"), 4: (15, "Q4_K_M"),
              5: (17, "Q5_K_M"), 6: (18, "Q6_K"), 8: (7, "Q8_0")}


def gguf_source(source: str) -> dict:
    """Read the stored precision, without loading weights or guessing from names."""
    from .core.models.headers import read_gguf
    from .core.models.identify import _GGUF_FILE_TYPES

    header = read_gguf(Path(source))
    if header is None:
        raise ValueError("Choose a valid GGUF model file.")
    kind = header.fields.get('general.file_type')
    return {'quantization': _GGUF_FILE_TYPES.get(kind, 'Unknown precision'),
            'file_type': kind, 'quantized': kind not in (0, 1, 32),
            'unchanged_bits': [bits for bits, (value, _) in GGUF_TYPES.items() if value == kind]}


def gguf_quantizer() -> str | None:
    import sys

    from .native_chat import RUNTIME_DIR, server_path

    explicit = os.environ.get('UNCLOUD_LLAMA_QUANTIZE')
    if explicit and Path(explicit).is_file():
        return explicit
    name = 'llama-quantize.exe' if sys.platform == 'win32' else 'llama-quantize'
    roots = []
    if server := server_path():
        roots.extend((Path(server).parent, Path(server).parent.parent))
    roots.append(RUNTIME_DIR)
    if bundled := os.environ.get('UNCLOUD_LLAMA_RUNTIME_DIR'):
        roots.append(Path(bundled))
    found = next((str(root / name) for root in roots if (root / name).is_file()), None)
    return found or shutil.which(name)

# Components mflux writes. The first two are the ones worth choosing between.
_COMPONENTS = ("transformer", "text_encoder", "vae", "tokenizer")


def base_models() -> list[dict]:
    """Base models mflux can configure, for the picker to offer."""
    import inspect

    try:
        from mflux.models.common.config.model_config import ModelConfig
    except ImportError:
        return []  # GGUF quantization does not require the Apple-only image engine.

    out: list[dict] = []
    for name in sorted(dir(ModelConfig)):
        if name.startswith("_"):
            continue
        factory = getattr(ModelConfig, name)
        if not callable(factory):
            continue
        try:
            if inspect.signature(factory).parameters:
                continue
            config = factory()
        except Exception:  # noqa: BLE001 - not every attribute is a factory
            continue
        repo = getattr(config, "model_name", None)
        if repo:
            out.append({"id": name, "repo": repo, "cli": name.replace("_", "-")})
    return out


@dataclass
class QuantizeJob:
    id: str
    name: str
    dest: str
    kind: str = "image"
    adapter_path: str | None = None
    allow_requantize: bool = False
    status: str = "running"  # running | done | error
    stage: str = "starting"
    error: str | None = None
    size_gb: float = 0.0
    log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "dest": self.dest,
            "status": self.status,
            "stage": self.stage,
            "error": self.error,
            "done": self.status in ("done", "error", "cancelled"),
            "kind": self.kind,
            "size_gb": round(self.size_gb, 2),
            "log": self.log[-12:],
        }


def _mflux_save_bin() -> Path:
    import sys

    candidate = Path(sys.executable).parent / "mflux-save"
    if candidate.is_file():
        return candidate
    found = shutil.which("mflux-save")
    if found:
        return Path(found)
    raise RuntimeError("mflux-save not found — is the `mflux` package installed?")


class QuantizeManager:
    def __init__(self) -> None:
        self.jobs: dict[str, QuantizeJob] = {}
        self._tasks: set[asyncio.Task] = set()
        self._by_id: dict[str, asyncio.Task] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    def list_jobs(self) -> list[dict]:
        return [j.to_dict() for j in self.jobs.values()]

    def start(
        self,
        *,
        source: str,
        base: str,
        dest_dir: str,
        name: str,
        transformer_bits: int,
        encoder_bits: int,
        lora_paths: list[str] | None = None,
        lora_scales: list[float] | None = None,
        kind: str = "image",
        adapter_path: str | None = None,
        allow_requantize: bool = False,
    ) -> QuantizeJob:
        if kind not in {"image", "text", "gguf"}:
            raise ValueError("Choose image, text MLX or GGUF quantization.")
        if not name.strip() or Path(name).name != name or name in {".", ".."} or "\\" in name:
            raise ValueError("Output name must be a single folder name.")
        if kind == "text" and not (Path(source) / "config.json").is_file():
            raise ValueError("Text quantization requires a complete local model directory.")
        if kind == "gguf" and not Path(source).is_file():
            raise ValueError("GGUF quantization requires a local GGUF file.")
        if adapter_path and kind != "text":
            raise ValueError("Text adapters can only be merged with their MLX base model.")
        allowed = tuple(GGUF_TYPES) if kind == 'gguf' else BITS
        for bits in ((transformer_bits,) if kind == 'gguf'
                     else (transformer_bits, encoder_bits)):
            if bits not in allowed:
                raise ValueError(f"{bits}-bit is not one of {allowed}")
        if kind == 'image' and transformer_bits != encoder_bits:
            raise ValueError(
                f"A mixed build cannot be loaded: mflux applies one precision to "
                f"every component, taken from whichever it reads first. "
                f"{transformer_bits}-bit weights beside {encoder_bits}-bit ones "
                f"would be read at a single width and produce nonsense. Build "
                f"uniformly — 6-bit costs about what {transformer_bits}/"
                f"{encoder_bits} was meant to."
            )
        if not Path(source).exists():
            raise FileNotFoundError(f"No model at {source}")
        if kind == 'gguf':
            info = gguf_source(source)
            target_type, target_name = GGUF_TYPES[transformer_bits]
            if info['file_type'] == target_type:
                raise ValueError(f"This model already uses {target_name}. Choose a lower "
                                 "precision for a smaller copy.")
            if info['quantized'] and not allow_requantize:
                raise ValueError(f"This model already uses {info['quantization']}. Enable "
                                 "re-quantization to compress it again; quality can decrease.")
            if not gguf_quantizer():
                raise RuntimeError("The GGUF quantizer is missing. Install the llama.cpp "
                                   "quantizer or set UNCLOUD_LLAMA_QUANTIZE to its path.")

        dest = Path(dest_dir) / name
        if dest.exists() or any(
            j.dest == str(dest) and j.status == "running" for j in self.jobs.values()
        ):
            raise ValueError(
                "That output already exists. Choose a new name; source files are never replaced."
            )
        job = QuantizeJob(id=uuid.uuid4().hex[:12], name=name, dest=str(dest), kind=kind)
        job.adapter_path = adapter_path
        job.allow_requantize = allow_requantize
        self.jobs[job.id] = job
        task = asyncio.create_task(
            self._run(
                job,
                source,
                base,
                dest,
                transformer_bits,
                encoder_bits,
                lora_paths or [],
                lora_scales or [],
            )
        )
        self._by_id[job.id] = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        task = self._by_id.get(job_id)
        if not job or not task or job.status != "running":
            return False
        task.cancel()
        job.status = "cancelled"
        job.stage = "Stopped; source files preserved"
        return True

    async def _run(
        self,
        job: QuantizeJob,
        source: str,
        base: str,
        dest: Path,
        transformer_bits: int,
        encoder_bits: int,
        lora_paths: list[str],
        lora_scales: list[float],
    ) -> None:
        from .power import keep_awake

        staging = dest.parent / f".{dest.name}.{job.id}.building"
        try:
            with keep_awake("quantize"):
                shutil.rmtree(staging, ignore_errors=True)
                staging.mkdir(parents=True, exist_ok=True)

                job.stage = f"quantising at {transformer_bits}-bit"
                dest_tmp = staging / "final"
                if job.kind == "image":
                    await self._mflux_save(
                        job, source, base, dest_tmp, transformer_bits, lora_paths, lora_scales
                    )
                else:
                    await self._text_save(job, source, dest_tmp, transformer_bits, staging)

                if job.kind == "image":
                    (dest_tmp / MLX_MARKER).write_text(
                        json.dumps(
                            {
                                "schemaVersion": 1,
                                "name": job.name,
                                "base_model": base,
                                "quantize": transformer_bits,
                                "source": source,
                                "lora_paths": lora_paths,
                            },
                            indent=2,
                        )
                        + "\n"
                    )

                if dest.exists():
                    raise RuntimeError(
                        "The destination appeared during the build; it was preserved."
                    )
                shutil.move(str(dest_tmp), str(dest))

                from .library import _dir_size_gb  # noqa: PLC0415

                job.size_gb = _dir_size_gb(dest)
                job.stage = "done"
                job.status = "done"
                invalidate_library_cache()
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.stage = "Stopped; source files preserved"
            raise
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            job.status = "error"
            job.error = str(exc)
            job.stage = "failed"
        finally:
            proc = self._processes.pop(job.id, None)
            if proc is not None and proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 5)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
            shutil.rmtree(staging, ignore_errors=True)

    async def _mflux_save(
        self,
        job: QuantizeJob,
        source: str,
        base: str,
        out: Path,
        bits: int,
        lora_paths: list[str],
        lora_scales: list[float],
    ) -> None:
        cmd = [
            str(_mflux_save_bin()),
            "--model",
            source,
            "--base-model",
            base.replace("_", "-"),
            "--path",
            str(out),
            "--quantize",
            str(bits),
        ]
        if lora_paths:
            cmd += ["--lora-paths", *lora_paths]
            if lora_scales:
                cmd += ["--lora-scales", *(str(s) for s in lora_scales)]
            cmd.append("--bake-lora")

        await self._command(job, cmd)

    async def _text_save(self, job, source, out, bits, staging):
        import sys

        if job.kind == "gguf":
            found = gguf_quantizer()
            if not found:
                raise RuntimeError(
                    "The GGUF quantizer is missing. Install the llama.cpp runtime before building."
                )
            out.mkdir()
            options = ['--allow-requantize'] if job.allow_requantize else []
            await self._command(job, [found, *options, source, str(out / "model.gguf"),
                                      GGUF_TYPES[bits][1]])
            if gguf_source(str(out / 'model.gguf'))['file_type'] != GGUF_TYPES[bits][0]:
                raise RuntimeError('The quantizer did not produce the requested GGUF precision.')
            return
        adapter = job.adapter_path
        if adapter:
            fused = staging / "fused"
            job.stage = "Merging the text adapter"
            await self._command(
                job,
                [
                    sys.executable,
                    "-m",
                    "mlx_lm.fuse",
                    "--model",
                    source,
                    "--adapter-path",
                    adapter,
                    "--save-path",
                    str(fused),
                    "--dequantize",
                ],
            )
            source = str(fused)
        job.stage = f"Building {bits}-bit text weights"
        await self._command(
            job,
            [
                sys.executable,
                "-m",
                "mlx_lm.convert",
                "--hf-path",
                source,
                "--mlx-path",
                str(out),
                "-q",
                "--q-bits",
                str(bits),
                "--q-group-size",
                "64",
            ],
        )

    async def _command(self, job, cmd):
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._processes[job.id] = proc
        assert proc.stdout
        tail: list[str] = []
        while True:
            chunk = await proc.stdout.readline()
            if not chunk:
                break
            # mflux draws progress bars with carriage returns; keep only lines
            # that carry information a person would want.
            text = chunk.decode(errors="ignore").replace("\r", "\n")
            for line in text.splitlines():
                line = line.strip()
                if line and "%|" not in line:
                    tail.append(line)
                    tail[:] = tail[-40:]
                    job.log.append(line)
                    job.log[:] = job.log[-40:]
        if await proc.wait() != 0:
            from .output_check import summarise_traceback

            raise RuntimeError(f"Model build failed: {summarise_traceback(chr(10).join(tail))}")


quantize_manager = QuantizeManager()
