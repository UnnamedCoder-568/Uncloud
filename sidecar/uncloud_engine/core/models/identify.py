"""What a model on disk is, decided by what is inside it.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Every conclusion here carries the evidence it was drawn from and one of three
levels of confidence, and the difference between them is the whole point:

* CERTAIN — the files declare it. A diffusers `model_index.json` naming its
  pipeline class, a GGUF header naming its architecture.
* INFERRED — the structure implies it. A transformer config whose class only
  one pipeline accepts; tensor names only one architecture uses.
* GUESSED — only a filename suggests it. Reported as a guess, never promoted.

Identification is not compatibility. This module says what a model IS. Whether
a given application can run it is that application's question, answered
separately, and a model that is recognised but not runnable must be shown as
exactly that — not listed as ready and left to fail on first use.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from .headers import front_matter, read_gguf, read_json, read_safetensors, tensor_names

#: The app's own description of a model, written on import. Shared by both
#: products, so a model added in one is recognised by the other.
MANIFEST = "uncloud-model.json"

#: Older per-product markers, still honoured.
LEGACY_MARKERS = ("uncloud-mlx.json", "adstudio-mlx.json", "uncloud-video.json")


class Task(StrEnum):
    TEXT = "text-generation"
    IMAGE = "image-generation"
    VIDEO = "video-generation"
    TEXT_ENCODER = "text-encoder"
    SPEECH_TO_TEXT = "speech-to-text"
    TEXT_TO_SPEECH = "text-to-speech"
    MUSIC = "music-generation"
    COMPONENT = "pipeline-component"
    ADAPTER = "adapter"
    UNKNOWN = "unknown"


class Layout(StrEnum):
    DIFFUSERS = "diffusers-pipeline"
    DIFFUSERS_PARTS = "diffusers-components"      # the parts, no model_index.json
    MFLUX = "mflux-checkpoint"
    MLX = "mlx-weights"
    TRANSFORMERS = "transformers"
    CTRANSLATE2 = "ctranslate2"
    GGUF = "gguf"
    SAFETENSORS = "single-safetensors"
    BUNDLE = "bundle"                             # several models shipped together
    UNKNOWN = "unknown"


class Confidence(StrEnum):
    CERTAIN = "certain"
    INFERRED = "inferred"
    GUESSED = "guessed"
    UNKNOWN = "unknown"


@dataclass
class Evidence:
    source: str
    finding: str


@dataclass
class Need:
    """A metadata file this model needs and does not have."""

    file: str
    why: str
    #: Buildable from what is already on disk, with no guessing.
    derivable: bool = False


@dataclass
class Identification:
    path: str
    is_file: bool
    layout: Layout = Layout.UNKNOWN
    task: Task = Task.UNKNOWN
    family: str = ""
    architecture: str = ""
    pipeline: str = ""
    quantization: str = ""
    confidence: Confidence = Confidence.UNKNOWN
    name: str = ""
    base_repo: str = ""
    #: What a model card SAYS the licence is. A claim to show a person, never a
    #: verified licence — nothing here treats it as one.
    licence_claim: str = ""
    size_bytes: int = 0
    evidence: list[Evidence] = field(default_factory=list)
    needs: list[Need] = field(default_factory=list)
    #: Other families it could be, when the files do not settle it.
    candidates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: The fields a person set on import, which win where content cannot decide.
    declared: dict[str, str] = field(default_factory=dict)
    #: For a folder that holds models rather than being one: what is inside.
    contents: list[dict[str, str]] = field(default_factory=list)

    def saw(self, source: str, finding: str) -> None:
        self.evidence.append(Evidence(source, finding))

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in ("layout", "task", "confidence"):
            data[key] = str(data[key])
        return data


# ------------------------------------------------------------------ tables
#
# Pipeline classes, matched by LONGEST prefix, so "Flux2Klein" wins over "Flux2"
# and "WanImageToVideo" over "Wan". Checked against diffusers itself in the
# tests wherever diffusers is installed.

_PIPELINE_FAMILIES: dict[str, tuple[str, Task]] = {
    "ZImage": ("z-image", Task.IMAGE),
    "Flux2Klein": ("flux2-klein", Task.IMAGE),
    "Flux2": ("flux2", Task.IMAGE),
    "FluxKontext": ("flux-kontext", Task.IMAGE),
    "Flux": ("flux", Task.IMAGE),
    "QwenImageEdit": ("qwen-image-edit", Task.IMAGE),
    "QwenImage": ("qwen-image", Task.IMAGE),
    "LTX2": ("ltx-2", Task.VIDEO),
    "LTX": ("ltx-video", Task.VIDEO),
    "WanVACE": ("wan-vace", Task.VIDEO),
    "WanSpeechToVideo": ("wan-s2v", Task.VIDEO),
    "WanImageToVideo": ("wan-i2v", Task.VIDEO),
    "Wan": ("wan", Task.VIDEO),
    "HunyuanVideo15": ("hunyuan-video-1.5", Task.VIDEO),
    "HunyuanVideo": ("hunyuan-video", Task.VIDEO),
    "CogVideoX": ("cogvideox", Task.VIDEO),
    "StableDiffusion3": ("sd3", Task.IMAGE),
    "StableDiffusionXL": ("sdxl", Task.IMAGE),
    "StableDiffusion": ("sd1", Task.IMAGE),
    "Lumina2": ("lumina2", Task.IMAGE),
    "Chroma": ("chroma", Task.IMAGE),
    "HiDreamImage": ("hidream", Task.IMAGE),
}

#: Transformer class -> the pipeline that generates from it, for folders that
#: arrive without a model_index.json. Only the base text-to-output pipeline.
TRANSFORMER_PIPELINES: dict[str, str] = {
    "ZImageTransformer2DModel": "ZImagePipeline",
    "Flux2Transformer2DModel": "Flux2Pipeline",
    "FluxTransformer2DModel": "FluxPipeline",
    "QwenImageTransformer2DModel": "QwenImagePipeline",
    "LTXVideoTransformer3DModel": "LTXPipeline",
    "LTX2VideoTransformer3DModel": "LTX2Pipeline",
    "WanTransformer3DModel": "WanPipeline",
    "WanVACETransformer3DModel": "WanVACEPipeline",
    "HunyuanVideoTransformer3DModel": "HunyuanVideoPipeline",
    "HunyuanVideo15Transformer3DModel": "HunyuanVideo15Pipeline",
    "CogVideoXTransformer3DModel": "CogVideoXPipeline",
    "SD3Transformer2DModel": "StableDiffusion3Pipeline",
    "Lumina2Transformer2DModel": "Lumina2Pipeline",
    "ChromaTransformer2DModel": "ChromaPipeline",
    "HiDreamImageTransformer2DModel": "HiDreamImagePipeline",
}

_LM_ARCHS = ("qwen", "llama", "mistral", "gemma", "phi", "granite", "deepseek", "command",
             "olmo", "glm", "exaone", "falcon", "starcoder", "internlm", "baichuan", "yi",
             "minicpm", "smollm", "nemotron", "mamba", "rwkv", "jamba", "ernie", "hunyuan-dense")

_GGUF_DIFFUSION: dict[str, tuple[str, Task, tuple[str, ...]]] = {
    # arch -> (family, task, other families it is also used for)
    "flux": ("flux", Task.IMAGE, ("flux2",)),
    "flux2": ("flux2", Task.IMAGE, ()),
    "lumina2": ("lumina2", Task.IMAGE, ("z-image",)),
    "wan": ("wan", Task.VIDEO, ()),
    "ltxv": ("ltx-video", Task.VIDEO, ()),
    "hyvid": ("hunyuan-video", Task.VIDEO, ()),
    "hunyuan-video": ("hunyuan-video", Task.VIDEO, ()),
    "qwen_image": ("qwen-image", Task.IMAGE, ()),
    "cosmos": ("cosmos", Task.VIDEO, ()),
    "chroma": ("chroma", Task.IMAGE, ()),
    "hidream": ("hidream", Task.IMAGE, ()),
    "aura": ("auraflow", Task.IMAGE, ()),
    "sd1": ("sd1", Task.IMAGE, ()),
    "sdxl": ("sdxl", Task.IMAGE, ()),
    "sd3": ("sd3", Task.IMAGE, ()),
}

_GGUF_ENCODERS = ("t5", "t5encoder", "umt5", "clip")

#: llama.cpp's general.file_type values. Only the common ones; anything else is
#: reported as its number rather than invented.
_GGUF_FILE_TYPES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1",
    10: "Q2_K", 11: "Q3_K_S", 12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M",
    16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K", 32: "BF16",
}

#: Words in a filename that suggest a family. Used only when nothing inside the
#: files could decide, and always labelled a guess.
_NAME_HINTS: tuple[tuple[str, str, Task], ...] = (
    ("z-image", "z-image", Task.IMAGE), ("z_image", "z-image", Task.IMAGE),
    ("klein", "flux2-klein", Task.IMAGE), ("flux", "flux", Task.IMAGE),
    ("krea", "krea2", Task.IMAGE), ("sdxl", "sdxl", Task.IMAGE),
    ("wan2", "wan", Task.VIDEO), ("ltx", "ltx-video", Task.VIDEO),
    ("hunyuan", "hunyuan-video", Task.VIDEO), ("whisper", "whisper", Task.SPEECH_TO_TEXT),
    ("kokoro", "kokoro", Task.TEXT_TO_SPEECH), ("vibevoice", "vibevoice", Task.TEXT_TO_SPEECH),
    ("chatterbox", "chatterbox", Task.TEXT_TO_SPEECH), ("ace-step", "ace-step", Task.MUSIC),
)

_COMPONENT_DIRS = ("transformer", "unet", "vae", "text_encoder", "text_encoder_2",
                   "tokenizer", "tokenizer_2", "scheduler")


def _pipeline_family(pipeline: str) -> tuple[str, Task] | None:
    best = None
    for prefix, value in _PIPELINE_FAMILIES.items():
        if pipeline.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, value)
    return best[1] if best else None


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _has_weights(folder: Path) -> bool:
    return any(folder.glob("*.safetensors")) or any(folder.glob("*.bin")) \
        or any(folder.glob("*.gguf"))


def _readme(identification: Identification, folder: Path) -> None:
    card = front_matter(folder / "README.md")
    if not card:
        return
    if card.get("base_model") and not identification.base_repo:
        identification.base_repo = card["base_model"].split(",")[0].strip()
        identification.saw("README.md", f"model card names base_model {identification.base_repo}")
    if card.get("license"):
        identification.licence_claim = card["license"]
        identification.saw("README.md",
                           f"model card says license: {card['license']} (a claim, not verified)")


def _guess_from_name(identification: Identification, name: str) -> None:
    lowered = name.lower()
    for needle, family, task in _NAME_HINTS:
        if needle in lowered:
            identification.family = identification.family or family
            if identification.task is Task.UNKNOWN:
                identification.task = task
            identification.confidence = Confidence.GUESSED
            identification.saw("filename", f"the name contains '{needle}' — a guess only")
            return


# ------------------------------------------------------------------ files

def _gguf(identification: Identification, path: Path) -> None:
    identification.layout = Layout.GGUF
    header = read_gguf(path)
    if header is None:
        identification.warnings.append("The GGUF header could not be read.")
        _guess_from_name(identification, path.name)
        return

    arch = header.architecture
    identification.architecture = arch
    identification.name = header.name or path.stem
    identification.saw("GGUF header", f"general.architecture = {arch or '(absent)'}")
    if header.name:
        identification.saw("GGUF header", f"general.name = {header.name}")
    file_type = header.fields.get("general.file_type")
    if isinstance(file_type, int):
        identification.quantization = _GGUF_FILE_TYPES.get(file_type, f"file type {file_type}")
    for key in ("general.base_model.0.repo_url", "general.basename"):
        if header.fields.get(key) and not identification.base_repo and "repo_url" in key:
            url = str(header.fields[key])
            identification.base_repo = (url.split("huggingface.co/")[-1]
                                        if "huggingface.co/" in url else "")
    if header.fields.get("general.license"):
        identification.licence_claim = str(header.fields["general.license"])

    lowered_name = header.name.lower()
    if arch in _GGUF_DIFFUSION:
        family, task, others = _GGUF_DIFFUSION[arch]
        identification.family, identification.task = family, task
        identification.confidence = Confidence.INFERRED
        identification.candidates = list(others)
        # A lumina2 header is shared by Lumina-Image-2 and Z-Image; the filename
        # can break the tie, but only as a guess on top of the certain part.
        if others:
            for other in others:
                if other.replace("-", "") in path.name.lower().replace("-", "").replace("_", ""):
                    identification.family = other
                    identification.candidates = [family]
                    identification.saw("filename", f"the name suggests {other} among "
                                                   f"the {arch} family — a guess")
        identification.needs.append(Need(
            file="(pipeline)",
            why=("A quantised diffusion transformer on its own. It generates nothing "
                 "without the matching VAE, text encoder, tokenizer and scheduler from "
                 "the full pipeline beside it.")))
        return
    if arch.startswith(_GGUF_ENCODERS) or "text encoder" in lowered_name \
            or "text_encoder" in lowered_name:
        identification.task = Task.TEXT_ENCODER
        identification.family = arch
        identification.confidence = Confidence.CERTAIN if arch.startswith(_GGUF_ENCODERS) \
            else Confidence.INFERRED
        identification.saw("GGUF header", "a text encoder: a pipeline component, not a "
                                          "model to load on its own")
        return
    if arch.startswith(_LM_ARCHS):
        identification.task = Task.TEXT
        identification.family = arch
        identification.confidence = Confidence.CERTAIN
        return
    identification.warnings.append(
        f"The header names architecture '{arch}', which is not one Uncloud knows.")
    _guess_from_name(identification, path.name)


def _safetensors_file(identification: Identification, path: Path) -> None:
    identification.layout = Layout.SAFETENSORS
    identification.name = path.stem
    header = read_safetensors(path)
    if header is None:
        identification.warnings.append("The safetensors header could not be read.")
        _guess_from_name(identification, path.name)
        return
    keys = list(header.shapes)
    identification.saw("safetensors header", f"{len(keys)} tensors")
    spec = header.metadata.get("modelspec.architecture", "")
    if spec:
        identification.saw("safetensors metadata", f"modelspec.architecture = {spec}")

    def any_key(*needles: str) -> bool:
        return any(all(n in k for n in needles) for k in keys)

    found: tuple[str, Task, str] | None = None
    adapter_marks = ("lora_", ".lora.", "lokr_", "loha_", "hada_w", "dora_scale", "lora_A",
                     "lora_B", "lora_up", "lora_down")
    trained_adapter = any(k.startswith(("ss_network", "ss_base_model")) for k in header.metadata)
    if trained_adapter or any(any_key(mark) for mark in adapter_marks):
        target = ("flux" if any_key("double_blocks.") else
                  "wan" if any_key("blocks.0.self_attn") else
                  "sdxl" if any_key("label_emb") or any_key("input_blocks") else "")
        kinds = [m.rstrip("_.") for m in ("lokr_", "loha_", "lora_") if any_key(m)]
        found = (target, Task.ADAPTER,
                 f"adapter weights ({', '.join(kinds) or 'LoRA'})"
                 + (f" for a {target}-family model" if target else ""))
        if header.metadata.get("ss_base_model_version"):
            identification.saw("safetensors metadata",
                               "ss_base_model_version = "
                               f"{header.metadata['ss_base_model_version']}")
    elif any_key("double_blocks.") and any_key("single_blocks."):
        found = ("flux", Task.IMAGE, "double_blocks and single_blocks, the Flux layout")
    elif any_key("model.diffusion_model.input_blocks"):
        family = "sdxl" if any_key("label_emb") else "sd1"
        found = (family, Task.IMAGE, "a Stable Diffusion UNet under model.diffusion_model")
    elif any_key("patch_embedding") and any_key("blocks.0.self_attn"):
        found = ("wan", Task.VIDEO, "patch_embedding with blocks.N.self_attn, the Wan layout")
    elif any_key("cap_embedder") and any_key("layers.0"):
        found = ("lumina2", Task.IMAGE, "cap_embedder with layers.N, the Lumina 2 layout")
    elif any_key("adaln_single") and any_key("caption_projection"):
        found = ("ltx-video", Task.VIDEO, "adaln_single with caption_projection")
        identification.candidates = ["pixart"]
    elif any_key("decoder.up_blocks") and any_key("encoder.down_blocks"):
        found = ("vae", Task.COMPONENT, "an encoder and decoder: a VAE")
    elif any_key("encoder.block.0.layer.0.SelfAttention"):
        found = ("t5", Task.TEXT_ENCODER, "a T5 encoder stack")
    elif any_key("model.layers.0.self_attn.q_proj") or any_key("layers.0.attention.wq"):
        found = ("", Task.TEXT, "a decoder-only language model's attention layers")
    if found:
        identification.family, identification.task, reason = found
        identification.confidence = Confidence.INFERRED
        identification.saw("tensor names", reason)
        if identification.task is Task.ADAPTER:
            identification.warnings.append(
                "An adapter, not a model: it changes a base model at load time and "
                "generates nothing on its own.")
        elif identification.task in (Task.IMAGE, Task.VIDEO):
            identification.warnings.append(
                "A single-file checkpoint. Loading it needs the rest of its pipeline "
                "(text encoder, VAE, scheduler) or a runtime that can assemble one.")
        return
    _guess_from_name(identification, path.name)


# ----------------------------------------------------------------- folders

def _diffusers(identification: Identification, folder: Path, index: dict) -> None:
    identification.layout = Layout.DIFFUSERS
    pipeline = str(index.get("_class_name") or "")
    identification.pipeline = pipeline
    identification.saw("model_index.json", f"_class_name = {pipeline}")
    family = _pipeline_family(pipeline)
    if family:
        identification.family, identification.task = family
        identification.confidence = Confidence.CERTAIN
    else:
        identification.warnings.append(f"{pipeline} is not a pipeline Uncloud knows.")
    if pipeline.startswith("Flux2") and not pipeline.startswith("Flux2Klein"):
        _refine_flux2(identification, folder)

    for component, spec in index.items():
        if component.startswith("_") or not isinstance(spec, list) or spec[0] is None:
            continue
        part = folder / component
        if not part.is_dir():
            identification.needs.append(Need(
                file=f"{component}/", why=f"model_index.json lists {component} "
                                          f"({spec[1]}), and the folder is missing."))
            continue
        if component in ("transformer", "unet", "vae", "text_encoder", "text_encoder_2") \
                and not _has_weights(part):
            identification.warnings.append(
                f"{component}/ has no weights of its own"
                + (" — they appear to be the GGUF files at the top level."
                   if any(folder.glob("*.gguf")) else "."))
        if component == "scheduler" and not (part / "scheduler_config.json").is_file():
            identification.needs.append(Need(
                file="scheduler/scheduler_config.json",
                why="The scheduler folder has no configuration."))


def _refine_flux2(identification: Identification, folder: Path) -> None:
    """Flux 2 dev and Klein share a transformer class; the text encoder differs."""
    config = read_json(folder / "text_encoder" / "config.json") or {}
    architectures = " ".join(config.get("architectures") or [])
    if "Qwen3" in architectures:
        identification.pipeline = "Flux2KleinPipeline"
        identification.family = "flux2-klein"
        identification.saw("text_encoder/config.json",
                           f"{architectures}: Klein's encoder, so Flux2KleinPipeline")
    elif architectures:
        identification.saw("text_encoder/config.json", f"{architectures}")


def _diffusers_parts(identification: Identification, folder: Path) -> bool:
    transformer = read_json(folder / "transformer" / "config.json") \
        or read_json(folder / "unet" / "config.json")
    if not transformer:
        return False
    cls = str(transformer.get("_class_name") or "")
    if not cls:
        return False
    identification.layout = Layout.DIFFUSERS_PARTS
    identification.saw("transformer/config.json", f"_class_name = {cls}")
    if cls == "UNet2DConditionModel":
        pipeline = ("StableDiffusionXLPipeline" if (folder / "text_encoder_2").is_dir()
                    else "StableDiffusionPipeline")
    else:
        pipeline = TRANSFORMER_PIPELINES.get(cls, "")
    if not pipeline:
        identification.warnings.append(f"No known pipeline generates from {cls}.")
        return True
    identification.pipeline = pipeline
    family = _pipeline_family(pipeline)
    if family:
        identification.family, identification.task = family
    identification.confidence = Confidence.INFERRED
    identification.saw("pipeline table", f"{cls} is generated by {pipeline}")
    if pipeline == "Flux2Pipeline":
        _refine_flux2(identification, folder)
    identification.needs.append(Need(
        file="model_index.json",
        why="The components are here but nothing says how they assemble into a "
            "pipeline, so a loader cannot open the folder.",
        derivable=True))
    return True


#: mflux base models told apart by their own tensors. Checked on real
#: checkpoints of each: FLUX.2 Klein 4B has 5 double-stream and 20 single-stream
#: blocks at width 3072, 9B has 8 and 24 at 4096; Krea 2 has a different layout
#: altogether. A checkpoint matching none of these is left for a person to name.
def _mflux_base(weight_names: list[str]) -> tuple[str, str] | None:
    prefixes = {n.split(".")[0] for n in weight_names}

    def blocks(prefix: str) -> int:
        return len({n.split(".")[1] for n in weight_names
                    if n.startswith(prefix + ".") and n.split(".")[1].isdigit()})

    if "double_stream_modulation_img" in prefixes and "single_transformer_blocks" in prefixes:
        double, single = blocks("transformer_blocks"), blocks("single_transformer_blocks")
        if (double, single) == (5, 20):
            return "flux2_klein_4b", "5 double-stream and 20 single-stream blocks: FLUX.2 Klein 4B"
        if (double, single) == (8, 24):
            return "flux2_klein_9b", "8 double-stream and 24 single-stream blocks: FLUX.2 Klein 9B"
        return None
    if {"txtfusion", "tproj", "blocks"} <= prefixes:
        return "krea2", "txtfusion, tproj and blocks.N: the Krea 2 layout"
    return None


def _measured_bits(folder: Path, index: dict) -> int | None:
    """Quantisation read off a packed weight, not taken from a label.

    MLX packs n-bit values into uint32 columns, so a square projection of width
    W stored at b bits has W*b/32 columns. The first attention query projection
    is square in every layout checked here.
    """
    weight_map = index.get("weight_map") or {}
    name = next((n for n in weight_map if n.endswith("attn.to_q.weight")), None)
    if name is None:
        return None
    header = read_safetensors(folder / weight_map[name])
    shape = header.shapes.get(name) if header else None
    if not shape or len(shape) != 2 or shape[0] == 0:
        return None
    bits = shape[1] * 32 / shape[0]
    return int(bits) if bits == int(bits) and 2 <= bits <= 8 else None


def _mflux(identification: Identification, folder: Path) -> bool:
    marker_path = next((folder / m for m in ("uncloud-mlx.json", "adstudio-mlx.json")
                        if (folder / m).is_file()), None)
    marker = read_json(marker_path) if marker_path else None
    weights_folder = folder
    if marker and marker.get("checkpoint"):
        # A recipe: a name, a base and some adapters, pointing at weights that
        # live elsewhere so a fine-tune costs a kilobyte instead of a copy.
        target = (folder / str(marker["checkpoint"])).resolve()
        identification.saw(marker_path.name, f"a recipe pointing at {target.name}")
        if not target.is_dir():
            identification.warnings.append(f"The checkpoint it points at ({target}) is missing.")
            return False
        weights_folder = target
        for lora in marker.get("lora_paths") or []:
            exists = (folder / lora).resolve().is_file()
            identification.saw(marker_path.name, f"applies adapter {Path(lora).name}"
                                                 + ("" if exists else " — MISSING"))

    for base in (weights_folder / "transformer", weights_folder):
        index = read_json(base / "model.safetensors.index.json")
        if index is None or not (weights_folder / "vae").is_dir():
            continue
        meta = index.get("metadata") or {}
        if "mflux_version" not in meta and "quantization_level" not in meta:
            continue
        identification.layout = Layout.MFLUX
        identification.task = Task.IMAGE
        identification.saw("transformer shard index",
                           f"mflux_version = {meta.get('mflux_version', '?')}, "
                           f"quantization_level = {meta.get('quantization_level', 'none')}")
        recorded = meta.get("quantization_level")
        measured = _measured_bits(base, index)
        if measured is not None:
            identification.quantization = f"{measured}bit"
            identification.saw("packed weight shape",
                               f"attention weights are stored at {measured} bits")
            if recorded and str(measured) != str(recorded):
                identification.warnings.append(
                    f"The shard index records {recorded}-bit, but the weights are packed "
                    f"at {measured} bits.")
        elif recorded:
            identification.quantization = f"{recorded}bit"
        for label in ("5-bit", "5bit", "6-bit", "6bit", "8-bit", "8bit", "4-bit", "4bit"):
            if label in folder.name.lower() and identification.quantization \
                    and not identification.quantization.startswith(label[0]):
                identification.warnings.append(
                    f"The folder name says {label}; the weights are {identification.quantization}.")
                break

        derived = _mflux_base(sorted(index.get("weight_map") or {}))
        if marker and marker.get("base_model"):
            identification.family = str(marker["base_model"])
            identification.confidence = Confidence.CERTAIN
            identification.saw(marker_path.name, f"base_model = {marker['base_model']}")
            if derived and derived[0] != identification.family:
                identification.warnings.append(
                    f"The marker says {identification.family}, but the tensors are "
                    f"{derived[0]} ({derived[1]}).")
        elif derived:
            identification.family = derived[0]
            identification.confidence = Confidence.INFERRED
            identification.saw("tensor names", derived[1])
            identification.needs.append(Need(
                file="uncloud-mlx.json",
                why="mflux needs to be told the base model. It is recorded nowhere in "
                    "the checkpoint, but its tensors identify it.",
                derivable=True))
        else:
            identification.confidence = Confidence.INFERRED
            identification.candidates = ["flux2_klein_4b", "flux2_klein_9b", "z_image_turbo",
                                         "krea2"]
            identification.needs.append(Need(
                file="uncloud-mlx.json",
                why="mflux needs to be told the base model, and neither the checkpoint "
                    "nor its tensors settle which one. It has to be chosen."))
        return True
    return False


def _config_model(identification: Identification, folder: Path, config: dict) -> bool:
    model_type = str(config.get("model_type") or "")
    architectures = [str(a) for a in config.get("architectures") or []]
    joined = " ".join(architectures)
    if not model_type and not architectures:
        return False
    identification.architecture = model_type or joined
    identification.saw("config.json", f"model_type = {model_type or '(absent)'}; "
                                      f"architectures = {joined or '(absent)'}")
    name_or_path = str(config.get("_name_or_path") or "")
    if "/" in name_or_path and not identification.base_repo:
        identification.base_repo = name_or_path
    names = tensor_names(folder)
    quantized_mlx = "quantization" in config or any(n.endswith(".scales") for n in names[:4000])
    has_ct2 = (folder / "model.bin").is_file() and not any(folder.glob("*.safetensors"))
    identification.layout = (Layout.CTRANSLATE2 if has_ct2
                             else Layout.MLX if quantized_mlx else Layout.TRANSFORMERS)
    if quantized_mlx:
        q = config.get("quantization") or {}
        if isinstance(q, dict) and q.get("bits"):
            identification.quantization = f"{q['bits']}bit"
        identification.saw("weights", "quantised MLX tensors (.scales/.biases)")

    if model_type == "whisper" or "Whisper" in joined:
        identification.task, identification.family = Task.SPEECH_TO_TEXT, "whisper"
    elif model_type == "vibevoice" or "VibeVoice" in joined:
        identification.task, identification.family = Task.TEXT_TO_SPEECH, "vibevoice"
    elif model_type == "bark" or "BarkModel" in joined:
        identification.task, identification.family = Task.TEXT_TO_SPEECH, "bark"
    elif model_type == "acestep" or "AceStep" in joined:
        identification.task, identification.family = Task.MUSIC, "ace-step"
        identification.layout = Layout.BUNDLE
    elif model_type in ("t5", "umt5") or "EncoderModel" in joined:
        identification.task, identification.family = Task.TEXT_ENCODER, model_type or joined
    elif "CausalLM" in joined or "ForConditionalGeneration" in joined:
        identification.task, identification.family = Task.TEXT, model_type
    else:
        identification.family = model_type
        identification.confidence = Confidence.INFERRED
        identification.warnings.append(f"A {model_type or joined} model, whose task "
                                       "could not be read from its configuration.")
        return True
    identification.confidence = Confidence.CERTAIN
    for tokenizer in ("tokenizer.json", "tokenizer_config.json"):
        if identification.task in (Task.TEXT, Task.TEXT_ENCODER) \
                and identification.layout is not Layout.CTRANSLATE2 \
                and not (folder / tokenizer).is_file() \
                and not (folder / "tokenizer" / tokenizer).is_file():
            identification.needs.append(Need(
                file=tokenizer, why="A language model without its tokenizer cannot read "
                                    "a prompt."))
    return True


def _bundle(identification: Identification, folder: Path) -> bool:
    from ..speech.engines import recognise as recognise_speech

    # English, multilingual V2 or V3, or the converter alone: each is a
    # different set of files, and a multilingual-only download has no t3_cfg.
    speech = recognise_speech(folder)
    files = {p.name for p in folder.iterdir() if p.is_file()}
    partial = {"t3_cfg.safetensors", "s3gen.safetensors", "ve.safetensors"} <= files
    if (speech is not None and speech.engine == "chatterbox") or partial:
        identification.layout = Layout.BUNDLE
        identification.task, identification.family = Task.TEXT_TO_SPEECH, "chatterbox"
        identification.confidence = Confidence.INFERRED
        found = ", ".join(v.label for v in speech.variants) if speech else ""
        identification.saw("files", f"Chatterbox weights: {found}" if found else
                           "t3, s3gen and ve weights together: the Chatterbox set")
        return True
    subfolders = [p for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if any(p.name.startswith("acestep") for p in subfolders):
        identification.layout = Layout.BUNDLE
        identification.task, identification.family = Task.MUSIC, "ace-step"
        identification.confidence = Confidence.INFERRED
        identification.saw("folders", "acestep-* model folders: the ACE-Step set")
        return True
    return False


_WEIGHT_SUFFIXES = (".gguf", ".safetensors", ".bin", ".pt", ".pth", ".ckpt")


def _weights_within(folder: Path, depth: int = 2) -> bool:
    for pattern in ("*", "*/*")[:depth]:
        if any(p.suffix.lower() in _WEIGHT_SUFFIXES for p in folder.glob(pattern)):
            return True
    return False


def _single_file_folder(identification: Identification, folder: Path) -> bool:
    """A folder that exists to hold one weights file, as GGUF downloads do."""
    weights = [p for p in folder.iterdir()
               if p.is_file() and p.suffix.lower() in (".gguf", ".safetensors")]
    if len(weights) != 1 or any(p.is_dir() and not p.name.startswith(".")
                                for p in folder.iterdir()):
        return False
    inner = identify(weights[0], sizes=False)
    if inner.layout is Layout.UNKNOWN:
        return False
    for key in ("layout", "task", "family", "architecture", "quantization", "confidence",
                "base_repo", "candidates", "needs", "warnings"):
        setattr(identification, key, getattr(inner, key))
    identification.evidence = [Evidence("folder", f"holds one weights file, {weights[0].name}"),
                               *inner.evidence]
    identification.name = inner.name or folder.name
    identification.path = str(weights[0])
    identification.is_file = True
    return True


def _container(identification: Identification, folder: Path) -> bool:
    """A folder of models rather than a model: say what is in it."""
    found: list[dict[str, str]] = []
    for child in sorted(folder.iterdir()):
        if child.name.startswith("."):
            continue
        if child.is_file() and child.suffix.lower() not in (".gguf", ".safetensors"):
            continue
        inner = identify(child, sizes=False)
        if inner.layout is Layout.UNKNOWN or inner.confidence is Confidence.UNKNOWN:
            continue
        found.append({"path": inner.path, "name": inner.name, "task": str(inner.task),
                      "family": inner.family})
    if not found:
        return False
    identification.contents = found
    identification.saw("folder", f"holds {len(found)} model{'s' if len(found) != 1 else ''} "
                                 "rather than being one")
    if len(found) > 1:
        identification.warnings.append(
            "This folder holds several models. Choose the one to add.")
    return True


def identify(path: Path, *, sizes: bool = True) -> Identification:
    """What `path` is. Reads headers and configs only; never loads weights."""
    path = Path(path)
    identification = Identification(path=str(path), is_file=path.is_file(),
                                    name=path.stem if path.is_file() else path.name)
    if not path.exists():
        identification.warnings.append("Nothing exists at this path.")
        return identification
    if sizes:
        identification.size_bytes = _size(path)

    if path.is_file():
        if path.suffix.lower() == ".gguf":
            _gguf(identification, path)
        elif path.suffix.lower() == ".safetensors":
            _safetensors_file(identification, path)
        else:
            identification.warnings.append(
                f"A {path.suffix or 'extensionless'} file is not a weights format Uncloud reads.")
        _apply_manifest(identification, path.with_name(path.name + "." + MANIFEST))
        return identification

    _readme(identification, path)
    # Most specific first. A declared pipeline beats everything; an mflux shard
    # index beats the component folders it also has; a folder that merely holds
    # models is only concluded once nothing says it is one.
    index = read_json(path / "model_index.json")
    config = read_json(path / "config.json")
    recognisers = (
        lambda: bool(index and index.get("_class_name"))
        and (_diffusers(identification, path, index) or True),
        lambda: _mflux(identification, path),
        lambda: _diffusers_parts(identification, path),
        lambda: bool(config) and _config_model(identification, path, config),
        lambda: _bundle(identification, path),
        lambda: _single_file_folder(identification, path),
        lambda: _container(identification, path),
    )
    if not any(recognise() for recognise in recognisers):
        # A name is only worth guessing from if there is something to name.
        if _weights_within(path):
            _guess_from_name(identification, path.name)
        if identification.confidence is Confidence.UNKNOWN:
            identification.warnings.append(
                "Nothing here declares or implies a model format Uncloud reads: no "
                "model_index.json, no config.json, no GGUF or recognisable weights.")
    _apply_manifest(identification, path / MANIFEST)
    return identification


def _apply_manifest(identification: Identification, manifest: Path) -> None:
    """A manifest written on an earlier import. Where the files already decided
    something, the files win; the manifest fills what they could not."""
    data = read_json(manifest)
    if not data:
        return
    identification.saw(manifest.name, "imported before; its recorded choices are applied")
    declared = data.get("declared") or {}
    identification.declared = {str(k): str(v) for k, v in declared.items()}
    if data.get("name"):
        identification.name = str(data["name"])
    if identification.confidence in (Confidence.GUESSED, Confidence.UNKNOWN) \
            or identification.candidates:
        for key in ("family", "task", "pipeline"):
            if declared.get(key):
                value = declared[key]
                setattr(identification, key, Task(value) if key == "task" else value)
        if declared.get("family"):
            identification.candidates = []
            identification.needs = [n for n in identification.needs
                                    if n.file != "uncloud-mlx.json"]
