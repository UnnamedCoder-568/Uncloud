"""Text-to-video via diffusers. Currently LTX-Video.

Memory is the whole problem. LTX ships a T5 text encoder that is 18 GB on
disk in fp32; loaded as-is alongside the transformer and VAE it will not fit
on a 24 GB machine, and what you get is not an error but an hour of swapping.
Loading in bfloat16 halves it, and offloading each component back to the CPU
between stages keeps only one resident at a time.

Frame counts follow LTX's own constraint of 8n+1.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path

from .output_check import verify_video
from .config import output_dir_for
from .power import keep_awake



# LTX accepts frame counts of the form 8n+1; anything else is silently padded.
DEFAULT_FRAMES = 49          # ~2s at 24fps
DEFAULT_FPS = 24
DEFAULT_W, DEFAULT_H = 512, 320
MAX_PIXELS = 704 * 480       # beyond this a 24 GB machine starts swapping


def valid_frames(n: int) -> int:
    """Round to the nearest 8n+1 that LTX will actually honour."""
    n = max(9, min(257, int(n)))
    return ((n - 1) // 8) * 8 + 1


@dataclass
class VideoJob:
    id: str
    prompt: str
    status: str = "pending"        # pending | running | done | error
    stage: str = ""
    step: int = 0
    total_steps: int = 0
    output_path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "prompt": self.prompt, "status": self.status,
            "stage": self.stage, "step": self.step, "total_steps": self.total_steps,
            "output_path": self.output_path, "error": self.error,
            "done": self.status in ("done", "error"),
        }


class VideoEngine:
    def __init__(self) -> None:
        self.jobs: dict[str, VideoJob] = {}
        self._pipe = None
        self._loaded_path: str | None = None

    def list_jobs(self) -> list[dict]:
        return [j.to_dict() for j in self.jobs.values()]

    def get(self, job_id: str) -> VideoJob | None:
        return self.jobs.get(job_id)

    def unload(self) -> None:
        self._pipe = None
        self._loaded_path = None
        try:
            import gc

            import torch

            gc.collect()
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except Exception:  # noqa: BLE001
            pass

    def start(
        self, model_path: str, prompt: str, *, negative_prompt: str = "",
        frames: int = DEFAULT_FRAMES, fps: int = DEFAULT_FPS,
        width: int = DEFAULT_W, height: int = DEFAULT_H,
        steps: int = 30, guidance: float = 3.0, seed: int | None = None,
    ) -> VideoJob:
        job = VideoJob(id=uuid.uuid4().hex[:12], prompt=prompt, total_steps=steps)
        self.jobs[job.id] = job
        asyncio.create_task(self._run(
            job, model_path, prompt, negative_prompt, frames, fps,
            width, height, steps, guidance, seed,
        ))
        return job

    async def _run(self, job, model_path, prompt, negative_prompt, frames, fps,
                   width, height, steps, guidance, seed) -> None:
        job.status = "running"
        job.stage = "loading model"
        try:
            with keep_awake("video"):
                from .engines import engine_manager

                # A text model and a video pipeline cannot share 24 GB.
                if engine_manager.active:
                    engine_manager.stop()
                from .image_engine import image_engine

                image_engine.unload()

                out = await asyncio.to_thread(
                    self._generate, job, model_path, prompt, negative_prompt,
                    frames, fps, width, height, steps, guidance, seed,
                )
                verify_video(out)
                job.output_path = out
                job.status = "done"
                job.stage = ""
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            job.status = "error"
            job.error = str(exc)
            self.unload()

    def _generate(self, job, model_path, prompt, negative_prompt, frames, fps,
                  width, height, steps, guidance, seed) -> str:
        import torch
        from diffusers import LTXPipeline
        from diffusers.utils import export_to_video

        if width * height > MAX_PIXELS:
            scale = (MAX_PIXELS / (width * height)) ** 0.5
            width, height = int(width * scale) // 32 * 32, int(height * scale) // 32 * 32
        # LTX wants both dimensions divisible by 32.
        width, height = max(160, width // 32 * 32), max(160, height // 32 * 32)
        frames = valid_frames(frames)

        device = "mps" if torch.backends.mps.is_available() else (
            "cuda" if torch.cuda.is_available() else "cpu"
        )

        if self._pipe is None or self._loaded_path != model_path:
            self._pipe = None
            job.stage = "loading model"
            # bfloat16 is the difference between 12 GB and 24 GB here.
            pipe = LTXPipeline.from_pretrained(model_path, torch_dtype=torch.bfloat16)
            # Offloading components back to the CPU between stages is how you
            # fit a pipeline into a small VRAM budget — on a discrete GPU. On
            # Apple Silicon the CPU and GPU share one pool, so it frees nothing
            # and buys a real copy: measured 2.32ms per 8MB round trip, about
            # 3.4 GB/s, for the ~15GB of components here. Load straight to the
            # device and let the shared memory do its job.
            if device == "mps":
                pipe = pipe.to(device)
            else:
                try:
                    pipe.enable_model_cpu_offload(device=device)
                except Exception:  # noqa: BLE001 - fall back to a plain move
                    pipe = pipe.to(device)
            try:
                pipe.vae.enable_tiling()
            except Exception:  # noqa: BLE001
                pass
            self._pipe = pipe
            self._loaded_path = model_path

        gen = None
        if seed is not None:
            gen = torch.Generator(device="cpu").manual_seed(int(seed))

        job.stage = "generating"

        def progress(_p, step_index, _t, cb_kwargs):
            job.step = int(step_index) + 1
            return cb_kwargs

        result = self._pipe(
            prompt=prompt,
            negative_prompt=negative_prompt or None,
            width=width, height=height,
            num_frames=frames,
            num_inference_steps=int(steps),
            guidance_scale=float(guidance),
            generator=gen,
            callback_on_step_end=progress,
        )
        job.stage = "encoding"
        dest = output_dir_for("video") / f"{job.id}.mp4"
        export_to_video(result.frames[0], str(dest), fps=int(fps))
        return str(dest)


video_engine = VideoEngine()
