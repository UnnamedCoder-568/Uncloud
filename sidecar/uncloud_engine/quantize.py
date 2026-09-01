"""Build a pre-quantised MLX checkpoint from a model already on disk.

A diffusion model shipped at bf16 is stored in a form this machine cannot hold:
FLUX.2 Klein is 34GB against 24GB of memory, so every prompt evicts half the
pipeline and reloads it. Quantising once and saving the result turns that into
a single fast read of something that fits.

Precision is chosen per component, because the two halves do not deserve the
same budget. The transformer decides every pixel — faces first, since fine
facial structure is the highest-frequency detail an image has and the least
tolerant of coarse weights. The text encoder only turns a prompt into a
direction for the transformer to follow, and carries that just as well at low
precision. An 8-bit transformer beside a 4-bit encoder costs what a uniform
6-bit build costs and looks considerably better.

Note that lower precision does not run faster here. On an M5 a bf16 matmul
measured 13.57 TFLOPS against 11.94 for int4 — quantisation is cheaper to hold
and slightly more expensive to compute. Pick the highest precision that fits.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .library import MLX_MARKER, invalidate_library_cache

# What mflux will quantise to. 3 and 5 exist but are rarely worth it.
BITS = (3, 4, 5, 6, 8)

# Components mflux writes. The first two are the ones worth choosing between.
_COMPONENTS = ("transformer", "text_encoder", "vae", "tokenizer")


def base_models() -> list[dict]:
    """Base models mflux can configure, for the picker to offer."""
    import inspect

    from mflux.models.common.config.model_config import ModelConfig

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
    status: str = "running"          # running | done | error
    stage: str = "starting"
    error: str | None = None
    size_gb: float = 0.0
    log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "dest": self.dest,
            "status": self.status, "stage": self.stage, "error": self.error,
            "done": self.status in ("done", "error"),
            "size_gb": round(self.size_gb, 2), "log": self.log[-12:],
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

    def list_jobs(self) -> list[dict]:
        return [j.to_dict() for j in self.jobs.values()]

    def start(
        self, *, source: str, base: str, dest_dir: str, name: str,
        transformer_bits: int, encoder_bits: int,
        lora_paths: list[str] | None = None, lora_scales: list[float] | None = None,
    ) -> QuantizeJob:
        for bits in (transformer_bits, encoder_bits):
            if bits not in BITS:
                raise ValueError(f"{bits}-bit is not one of {BITS}")
        if not Path(source).exists():
            raise FileNotFoundError(f"No model at {source}")

        dest = Path(dest_dir) / name
        job = QuantizeJob(id=uuid.uuid4().hex[:12], name=name, dest=str(dest))
        self.jobs[job.id] = job
        asyncio.create_task(self._run(
            job, source, base, dest, transformer_bits, encoder_bits,
            lora_paths or [], lora_scales or [],
        ))
        return job

    async def _run(
        self, job: QuantizeJob, source: str, base: str, dest: Path,
        transformer_bits: int, encoder_bits: int,
        lora_paths: list[str], lora_scales: list[float],
    ) -> None:
        from .power import keep_awake

        staging = dest.parent / f".{dest.name}.building"
        try:
            with keep_awake("quantize"):
                shutil.rmtree(staging, ignore_errors=True)
                staging.mkdir(parents=True, exist_ok=True)

                # One pass per distinct precision. mflux quantises the whole
                # model at once, so a mixed build costs two passes and then
                # keeps one component folder from each.
                levels = sorted({transformer_bits, encoder_bits}, reverse=True)
                built: dict[int, Path] = {}
                for i, bits in enumerate(levels, 1):
                    job.stage = f"quantising at {bits}-bit ({i} of {len(levels)})"
                    out = staging / f"q{bits}"
                    await self._mflux_save(job, source, base, out, bits,
                                           lora_paths, lora_scales)
                    built[bits] = out

                job.stage = "assembling"
                dest_tmp = staging / "final"
                dest_tmp.mkdir(parents=True, exist_ok=True)
                picks = {
                    "transformer": transformer_bits,
                    "text_encoder": encoder_bits,
                    "vae": transformer_bits,
                    "tokenizer": transformer_bits,
                }
                for component, bits in picks.items():
                    src = built[bits] / component
                    if src.is_dir():
                        shutil.move(str(src), str(dest_tmp / component))

                (dest_tmp / MLX_MARKER).write_text(json.dumps({
                    "schemaVersion": 1,
                    "name": job.name,
                    "base_model": base,
                    "quantize": transformer_bits,
                    "encoder_quantize": encoder_bits,
                    "source": source,
                    "lora_paths": lora_paths,
                }, indent=2) + "\n")

                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.move(str(dest_tmp), str(dest))

                from .library import _dir_size_gb  # noqa: PLC0415

                job.size_gb = _dir_size_gb(dest)
                job.stage = "done"
                job.status = "done"
                invalidate_library_cache()
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            job.status = "error"
            job.error = str(exc)
            job.stage = "failed"
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    async def _mflux_save(
        self, job: QuantizeJob, source: str, base: str, out: Path, bits: int,
        lora_paths: list[str], lora_scales: list[float],
    ) -> None:
        cmd = [
            str(_mflux_save_bin()), "--model", source,
            "--base-model", base.replace("_", "-"),
            "--path", str(out), "--quantize", str(bits),
        ]
        if lora_paths:
            cmd += ["--lora-paths", *lora_paths]
            if lora_scales:
                cmd += ["--lora-scales", *(str(s) for s in lora_scales)]
            cmd.append("--bake-lora")

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
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

            raise RuntimeError(
                f"Quantising at {bits}-bit failed: "
                f"{summarise_traceback(chr(10).join(tail))}"
            )


quantize_manager = QuantizeManager()
