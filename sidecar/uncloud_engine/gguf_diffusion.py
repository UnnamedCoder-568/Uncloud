"""A loose diffusion transformer, run with parts borrowed from a pipeline you have.

What gets shared for a fine-tuned image model is usually a single file: the
transformer, quantised to GGUF by ComfyUI's converter. On its own it renders
nothing — no VAE to turn latents into pixels, no text encoder to read the
prompt, no scheduler to step it — which is why the Models tab greys such a file
out and says so.

But it is only unsupported while those parts are missing. When the models folder
already holds a complete pipeline of the same family — usually the official
release the fine-tune was cut from — the rest can be borrowed from it, which is
what this module does. `flux2_profile` does the same thing for a folder that
names its parts in a manifest; here nobody wrote one, so the family comes out of
the GGUF header and the donor is found by looking.

Two details of the format matter:

  * ComfyUI's converter flattens tensors that have a leading 1 dimension and
    records the real shape under a `comfy.gguf.orig_shape.*` metadata key.
    diffusers does not read those keys back, so the checkpoint arrives with a
    `cap_pad_token` of shape [3840] where the model wants [1, 3840] and the load
    fails on a shape mismatch. Restoring them is this module's one repair.
  * Quantised weights carry no architecture config, so it is taken from the
    donor's transformer folder. That is the same architecture by definition: a
    fine-tune that changed the shape of the model would not load anywhere else
    either.

Nothing here downloads anything or reaches past what is already on the disk. A
file with no donor beside it stays exactly as unsupported as it was.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# family (as Core's identifier names it) -> the diffusers pipeline and
# transformer classes that family loads as. A donor has to declare both: the
# pipeline in its model_index.json, the transformer in its own config. Every
# class listed here is one diffusers can load from a single file — that is what
# makes borrowing possible at all, and a family whose loader diffusers does not
# have would fail at load time rather than here.
_FAMILIES: dict[str, tuple[str, str]] = {
    "z-image": ("ZImagePipeline", "ZImageTransformer2DModel"),
    "lumina2": ("Lumina2Pipeline", "Lumina2Transformer2DModel"),
    "flux": ("FluxPipeline", "FluxTransformer2DModel"),
    "flux2": ("Flux2Pipeline", "Flux2Transformer2DModel"),
    "qwen-image": ("QwenImagePipeline", "QwenImageTransformer2DModel"),
    "chroma": ("ChromaPipeline", "ChromaTransformer2DModel"),
    "hidream": ("HiDreamImagePipeline", "HiDreamImageTransformer2DModel"),
    "auraflow": ("AuraFlowPipeline", "AuraFlowTransformer2DModel"),
}

# Folders that are never a model root, and are expensive to walk into.
_SKIP_DIRS = {"blobs", "manifests", "downloads", ".cache", "snapshots"}

# How deep to look for a donor. Models live at the top of the folder or one or
# two levels down ("Image Models/z-image-turbo-bf16"); deeper than that is
# somebody else's cache.
_MAX_DEPTH = 4

# What a pipeline needs on disk before it can lend anything.
_BORROWED = ("scheduler", "text_encoder", "tokenizer", "vae")


@dataclass
class Assembly:
    """A loose transformer and the pipeline that can complete it."""

    transformer: Path
    family: str
    pipeline_class: str | None = None
    transformer_class: str | None = None
    base: Path | None = None

    @property
    def ready(self) -> bool:
        return self.base is not None and self.pipeline_class is not None

    def note(self) -> str:
        if self.ready:
            assert self.base is not None
            return (
                f"Assembled at load time: this file as the diffusion transformer, "
                f"with the VAE, text encoder, tokenizer and scheduler borrowed "
                f"from “{self.base.name}”."
            )
        if self.pipeline_class is None:
            return (
                "A diffusion transformer on its own. It needs the rest of its "
                "pipeline — VAE, text encoder, scheduler — and Uncloud does not "
                f"know which pipeline the {self.family or 'unrecognised'} family "
                "assembles into."
            )
        return (
            "A diffusion transformer on its own. Download the full "
            f"{self.family} pipeline into the same models folder and this file "
            "will borrow its VAE, text encoder, tokenizer and scheduler."
        )


# ------------------------------------------------------------------ donors

def _reads_as(path: Path, want: str) -> bool:
    """Whether a JSON config declares the class we are looking for."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("_class_name") == want


