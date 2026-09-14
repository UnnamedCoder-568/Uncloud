"""Adding a model Uncloud did not download itself.

What a model IS comes from Core (`core.models`), identical in both products.
This file answers the question that is Uncloud's alone: can one of Uncloud's
engines actually run it? A model that is recognised and not runnable is listed
as exactly that, with the reason — never marked ready and left to fail when
somebody picks it.

The pipeline sets below are what each engine really loads. Image generation
goes through diffusers' AutoPipelineForText2Image, so its mapping is the list;
video goes through two hand-written loaders, so it is two families. Both are
checked against the installed libraries in the tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .budget import engine_runs_here
from .core.models import Identification, Layout, Task, apply, hub, identify, plan
from .core.models.identify import MANIFEST

#: diffusers AutoPipelineForText2Image, 0.39. Only the pipelines an import
#: could plausibly produce; a pipeline absent here is not claimed runnable.
TEXT2IMAGE = frozenset({
    "AuraFlowPipeline", "ChromaPipeline", "Flux2KleinPipeline", "Flux2Pipeline",
    "FluxKontextPipeline", "FluxPipeline", "HunyuanDiTPipeline", "Krea2Pipeline",
    "Lumina2Pipeline", "LuminaPipeline", "PixArtSigmaPipeline", "QwenImagePipeline",
    "SanaPipeline", "StableDiffusion3Pipeline", "StableDiffusionPipeline",
    "StableDiffusionXLPipeline", "ZImagePipeline",
})

#: Of those, the ones AutoPipelineForImage2Image also opens: an edit tab entry.
IMAGE2IMAGE = frozenset({
    "Flux2KleinPipeline", "Flux2Pipeline", "FluxKontextPipeline", "QwenImageEditPipeline",
    "StableDiffusion3Pipeline", "StableDiffusionPipeline", "StableDiffusionXLPipeline",
    "ZImagePipeline",
})

#: Core family -> video_engine family. The only two it has loaders for.
VIDEO_FAMILIES = {"ltx-video": "ltx", "wan": "wan"}

_MFLUX_CLI = {
    "flux2_klein_4b": "mflux-generate-flux2-klein", "flux2_klein_9b": "mflux-generate-flux2-klein",
    "krea2": "mflux-generate-krea2", "z_image_turbo": "mflux-generate-z-image",
}


@dataclass
class Verdict:
    runnable: bool
    category: str
    engine: str
    note: str = ""
    capabilities: list[str] = field(default_factory=list)
    mflux_cli: str | None = None
    mflux_base: str | None = None

    def to_dict(self) -> dict:
        return {"runnable": self.runnable, "category": self.category, "engine": self.engine,
                "note": self.note, "capabilities": self.capabilities}


def verdict(i: Identification) -> Verdict:
    """Which engine runs this, or why none does."""
    task, layout, family = i.task, i.layout, i.family

    if task is Task.TEXT:
        if layout is Layout.GGUF:
            return Verdict(True, "text", "gguf", capabilities=["chat"])
        if layout is Layout.MLX:
            ok = engine_runs_here("mlx")
            return Verdict(ok, "text", "mlx", "" if ok else
                           "MLX weights run only on Apple Silicon.", ["chat"])
        return Verdict(False, "text", "unsupported",
                       f"A {layout} language model. Uncloud chats through GGUF (llama.cpp) "
                       "and MLX weights; this format would need converting first.")

    if task is Task.TEXT_ENCODER:
        return Verdict(layout is Layout.GGUF, "component", "text-encoder",
                       "Text encoder for a diffusion pipeline — pair it with a model, not "
                       "selectable on its own.")

    if task is Task.IMAGE and layout is Layout.MFLUX:
        cli = _MFLUX_CLI.get(family)
        ok = cli is not None and engine_runs_here("mflux")
        note = ("" if ok else "mflux runs only on Apple Silicon." if cli
                else "Which base model this checkpoint was cut from is not recorded yet.")
        return Verdict(ok, "image", "mflux", note, ["text2img"], mflux_cli=cli,
                       mflux_base=family or None)

    if task is Task.IMAGE and layout in (Layout.DIFFUSERS, Layout.DIFFUSERS_PARTS):
        if i.pipeline in TEXT2IMAGE:
            capabilities = ["text2img"] + (["edit"] if i.pipeline in IMAGE2IMAGE else [])
            waiting = layout is Layout.DIFFUSERS_PARTS
            return Verdict(not waiting, "image", "diffusers",
                           "Needs its model_index.json before it can load." if waiting else "",
                           capabilities)
        return Verdict(False, "image", "diffusers",
                       f"{i.pipeline or 'This pipeline'} is not one Uncloud's image engine "
                       "opens.")

    if task is Task.VIDEO and layout in (Layout.DIFFUSERS, Layout.DIFFUSERS_PARTS):
        engine_family = VIDEO_FAMILIES.get(family)
        if engine_family is None:
            return Verdict(False, "video", "diffusers",
                           f"Uncloud's video engine loads LTX-Video and Wan; this is "
                           f"{family or 'an unrecognised family'}.")
        waiting = layout is Layout.DIFFUSERS_PARTS
        return Verdict(not waiting, "video", "diffusers",
                       "Needs its model_index.json before it can load." if waiting else "",
                       ["text2video"])

    if task in (Task.IMAGE, Task.VIDEO) and layout in (Layout.GGUF, Layout.SAFETENSORS):
        return Verdict(False, "image" if task is Task.IMAGE else "video", "gguf-diffusion",
                       "A diffusion transformer on its own. It needs the rest of its "
                       "pipeline — VAE, text encoder, scheduler — to generate anything.")

    if task is Task.SPEECH_TO_TEXT:
        if layout is Layout.CTRANSLATE2:
            return Verdict(True, "voice-stt", "faster-whisper", capabilities=["transcribe"])
        return Verdict(False, "voice-stt", "faster-whisper",
                       "Whisper in the transformers format. Uncloud transcribes with "
                       "faster-whisper, which loads CTranslate2 conversions (a model.bin), "
                       "so this one would fail when chosen.")

    if task is Task.TEXT_TO_SPEECH:
        if family == "vibevoice":
            return Verdict(True, "voice-tts", "vibevoice", capabilities=["speak"])
        return Verdict(False, "voice-tts", "unsupported",
                       f"Recognised as {family or 'a speech model'}, which Uncloud has no "
                       "engine for yet.")

    if task is Task.MUSIC and family == "ace-step":
        return Verdict(True, "music", "acestep", capabilities=["music"])

    if task is Task.ADAPTER:
        return Verdict(False, "component", "adapter",
                       "An adapter changes a base model when it loads. Apply it from a "
                       "recipe beside the checkpoint it was trained for.")

    return Verdict(False, "other", "unsupported",
                   "Uncloud could not work out what this is from its files.")


def local_model(i: Identification, v: Verdict):
    from .library import LocalModel

    return LocalModel(
        id=f"local:{i.path}", name=i.name, category=v.category, engine=v.engine,
        path=i.path, size_gb=i.size_bytes / (1024 ** 3), ready=v.runnable,
        note=v.note or None, capabilities=v.capabilities or None,
        mflux_cli=v.mflux_cli, mflux_base=v.mflux_base, tags=["imported"],
    )


def inspect(path: str) -> dict:
    """Identify, plan what is missing, and say whether it will run. Writes nothing."""
    i = identify(Path(path).expanduser())
    steps = plan(i)
    return {"identification": i.to_dict(), "plan": [s.to_dict() for s in steps],
            "verdict": verdict(i).to_dict(), "manifest": (Path(i.path) / MANIFEST).is_file()
            if not i.is_file else Path(i.path + "." + MANIFEST).is_file()}


def import_model(path: str, *, name: str, family: str = "", online: bool = False,
                 licence: str = "unknown", token: str | None = None) -> dict:
    """Write what is missing and the manifest; return the model as the library
    will now list it. The caller has already passed the approval gate."""
    i = identify(Path(path).expanduser())
    choices = {"family": family} if family else {}
    fetch = (lambda repo, file: hub.fetch_json(repo, file, token=token)) if online else None
    steps = plan(i, choices=choices, fetch=fetch)
    result = apply(i, steps, product="Uncloud", name=name or i.name, choices=choices,
                   licence=licence)
    after = identify(Path(i.path))
    v = verdict(after)
    return {"result": result, "plan": [s.to_dict() for s in steps],
            "identification": after.to_dict(), "verdict": v.to_dict(),
            "model": local_model(after, v).to_dict()}
