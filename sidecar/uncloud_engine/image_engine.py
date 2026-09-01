from __future__ import annotations

import asyncio
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any



# Kontext renders at the source image's dimensions unless told otherwise. A 1792x2390
# phone-camera or catalogue photo is ~4.3MP, which pushes peak memory past 16GB on a
# 24GB Mac and drops the machine into swap — measured at 563s/step versus 20s/step at
# 0.5MP. Cap the working resolution unless the caller asks for something specific.
MAX_EDIT_PIXELS = 1024 * 1024


from .flux2_profile import flux2_profile_runtime, profile_for
from .mflux_runtime import can_run_in_process, mflux_runtime
from .output_check import summarise_traceback, verify_image
from .config import output_dir_for
from .power import keep_awake


def _fit_within_budget(reference_path: str) -> tuple[int, int] | None:
    """Scale the source's aspect ratio down to the pixel budget, snapped to /16."""
    try:
        from PIL import Image

        with Image.open(reference_path) as im:
            w, h = im.size
    except Exception:  # noqa: BLE001 - unreadable dims just means "let mflux decide"
        return None

    if w <= 0 or h <= 0 or w * h <= MAX_EDIT_PIXELS:
        return None

    scale = (MAX_EDIT_PIXELS / (w * h)) ** 0.5
    new_w = max(256, int(w * scale) // 16 * 16)
    new_h = max(256, int(h * scale) // 16 * 16)
    return new_w, new_h


def _mflux_bin(cli_name: str) -> str | None:
    return shutil.which(cli_name)


@dataclass
class ImageJob:
    id: str
    prompt: str
    status: str = "pending"  # pending | running | done | error
    step: int = 0
    total_steps: int = 0
    output_path: str | None = None
    error: str | None = None
    kind: str = "generate"  # generate | edit
    label: str | None = None  # e.g. the shot name in a Product batch

    def to_dict(self) -> dict:
        return {
            "id": self.id, "prompt": self.prompt, "status": self.status,
            "step": self.step, "total_steps": self.total_steps,
            "done": self.status in ("done", "error"), "error": self.error,
            "kind": self.kind, "label": self.label,
            # The UI needs the path to offer Save / Save as / Reveal on a result.
            "output_path": self.output_path,
        }


class ImageEngine:
    """Runs image generation via mflux (MLX, for FLUX-family models like Krea 2)
    or diffusers (torch, for everything else). At most one diffusers pipeline is
    kept resident at a time — these are multi-GB and this Mac's RAM is shared.
    """

    def __init__(self) -> None:
        self.jobs: dict[str, ImageJob] = {}
        self._pipe: Any = None
        self._pipe_path: str | None = None

    def list_jobs(self) -> list[dict]:
        return [j.to_dict() for j in self.jobs.values()]

    def unload(self) -> None:
        """Drop the resident pipeline. Called by the stop button and on exit."""
        import gc

        self._pipe = None
        self._pipe_path = None
        gc.collect()
        try:
            import torch

            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            elif torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001 - torch may not be importable here
            pass

    def _free_memory_for(self, engine: str) -> None:
        """Diffusion models are multi-GB; on a 16-24GB Mac they can't comfortably
        coexist with a loaded chat model. Free the text engine before generating,
        and drop any resident diffusers pipeline when about to run mflux instead."""
        from .engines import engine_manager

        if engine_manager.active:
            engine_manager.stop()
        if engine != "diffusers" and self._pipe is not None:
            self.unload()
        if engine != "mflux":
            # A diffusers pipeline and a resident mflux model will not both fit.
            mflux_runtime.unload()
        if engine != "flux2-profile":
            flux2_profile_runtime.unload()

    def start(
        self, model_path: str, engine: str, prompt: str, *, negative_prompt: str = "",
        steps: int | None = None, guidance: float | None = None,
        width: int = 1024, height: int = 1024, seed: int | None = None,
        mflux_cli: str = "mflux-generate", mflux_base: str | None = None,
        text_encoder_path: str | None = None,
        lora_paths: list[str] | None = None, lora_scales: list[float] | None = None,
    ) -> ImageJob:
        job = ImageJob(id=uuid.uuid4().hex[:12], prompt=prompt, total_steps=steps or 0)
        self.jobs[job.id] = job
        asyncio.create_task(self._run(
            job, model_path, engine, prompt, negative_prompt, steps, guidance, width, height,
            seed, mflux_cli, mflux_base, text_encoder_path, lora_paths, lora_scales,
        ))
        return job

    async def _run(
        self, job: ImageJob, model_path: str, engine: str, prompt: str, negative_prompt: str,
        steps: int | None, guidance: float | None, width: int, height: int, seed: int | None,
        mflux_cli: str, mflux_base: str | None = None,
        text_encoder_path: str | None = None,
        lora_paths: list[str] | None = None, lora_scales: list[float] | None = None,
    ) -> None:
        job.status = "running"
        try:
            # Diffusion can run for minutes on a laptop; hold sleep off.
            with keep_awake("image"):
                self._free_memory_for(engine)
                if engine == "mflux":
                    out = await self._run_mflux(job, model_path, prompt, steps, guidance,
                                                width, height, seed, mflux_cli, mflux_base,
                                                lora_paths, lora_scales)
                elif engine == "flux2-profile":
                    out = await asyncio.to_thread(
                        self._run_flux2_profile, job, model_path, prompt, steps,
                        guidance, width, height, seed, text_encoder_path,
                    )
                elif engine == "diffusers":
                    out = await asyncio.to_thread(
                        self._run_diffusers, job, model_path, prompt, negative_prompt,
                        steps, guidance, width, height, seed, text_encoder_path,
                    )
                else:
                    raise ValueError(
                        f"'{engine}' models cannot be generated with yet. "
                        "Pick a model listed as mflux or diffusers — the Models "
                        "tab shows which is which."
                    )
                # Check before claiming success: a flat grey rectangle is a
                # failure, not a picture, and must not be handed over as one.
                verify_image(out)
                job.output_path = out
                job.status = "done"
        except Exception as exc:  # noqa: BLE001 - surface any generation failure to the UI
            job.status = "error"
            job.error = str(exc)

    def start_edit(
        self, model_path: str, prompt: str, reference_path: str, *,
        steps: int | None = None, guidance: float | None = None,
        width: int | None = None, height: int | None = None, seed: int | None = None,
        strength: float | None = None, mflux_cli: str = "mflux-generate-kontext",
        label: str | None = None,
    ) -> ImageJob:
        """Reference-image editing: an input image plus an instruction."""
        job = ImageJob(id=uuid.uuid4().hex[:12], prompt=prompt, total_steps=steps or 0,
                       kind="edit", label=label)
        self.jobs[job.id] = job
        asyncio.create_task(self._run_edit(
            job, model_path, prompt, reference_path, steps, guidance,
            width, height, seed, strength, mflux_cli,
        ))
        return job

    async def _run_edit(
        self, job: ImageJob, model_path: str, prompt: str, reference_path: str,
        steps: int | None, guidance: float | None, width: int | None, height: int | None,
        seed: int | None, strength: float | None, mflux_cli: str,
    ) -> None:
        job.status = "running"
        try:
            if not Path(reference_path).exists():
                raise FileNotFoundError(f"Reference image not found: {reference_path}")
            self._free_memory_for("mflux")

            mflux_bin = _mflux_bin(mflux_cli)
            if not mflux_bin:
                raise RuntimeError(f"{mflux_cli} not found on PATH — is the `mflux` package installed?")

            out_path = output_dir_for() / f"{job.id}.png"
            steps = steps or 28
            job.total_steps = steps
            seed = seed if seed is not None else int(time.time())

            cmd = [
                mflux_bin, "--model", model_path, "--prompt", prompt,
                "--image", reference_path,
            ]
            if strength is not None:
                cmd.append(str(strength))
            cmd += [
                "--steps", str(steps), "--seed", str(seed),
                "--guidance", str(guidance if guidance is not None else 2.5),
                "--low-ram", "--vae-tiling",
                "--output", str(out_path),
            ]
            # Caller-supplied dimensions win; otherwise clamp to the pixel budget so a
            # large source photo can't silently drive the machine into swap.
            if not (width and height):
                fitted = _fit_within_budget(reference_path)
                if fitted:
                    width, height = fitted
            if width:
                cmd += ["--width", str(width)]
            if height:
                cmd += ["--height", str(height)]

            await self._stream_mflux(job, cmd, out_path, mflux_cli)
            verify_image(out_path, what="edited image")
            job.output_path = str(out_path)
            job.status = "done"
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            job.status = "error"
            job.error = str(exc)

    async def _stream_mflux(self, job: ImageJob, cmd: list[str], out_path: Path, cli_name: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        tail: list[str] = []
        assert proc.stdout
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode(errors="ignore")
            tail.append(text)
            tail[:] = tail[-40:]
            m = re.search(r"(\d+)\s*/\s*(\d+)", text)
            if m:
                job.step, job.total_steps = int(m.group(1)), int(m.group(2))
        code = await proc.wait()
        if code != 0 or not out_path.exists():
            detail = "".join(tail)
            raise RuntimeError(
                f"{cli_name} failed: {summarise_traceback(detail)}"
            )

    async def _run_mflux(
        self, job: ImageJob, model_path: str, prompt: str, steps: int | None,
        guidance: float | None, width: int, height: int, seed: int | None, mflux_cli: str,
        mflux_base: str | None = None,
        lora_paths: list[str] | None = None, lora_scales: list[float] | None = None,
    ) -> str:
        out_path = output_dir_for() / f"{job.id}.png"
        steps = steps or 8
        job.total_steps = steps
        seed = seed if seed is not None else int(time.time())

        # Preferred path: the model stays in memory between generations. The
        # subprocess below reloaded every weight for every image, which on a
        # 22 GB model is minutes of work repeated for no reason.
        if can_run_in_process(mflux_cli):
            def on_step(n: int) -> None:
                job.step = n

            return await asyncio.to_thread(
                mflux_runtime.generate,
                cli=mflux_cli, model_path=model_path, prompt=prompt, seed=seed,
                base=mflux_base, steps=steps, width=width, height=height,
                lora_paths=lora_paths, lora_scales=lora_scales,
                guidance=guidance if guidance is not None else 1.0,
                on_step=on_step, out_path=out_path,
            )

        mflux_bin = _mflux_bin(mflux_cli)
        if not mflux_bin:
            raise RuntimeError(f"{mflux_cli} not found on PATH — is the `mflux` package installed?")
        cmd = [
            mflux_bin, "--model", model_path, "--prompt", prompt,
            "--steps", str(steps), "--seed", str(seed),
            "--width", str(width), "--height", str(height),
            "--guidance", str(guidance if guidance is not None else 1.0),
            "--low-ram", "--vae-tiling",
            "--output", str(out_path),
        ]
        await self._stream_mflux(job, cmd, out_path, mflux_cli)
        return str(out_path)

    def _run_flux2_profile(
        self, job: ImageJob, model_path: str, prompt: str, steps: int | None,
        guidance: float | None, width: int, height: int, seed: int | None,
        text_encoder_path: str | None,
    ) -> str:
        """A folder that names its parts — see flux2_profile for why."""
        profile = profile_for(model_path)
        steps = steps or profile.steps or 4
        job.total_steps = steps

        def on_step(n: int) -> None:
            job.step = n

        return flux2_profile_runtime.generate(
            profile, prompt=prompt, steps=steps,
            guidance=guidance if guidance is not None else (profile.guidance or 1.0),
            width=width, height=height,
            seed=seed if seed is not None else int(time.time()),
            out_path=output_dir_for() / f"{job.id}.png",
            on_step=on_step, text_encoder_path=text_encoder_path,
        )

    def _swap_text_encoder(self, pipe, gguf_path: str) -> None:
        """Replace a pipeline's text encoder with one loaded from a GGUF file.

        FLUX.2 Klein's text encoder is a Qwen3ForCausalLM — an instruction
        following model — which is where its restraint lives, so replacing it is
        what actually changes what the pipeline will render. It is also the
        cheaper half: 4.7GB quantised against 15GB.

        Only meaningful for pipelines whose encoder is a causal LM. Krea 2's
        restraint is trained into the transformer and no swap will move it.
        """
        import torch
        from transformers import AutoModelForCausalLM

        encoder = getattr(pipe, "text_encoder", None)
        if encoder is None:
            raise RuntimeError("This pipeline has no text encoder to replace.")
        if type(encoder).__name__ not in ("Qwen3ForCausalLM", "Qwen2ForCausalLM"):
            raise RuntimeError(
                f"{type(encoder).__name__} is not a causal language model, so an "
                "uncensored encoder would not change its behaviour. This only "
                "applies to FLUX.2 Klein."
            )

        gguf = Path(gguf_path)
        if not gguf.is_file():
            raise FileNotFoundError(f"Text encoder not found: {gguf}")

        replacement = AutoModelForCausalLM.from_pretrained(
            str(gguf.parent), gguf_file=gguf.name, torch_dtype=torch.bfloat16,
        )
        pipe.text_encoder = replacement

    def _load_pipeline(self, model_path: str, text_encoder_path: str | None = None):
        key = (model_path, text_encoder_path)
        if self._pipe is not None and self._pipe_path == key:
            return self._pipe

        import torch
        from diffusers import AutoPipelineForText2Image, StableDiffusionXLPipeline

        self._pipe = None  # let the old pipeline get GC'd / freed before loading the next
        dtype = torch.bfloat16
        if Path(model_path).is_file():
            # AutoPipelineForText2Image has no from_single_file — single .safetensors
            # checkpoints in the wild are essentially always SD1.5/SDXL format.
            pipe = StableDiffusionXLPipeline.from_single_file(model_path, torch_dtype=dtype)
        else:
            pipe = AutoPipelineForText2Image.from_pretrained(model_path, torch_dtype=dtype)

        if text_encoder_path:
            self._swap_text_encoder(pipe, text_encoder_path)

        if torch.backends.mps.is_available():
            device = "mps"
        elif torch.cuda.is_available():
            device = "cuda"
        else:
            device = "cpu"
        pipe = pipe.to(device)

        self._pipe, self._pipe_path = pipe, key
        return pipe

    def _run_diffusers(
        self, job: ImageJob, model_path: str, prompt: str, negative_prompt: str,
        steps: int | None, guidance: float | None, width: int, height: int,
        seed: int | None, text_encoder_path: str | None = None,
    ) -> str:
        import torch

        pipe = self._load_pipeline(model_path, text_encoder_path)
        steps = steps or 25
        job.total_steps = steps
        generator = torch.Generator(device="cpu").manual_seed(seed if seed is not None else int(time.time()))

        def on_step_end(_pipe, step, _timestep, kwargs):
            job.step = step + 1
            return kwargs

        kwargs: dict[str, Any] = dict(
            prompt=prompt, num_inference_steps=steps, width=width, height=height,
            generator=generator, callback_on_step_end=on_step_end,
        )
        if negative_prompt:
            kwargs["negative_prompt"] = negative_prompt
        if guidance is not None:
            kwargs["guidance_scale"] = guidance

        result = pipe(**kwargs)
        image = result.images[0]
        out_path = output_dir_for() / f"{job.id}.png"
        image.save(out_path)
        return str(out_path)


image_engine = ImageEngine()
