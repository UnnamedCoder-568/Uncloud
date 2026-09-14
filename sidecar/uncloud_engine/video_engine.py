"""Text-to-video via diffusers.

Memory is the whole problem. LTX ships a T5 text encoder that is 18 GB on
disk in fp32; loaded as-is alongside the transformer and VAE it will not fit
on a 24 GB machine, and what you get is not an error but an hour of swapping.
Loading in bfloat16 halves it, and dropping the encoder once the prompt is
embedded keeps only one large component resident at a time.

That is as far as bfloat16 goes, and it is not far enough: 6.5 GB of weights
puts video out of reach of every 8 GB machine before a frame is drawn. There
is no MLX runtime for video the way mflux is for images, so the speed path
that fixed the image side does not exist here. What does exist is GGUF —
weights stay packed and are dequantised per operation — and it works on Metal
even though nothing says so. A Q4 transformer holds 3.4 GB where bfloat16
holds 6.5.

So this module knows two families. LTX loads a diffusers folder whole. Wan is
assembled from GGUF files beside a diffusers skeleton, and is both the newer
model and the smaller one. They differ in more than loading — frame counts
are 8n+1 for LTX and 4n+1 for Wan, and Wan's encode_prompt returns embeddings
without attention masks — so the differences live in one table rather than
scattered through the generate path.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import output_dir_for
from .core import placement
from .output_check import verify_video
from .power import keep_awake

# LTX accepts frame counts of the form 8n+1; anything else is silently padded.
DEFAULT_FRAMES = 49          # ~2s at 24fps
DEFAULT_FPS = 24
DEFAULT_W, DEFAULT_H = 960, 544
DEFAULT_STEPS = 40
DEFAULT_GUIDANCE = 3.0
DEFAULT_EXPORT_QUALITY = 9.0
DEFAULT_NEGATIVE_PROMPT = (
    "worst quality, inconsistent motion, blurry, jittery, distorted"
)
MAX_PIXELS = 1216 * 704      # LTX's recommended sub-720p detail ceiling

# A folder holding one of these declares which family it belongs to and where
# its GGUF files are. Without it a folder is assumed to be LTX, which is what
# every already-installed video model is.
VIDEO_MARKER = "uncloud-video.json"


def _stop_wan_upsampling_in_float32() -> None:
    """Upsample Wan's frames at the dtype they arrive in.

    WanUpsample casts to float32, upsamples, and casts back. It sits at the
    widest point in the decoder — after the last spatial expansion — so that
    round trip doubles the largest tensor in the whole pipeline, and the decode
    is already the memory peak.

    It buys nothing at these settings. Both stages use mode="nearest-exact",
    which copies values rather than interpolating between them, so there is no
    precision to preserve: upsampling a bfloat16 tensor directly on Metal gave
    a result bit-identical to the float32 round trip, and did it in 1.36ms
    against 2.02ms. Left alone for any mode that actually interpolates, where
    the cast would be doing real work.
    """
    try:
        from diffusers.models.autoencoders.autoencoder_kl_wan import WanUpsample
    except Exception:  # noqa: BLE001 - a newer diffusers may have moved it
        return
    if getattr(WanUpsample.forward, "_uncloud_no_upcast", False):
        return

    import torch.nn as nn

    def forward(self, x):
        if str(self.mode).startswith("nearest"):
            return nn.Upsample.forward(self, x)
        return nn.Upsample.forward(self, x.float()).type_as(x)

    forward._uncloud_no_upcast = True
    WanUpsample.forward = forward


_stop_wan_upsampling_in_float32()


@dataclass(frozen=True)
class Family:
    """What differs between video model families, in one place.

    Getting frame_step wrong is not an error — the pipeline rounds silently and
    returns a clip of a length nobody asked for — so it is declared rather than
    inferred.
    """
    name: str
    frame_step: int              # accepted frame counts are frame_step*n + 1
    size_multiple: int
    max_pixels: int
    steps: int
    guidance: float
    fps: int


FAMILIES: dict[str, Family] = {
    "ltx": Family(name="ltx", frame_step=8, size_multiple=32,
                  max_pixels=1216 * 704, steps=40, guidance=3.0, fps=24),
    # Wan 2.2 TI2V-5B is native 1280x704 at 24fps, and its VAE compresses 4x
    # temporally rather than LTX's 8x.
    "wan": Family(name="wan", frame_step=4, size_multiple=16,
                  max_pixels=1280 * 704, steps=30, guidance=5.0, fps=24),
}


def read_marker(model_path: str) -> dict:
    """What a model folder says about itself, or nothing."""
    import json

    marker = Path(model_path) / VIDEO_MARKER
    if not marker.is_file():
        return {}
    try:
        return json.loads(marker.read_text())
    except (OSError, ValueError):
        return {}


def family_for(model_path: str) -> Family:
    """The loader family: from the folder's marker, else from its own pipeline.

    Defaulting to LTX when there was no marker meant a Wan pipeline without
    one was opened with LTXPipeline. The pipeline class it declares says which
    it is, so that is asked before any default.
    """
    declared = read_marker(model_path).get("family", "")
    if declared in FAMILIES:
        return FAMILIES[declared]
    from .core.models import identify
    from .model_import import VIDEO_FAMILIES

    detected = VIDEO_FAMILIES.get(identify(Path(model_path), sizes=False).family, "")
    return FAMILIES.get(detected, FAMILIES["ltx"])


def free_device_cache() -> None:
    """Hand cached buffers back, on whichever accelerator this is.

    Every one of these calls used to be guarded by a check for Metal, which
    made the tiled decode a no-op on CUDA — it releases each tile and then
    nothing reclaims it, so the memory that tiling exists to save is never
    given up. The guards were written on a Mac and describe the machine they
    were written on rather than the problem.
    """
    import torch

    if torch.backends.mps.is_available():
        torch.mps.empty_cache()
    elif torch.cuda.is_available():
        torch.cuda.empty_cache()


def valid_frames(n: int, family: Family | None = None) -> int:
    """Round to a frame count this family will actually honour."""
    step = (family or FAMILIES["ltx"]).frame_step
    n = max(step + 1, min(257, int(n)))
    return ((n - 1) // step) * step + 1


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
    #: How the model's parts were arranged for this run — resident, or one of
    #: the offloads. Reported so a clip that took six minutes can say why it
    #: was not ninety seconds.
    placement: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "prompt": self.prompt, "status": self.status,
            "stage": self.stage, "step": self.step, "total_steps": self.total_steps,
            "output_path": self.output_path, "error": self.error,
            "placement": self.placement,
            "done": self.status in ("done", "error"),
        }


class VideoEngine:
    def __init__(self) -> None:
        self.jobs: dict[str, VideoJob] = {}
        self._pipe = None
        self._loaded_path: str | None = None

    def _encode(self, prompt: str, negative_prompt: str, guidance: float,
                family: Family) -> dict:
        """Turn the prompt into embeddings while the encoder is still loaded.

        The two families disagree about what an embedding is: LTX returns
        attention masks alongside and its pipeline expects them back, Wan
        returns embeddings alone and rejects the mask arguments.
        """
        import torch

        with torch.no_grad():
            result = self._pipe.encode_prompt(
                prompt=prompt,
                negative_prompt=negative_prompt or "",
                do_classifier_free_guidance=guidance > 1.0,
                device=self._pipe._execution_device,  # noqa: SLF001
            )

        if family.name == "wan":
            pe, ne = result
            out = {"prompt_embeds": pe}
            if ne is not None:
                out["negative_prompt_embeds"] = ne
            return out

        pe, pm, ne, nm = result
        out = {"prompt_embeds": pe, "prompt_attention_mask": pm}
        if ne is not None:
            out["negative_prompt_embeds"] = ne
            out["negative_prompt_attention_mask"] = nm
        return out

    def _release_text_encoder(self) -> None:
        """Drop the encoder once the prompt is embedded.

        Nothing downstream reads it — the pipeline is given embeddings — and it
        is the single largest thing in the pipeline. Reloaded on the next
        generation, which costs a read rather than an out-of-memory failure.
        """
        import gc


        self._pipe.text_encoder = None
        self._loaded_path = None   # force a reload before the next prompt
        gc.collect()
        free_device_cache()

    @staticmethod
    def _build_wan(model_path: str, marker: dict, dtype):
        """Assemble a Wan pipeline whose two big components stay quantised.

        The folder is a diffusers skeleton — configs, tokenizer, scheduler and
        the VAE, which is small enough to leave alone — with the transformer
        and text encoder supplied as GGUF beside it. Both are loaded through
        their own from_pretrained/from_single_file so each keeps its packed
        weights; diffusers dequantises per operation at compute time, and that
        path runs on Metal even though only CUDA and CPU are named in it.

        3.4 GB of transformer and 3.7 GB of encoder against 20 GB and 11 GB at
        bfloat16, for the same model.
        """
        from diffusers import (
            AutoencoderKLWan,
            GGUFQuantizationConfig,
            UniPCMultistepScheduler,
            WanPipeline,
            WanTransformer3DModel,
        )
        from transformers import AutoTokenizer, UMT5EncoderModel

        root = Path(model_path)
        gguf = GGUFQuantizationConfig(compute_dtype=dtype)

        transformer = WanTransformer3DModel.from_single_file(
            str(root / marker["transformer_gguf"]),
            quantization_config=gguf, torch_dtype=dtype,
            config=str(root / "transformer"),
        )
        text_encoder = UMT5EncoderModel.from_pretrained(
            str(root / "text_encoder"),
            gguf_file=str(root / marker["text_encoder_gguf"]),
            torch_dtype=dtype,
        )
        # The reference pipeline loads this VAE at float32, and on a machine
        # with memory to spare that is the safe default. Here it is the whole
        # budget: decoding 25 frames at 704x480 measured 12.03GB at float32
        # against 3.24GB at bfloat16 — and the bfloat16 decode was the faster
        # of the two, 230s against 303s, with output in the same [-1, 1] range.
        # The decoder upcasts to float32 internally where it matters anyway.
        vae = AutoencoderKLWan.from_pretrained(str(root / "vae"), torch_dtype=dtype)

        # Assembling a pipeline by hand skips the flags from_pretrained would
        # have read out of model_index.json. TI2V-5B sets expand_timesteps, and
        # without it the timestep schedule is wrong in a way that still runs:
        # every step completes, nothing raises, and the clip comes out as
        # moving colour with no subject in it.
        import json

        try:
            index = json.loads((root / "model_index.json").read_text())
        except (OSError, ValueError):
            index = {}

        return WanPipeline(
            tokenizer=AutoTokenizer.from_pretrained(str(root / "tokenizer")),
            text_encoder=text_encoder,
            transformer=transformer,
            vae=vae,
            scheduler=UniPCMultistepScheduler.from_pretrained(str(root / "scheduler")),
            boundary_ratio=index.get("boundary_ratio"),
            expand_timesteps=bool(index.get("expand_timesteps", False)),
        )

    def _release_transformer(self) -> None:
        """Drop the transformer once the last step is done.

        The same argument as the text encoder, at the other end of the job: the
        decode is the largest single allocation in a video generation, and by
        the time it starts the transformer has nothing left to do. Holding 3.4GB
        of it through the decode is 3.4GB the decode cannot have.
        """
        import gc


        self._pipe.transformer = None
        self._loaded_path = None   # force a reload before the next prompt
        gc.collect()
        free_device_cache()

    def _decode_wan_tiled(self, latents, tile: int = 256, stride: int = 192):
        """Decode Wan latents a tile at a time, freeing each before the next.

        Wan ships a tiled decode and it runs out of memory on Metal, which is
        why this exists. Its version decodes every tile of every row into a
        list and blends afterwards — fine where memory is plentiful, fatal
        here, because the tiles themselves are small (about 10MB each) but the
        working set of each tile's decode is not, and MPS holds those buffers
        until something asks it not to. Twenty-eight tiles' worth accumulates.

        Same tiles, same blend, same output; the difference is that a tile is
        released as soon as it has been decoded, and only the row above is kept
        for the vertical blend. Measured at 704x480: 1.21GB against 4.89GB
        decoding whole frames, for about 30% more time.
        """
        import torch
        from diffusers.models.autoencoders.autoencoder_kl_wan import unpatchify

        vae = self._pipe.vae
        ratio = vae.spatial_compression_ratio
        _, _, num_frames, height, width = latents.shape
        tile_h = tile_w = tile // ratio
        stride_h = stride_w = stride // ratio

        patch = vae.config.patch_size
        sample_h, sample_w = height * ratio, width * ratio
        if patch is not None:
            sample_h, sample_w = sample_h // patch, sample_w // patch
            out_h, out_w = stride // patch, stride // patch
            blend_h, blend_w = tile // patch - out_h, tile // patch - out_w
        else:
            out_h = out_w = stride
            blend_h = blend_w = tile - stride

        previous, out_rows = None, []
        for i in range(0, height, stride_h):
            row = []
            for j in range(0, width, stride_w):
                vae.clear_cache()
                frames = []
                for k in range(num_frames):
                    vae._conv_idx = [0]  # noqa: SLF001 - the cache protocol
                    piece = vae.post_quant_conv(latents[:, :, k:k + 1, i:i + tile_h, j:j + tile_w])
                    frames.append(vae.decoder(
                        piece, feat_cache=vae._feat_map,  # noqa: SLF001
                        feat_idx=vae._conv_idx, first_chunk=(k == 0)))
                row.append(torch.cat(frames, dim=2))
                del frames, piece
                free_device_cache()

            cropped = []
            for j, piece in enumerate(row):
                if previous is not None:
                    piece = vae.blend_v(previous[j], piece, blend_h)
                if j > 0:
                    piece = vae.blend_h(row[j - 1], piece, blend_w)
                cropped.append(piece[:, :, :, :out_h, :out_w])
            out_rows.append(torch.cat(cropped, dim=-1))
            previous = row
            del cropped
            free_device_cache()

        vae.clear_cache()
        decoded = torch.cat(out_rows, dim=3)[:, :, :, :sample_h, :sample_w]
        if patch is not None:
            decoded = unpatchify(decoded, patch_size=patch)
        return torch.clamp(decoded, -1.0, 1.0)

    def _decode_wan(self, latents):
        """Decode Wan latents the way its pipeline would, after the fact.

        Denoising with output_type="latent" returns before the decode, which is
        the whole point — it leaves a window to free the transformer. The cost
        is doing the pipeline's own denormalisation here.
        """
        import torch

        vae = self._pipe.vae
        cfg = vae.config
        latents = latents.to(vae.dtype)
        mean = (torch.tensor(cfg.latents_mean).view(1, cfg.z_dim, 1, 1, 1)
                .to(latents.device, latents.dtype))
        inv_std = (1.0 / torch.tensor(cfg.latents_std).view(1, cfg.z_dim, 1, 1, 1)
                   .to(latents.device, latents.dtype))
        with torch.no_grad():
            video = self._decode_wan_tiled(latents / inv_std + mean)
        return self._pipe.video_processor.postprocess_video(video, output_type="np")[0]

    def list_jobs(self) -> list[dict]:
        return [j.to_dict() for j in self.jobs.values()]

    def get(self, job_id: str) -> VideoJob | None:
        return self.jobs.get(job_id)

    def unload(self) -> None:
        self._pipe = None
        self._loaded_path = None
        try:
            import gc


            gc.collect()
            free_device_cache()
        except Exception:  # noqa: BLE001
            pass

    def start(
        self, model_path: str, prompt: str, *,
        negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
        frames: int = DEFAULT_FRAMES, fps: int = DEFAULT_FPS,
        width: int = DEFAULT_W, height: int = DEFAULT_H,
        steps: int = DEFAULT_STEPS, guidance: float = DEFAULT_GUIDANCE,
        seed: int | None = None,
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

    def _arrangement(self, model_path: str, family: str, frames: int,
                     width: int, height: int):
        """How this clip's parts should be placed on this machine.

        Asked of the same planner the capability gate uses, so what the user
        was told is possible is what actually gets set up. Two answers to that
        question is how a gate and a loader come to disagree.
        """
        from .budget import _placement_for, memory_budget, resident_weights_gb

        return _placement_for(frames, width, height,
                              resident_weights_gb(model_path), family,
                              1.4, memory_budget())

    def _generate(self, job, model_path, prompt, negative_prompt, frames, fps,
                  width, height, steps, guidance, seed) -> str:
        import torch
        from diffusers import LTXPipeline
        from diffusers.utils import export_to_video

        family = family_for(model_path)
        marker = read_marker(model_path)

        if width * height > family.max_pixels:
            scale = (family.max_pixels / (width * height)) ** 0.5
            width, height = int(width * scale), int(height * scale)
        mult = family.size_multiple
        width, height = max(mult * 5, width // mult * mult), max(mult * 5, height // mult * mult)
        frames = valid_frames(frames, family)

        device = "mps" if torch.backends.mps.is_available() else (
            "cuda" if torch.cuda.is_available() else "cpu"
        )

        if self._pipe is None or self._loaded_path != model_path:
            self._pipe = None
            job.stage = "loading model"
            # bfloat16 is the difference between 12 GB and 24 GB here.
            if family.name == "wan":
                pipe = self._build_wan(model_path, marker, torch.bfloat16)
            else:
                pipe = LTXPipeline.from_pretrained(model_path, torch_dtype=torch.bfloat16)
            # How the parts are arranged is decided by the planner, not by the
            # device string. It used to be the latter: anything that was not
            # Apple Silicon got component offloading whether it needed it or
            # not, and a machine with room to hold the whole pipeline paid for
            # moving it anyway.
            #
            # The reasoning the device check encoded is kept, in the planner:
            # on Apple Silicon the CPU and GPU share one pool, so offloading
            # frees nothing and buys a real copy — measured at 2.32ms per 8MB
            # round trip, about 3.4 GB/s, for the ~15GB of components here.
            # There the plan comes back RESIDENT or it does not run at all.
            arrangement = self._arrangement(model_path, family.name,
                                            frames, width, height)
            job.placement = arrangement.placement.value
            if arrangement.placement is placement.Placement.SEQUENTIAL_OFFLOAD:
                job.stage = "loading model (a layer at a time — slower)"
                try:
                    pipe.enable_sequential_cpu_offload(device=device)
                except Exception:  # noqa: BLE001 - older diffusers, or no support
                    pipe.enable_model_cpu_offload(device=device)
            elif arrangement.placement is placement.Placement.MODEL_OFFLOAD:
                job.stage = "loading model (a part at a time)"
                try:
                    pipe.enable_model_cpu_offload(device=device)
                except Exception:  # noqa: BLE001 - fall back to a plain move
                    pipe = pipe.to(device)
            else:
                pipe = pipe.to(device)
            # The decode is the peak here, as it is for images — but the fix
            # does not transfer. LTX tiles its decode and wants tiling on.
            # Wan's tiled_decode runs out of memory on Metal at every tile size
            # measured, default 256px tiles included, because each tile carries
            # its own frame cache and the overlaps accumulate; its plain path
            # already walks the clip a frame at a time and completes. Tiling
            # Wan made a decode that works into one that does not.
            if family.name != "wan":
                with contextlib.suppress(Exception):
                    pipe.vae.enable_tiling()
            self._pipe = pipe
            self._loaded_path = model_path

        gen = None
        if seed is not None:
            gen = torch.Generator(device="cpu").manual_seed(int(seed))

        job.stage = "generating"

        def progress(_p, step_index, _t, cb_kwargs):
            job.step = int(step_index) + 1
            return cb_kwargs

        # The text encoder is 9.4GB and runs once, at the start. Leaving it
        # resident through thirty denoising steps is most of why a four-second
        # clip ran out of memory on a 24GB machine: the weights were 15.3GB
        # while the sequence itself needed under half a gigabyte.
        job.stage = "reading prompt"
        embeds = self._encode(prompt, negative_prompt, float(guidance), family)
        self._release_text_encoder()

        job.stage = "generating"
        call = dict(
            width=width, height=height,
            num_frames=frames,
            num_inference_steps=int(steps),
            guidance_scale=float(guidance),
            generator=gen,
            callback_on_step_end=progress,
            **embeds,
        )
        if family.name == "wan":
            latents = self._pipe(output_type="latent", **call).frames
            self._release_transformer()
            job.stage = "decoding"
            clip = self._decode_wan(latents)
        else:
            clip = self._pipe(**call).frames[0]

        job.stage = "encoding"
        dest = output_dir_for("video") / f"{job.id}.mp4"
        # Diffusers defaults to quality=5, which visibly softens already-small
        # generated frames. Preserve detail in the MP4 rather than throwing it
        # away during the final encode.
        export_to_video(
            clip, str(dest), fps=int(fps),
            quality=DEFAULT_EXPORT_QUALITY,
        )
        return str(dest)


video_engine = VideoEngine()