def _lends_everything(folder: Path) -> bool:
    return all((folder / part).is_dir() for part in _BORROWED)


def find_base(models_dir: Path, pipeline_class: str, transformer_class: str) -> Path | None:
    """A complete pipeline of this family, anywhere in the models folder.

    Sorted, so the same file always assembles against the same donor: which
    pipeline lent the VAE changes the picture, and an answer that moved when a
    directory listing changed order would be impossible to explain.
    """
    found: list[Path] = []
    stack: list[tuple[Path, int]] = [(models_dir, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            children = sorted(current.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.name.startswith(".") or child.name in _SKIP_DIRS:
                continue
            index = child / "model_index.json"
            if index.is_file():
                if (_reads_as(index, pipeline_class)
                        and _lends_everything(child)
                        and _reads_as(child / "transformer" / "config.json", transformer_class)):
                    found.append(child)
                continue  # a model root: its subfolders are components
            if depth + 1 < _MAX_DEPTH:
                stack.append((child, depth + 1))
    return sorted(found)[0] if found else None


def assembly_for(path: Path, family: str, models_dir: Path) -> Assembly:
    """What it would take to run this file, and whether that is possible here."""
    classes = _FAMILIES.get(family)
    if classes is None:
        return Assembly(transformer=path, family=family)
    pipeline_class, transformer_class = classes
    return Assembly(
        transformer=path, family=family,
        pipeline_class=pipeline_class, transformer_class=transformer_class,
        base=find_base(models_dir, pipeline_class, transformer_class),
    )


# ------------------------------------------------------------------ loading

def _restore_comfy_shapes(state: dict[str, Any], path: Path) -> None:
    """Undo ComfyUI's flattening of tensors with a leading 1 dimension.

    Its converter stores `x_pad_token` of shape [1, 3840] as [3840] and writes
    the original shape into the file's metadata. Without this the load stops at
    the first such tensor with a shape mismatch, which reads as a corrupt file
    and is nothing of the kind.
    """
    import gguf

    prefix = "comfy.gguf.orig_shape."
    reader = gguf.GGUFReader(str(path))
    for key, field in reader.fields.items():
        if not key.startswith(prefix):
            continue
        name = key[len(prefix):]
        tensor = state.get(name)
        if tensor is None:
            continue
        shape = tuple(int(field.parts[i][0]) for i in field.data)
        if tuple(tensor.shape) != shape:
            state[name] = tensor.reshape(shape)


def load_pipeline(path: str | Path, models_dir: Path, family: str, *, dtype: Any = None):
    """The pipeline this file runs in, with its missing parts borrowed.

    Raises with the reason if there is nothing on the disk to borrow from — the
    Models tab says the same thing before anyone gets this far, but a model can
    be picked and the donor moved afterwards.
    """
    import torch
    from diffusers import GGUFQuantizationConfig
    from diffusers.models.model_loading_utils import load_gguf_checkpoint

    path = Path(path)
    dtype = dtype or torch.bfloat16
    assembly = assembly_for(path, family, models_dir)
    if not assembly.ready:
        raise RuntimeError(assembly.note())
    assert assembly.base is not None and assembly.transformer_class is not None

    import diffusers

    transformer_cls = getattr(diffusers, assembly.transformer_class)
    pipeline_cls = getattr(diffusers, assembly.pipeline_class or "")

    state = load_gguf_checkpoint(str(path))
    _restore_comfy_shapes(state, path)
    transformer = transformer_cls.from_single_file(
        state,
        config=str(assembly.base / "transformer"),
        quantization_config=GGUFQuantizationConfig(compute_dtype=dtype),
        torch_dtype=dtype,
    )
    return pipeline_cls.from_pretrained(
        str(assembly.base), transformer=transformer, torch_dtype=dtype,
    )
