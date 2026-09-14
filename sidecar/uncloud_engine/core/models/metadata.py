"""The metadata a model needs: found where it exists, created where it can be.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

For every file a model is missing, the lookup runs in one order and records
which step answered:

1. already on disk;
2. a sibling folder holding the same pipeline, which has the file;
3. the model's own repository on Hugging Face — only if a person asked;
4. built from what is on disk, where that involves no guessing;
5. otherwise nothing is written, and the reason is said.

Nothing is ever overwritten. A plan is shown before anything is written, the
write re-checks that each file is still absent, and every created file is
marked as created so it can be told apart from what the model shipped with.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import hub
from .headers import read_json
from .identify import MANIFEST, Identification

Fetch = Callable[[str, str], dict]

#: Written into files this module creates, under a key loaders ignore:
#: diffusers drops `_`-prefixed keys from a model_index.json.
MARK = "_uncloud"


#: Pipeline settings that live only in a published model_index.json — no
#: component config records them, so an index built from components gets the
#: defaults. Read from diffusers' own constructors (and checked against them in
#: the tests). For Wan 2.2 TI2V-5B the published file sets expand_timesteps to
#: true; the default is false, and the difference is a wrong video.
PIPELINE_SETTINGS: dict[str, tuple[str, ...]] = {
    "WanPipeline": ("boundary_ratio", "expand_timesteps"),
    "WanVACEPipeline": ("boundary_ratio",),
    "Flux2KleinPipeline": ("is_distilled",),
    "StableDiffusionXLPipeline": ("force_zeros_for_empty_prompt", "add_watermarker"),
}


#: Text encoder classes a pipeline's constructor names concretely. Used ONLY to
#: warn, never to rewrite: what a model's own files declare is what gets
#: written. Overriding from constructor type hints was tried and replaced Wan's
#: real UniPC scheduler with a flow-matching one — a wrong video from a file
#: that looked authoritative. Generic declarations (PreTrainedModel,
#: AutoTokenizer) are absent because they settle nothing.
PIPELINE_TEXT_ENCODERS: dict[str, dict[str, str]] = {
    "LTXPipeline": {"text_encoder": "T5EncoderModel"},
    "WanPipeline": {"text_encoder": "UMT5EncoderModel"},
    "WanVACEPipeline": {"text_encoder": "UMT5EncoderModel"},
    "Flux2KleinPipeline": {"text_encoder": "Qwen3ForCausalLM"},
    "Flux2Pipeline": {"text_encoder": "Mistral3ForConditionalGeneration"},
    "FluxPipeline": {"text_encoder": "CLIPTextModel", "text_encoder_2": "T5EncoderModel"},
    "HunyuanVideoPipeline": {"text_encoder": "LlamaModel", "text_encoder_2": "CLIPTextModel"},
    "CogVideoXPipeline": {"text_encoder": "T5EncoderModel"},
    "ChromaPipeline": {"text_encoder": "T5EncoderModel"},
    "StableDiffusion3Pipeline": {"text_encoder": "CLIPTextModel",
                                 "text_encoder_2": "CLIPTextModel",
                                 "text_encoder_3": "T5EncoderModel"},
    "StableDiffusionXLPipeline": {"text_encoder": "CLIPTextModel",
                                  "text_encoder_2": "CLIPTextModel"},
    "StableDiffusionPipeline": {"text_encoder": "CLIPTextModel"},
}


@dataclass
class Step:
    file: str
    #: present | create | fetch | copy | choose | unavailable
    action: str
    source: str
    detail: str = ""
    content: dict | None = None
    #: Written, but possibly not what the model's publisher wrote. Shown to the
    #: person as a caution, never hidden in a log.
    caution: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _component_spec(folder: Path) -> list[str] | None:
    """[library, class] for one pipeline component, read from its own config."""
    for name in ("config.json", "scheduler_config.json"):
        config = read_json(folder / name)
        if config and config.get("_class_name"):
            return ["diffusers", str(config["_class_name"])]
    config = read_json(folder / "config.json")
    if config and config.get("architectures"):
        return ["transformers", str(config["architectures"][0])]
    tokenizer = read_json(folder / "tokenizer_config.json")
    if tokenizer and tokenizer.get("tokenizer_class"):
        # Exactly as declared. Published indexes name the fast class for some
        # models and not for others with the same files; guessing would be
        # right half the time and look authoritative every time.
        return ["transformers", str(tokenizer["tokenizer_class"])]
    return None


def _holds_weights(folder: Path) -> bool:
    return any(p.suffix in (".safetensors", ".bin", ".gguf", ".pt") for p in folder.glob("*"))


def derive_model_index(root: Path, pipeline: str) -> tuple[dict | None, str]:
    """A model_index.json assembled from the component configs beside it.

    Returns (index, problem). A non-empty problem with an index is a caution:
    written, but not certainly what the publisher wrote.
    """
    index: dict[str, object] = {"_class_name": pipeline}
    expected = PIPELINE_TEXT_ENCODERS.get(pipeline, {})
    cautions: list[str] = []
    version = None
    unresolved = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        spec = _component_spec(folder)
        if spec is None:
            # A folder of images or documentation is not a component. One that
            # holds weights with nothing saying what they are is a real gap.
            if _holds_weights(folder):
                unresolved.append(folder.name)
            continue
        if folder.name in expected and spec[1] != expected[folder.name]:
            cautions.append(f"{folder.name} is recorded as {spec[1]}, but {pipeline} is "
                            f"written for {expected[folder.name]}.")
        elif folder.name.startswith("text_encoder") and folder.name not in expected \
                and spec[1].endswith(("ForCausalLM", "ForConditionalGeneration")):
            cautions.append(f"{folder.name} is recorded as {spec[1]}, a class with a "
                            "language-model head; the published pipeline may load the bare "
                            "model instead. It works either way, loading a little more.")
        index[folder.name] = spec
        version = version or (read_json(folder / "config.json") or {}).get("_diffusers_version")
    if "transformer" not in index and "unet" not in index:
        return None, "No transformer or unet component could be read."
    if unresolved:
        return None, ("These folders have no configuration saying what they are: "
                      + ", ".join(unresolved))
    if version:
        # The version the components were saved with, not an invented one.
        index["_diffusers_version"] = version
    index[MARK] = {"created": True,
                   "from": "the component configurations in this folder"}
    return index, " ".join(cautions)


def _sibling_with(root: Path, file: str, pipeline: str) -> Path | None:
    parent = root.parent
    try:
        siblings = sorted(p for p in parent.iterdir() if p.is_dir() and p != root)
    except OSError:
        return None
    for sibling in siblings:
        candidate = sibling / file
        index = read_json(sibling / "model_index.json") or {}
        if candidate.is_file() and (not pipeline or index.get("_class_name") == pipeline):
            return candidate
    return None


def plan(identification: Identification, *, choices: dict[str, str] | None = None,
         fetch: Fetch | None = None) -> list[Step]:
    """What would be written, and from where, without writing anything."""
    choices = choices or {}
    root = Path(identification.path)
    folder = root.parent if identification.is_file else root
    steps: list[Step] = []

    for need in identification.needs:
        if need.file == "(pipeline)":
            steps.append(Step(need.file, "unavailable", "",
                              detail=need.why + " Add the full pipeline folder instead, "
                                     "or import this file into one."))
            continue
        target = folder / need.file
        if target.exists():
            steps.append(Step(need.file, "present", "already on disk"))
            continue

        if need.file == "uncloud-mlx.json":
            base = choices.get("family") or (identification.family
                                             if not identification.candidates else "")
            if not base:
                steps.append(Step(need.file, "choose", "",
                                  detail=need.why, content=None))
                continue
            steps.append(Step(need.file, "create",
                              "your choice" if choices.get("family") else
                              "the checkpoint's own tensors",
                              content={"base_model": base, "name": identification.name,
                                       MARK: {"created": True}}))
            continue

        if need.file.endswith("/") :
            steps.append(Step(need.file, "unavailable", "", detail=need.why))
            continue

        sibling = _sibling_with(folder, need.file, identification.pipeline)
        if sibling is not None:
            content = read_json(sibling)
            steps.append(Step(need.file, "copy", f"{sibling.parent.name}/{need.file}",
                              detail="a sibling folder holding the same pipeline has it",
                              content=content))
            continue

        if fetch is not None and identification.base_repo:
            try:
                content = fetch(identification.base_repo, need.file)
                steps.append(Step(need.file, "fetch", f"huggingface.co/{identification.base_repo}",
                                  content=content))
                continue
            except hub.LookupError_ as error:
                if not need.derivable:
                    steps.append(Step(need.file, "unavailable", "", detail=str(error)))
                    continue

        if need.file == "model_index.json" and identification.pipeline:
            content, problem = derive_model_index(folder, identification.pipeline)
            settings = PIPELINE_SETTINGS.get(identification.pipeline, ())
            if content is not None:
                notes = [problem] if problem else []
                if settings:
                    notes.insert(0, f"{identification.pipeline} also takes "
                                    f"{', '.join(settings)}, which no component records, so "
                                    "the defaults are used. They may not match this model; "
                                    "the published file from an online lookup is safer.")
                steps.append(Step(need.file, "create", "the component configurations on disk",
                                  content=content, caution=bool(notes), detail=" ".join(notes)))
            else:
                steps.append(Step(need.file, "unavailable", "", detail=problem))
            continue

        detail = need.why
        if not identification.base_repo:
            detail += (" Nothing on disk names the repository it came from, so it "
                       "cannot be looked up.")
        elif fetch is None:
            detail += f" It can be looked up from {identification.base_repo} online."
        steps.append(Step(need.file, "unavailable", "", detail=detail))
    return steps


def manifest_path(identification: Identification) -> Path:
    path = Path(identification.path)
    return path.with_name(path.name + "." + MANIFEST) if identification.is_file \
        else path / MANIFEST


def manifest(identification: Identification, *, product: str, name: str,
             choices: dict[str, str], licence: str, created: list[str]) -> dict:
    return {
        "schemaVersion": 1,
        "name": name,
        "task": str(identification.task),
        "family": choices.get("family") or identification.family,
        "layout": str(identification.layout),
        "pipeline": identification.pipeline,
        "architecture": identification.architecture,
        "quantization": identification.quantization,
        "base_repo": identification.base_repo,
        "confidence": str(identification.confidence),
        "evidence": [asdict(e) for e in identification.evidence],
        "declared": {k: v for k, v in choices.items() if v},
        # Two fields, kept apart: what the model card claims, and what the person
        # importing said. Neither is treated as a verified licence.
        "licence": {"claimed": identification.licence_claim, "declared": licence or "unknown"},
        "created_files": created,
        "imported_by": product,
        "imported_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def _write_new(path: Path, content: dict) -> None:
    """Create `path` with `content`, failing rather than replacing anything."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.uncloud-tmp")
    temporary.write_text(json.dumps(content, indent=2) + "\n")
    try:
        # link, not rename: link refuses an existing target atomically, where a
        # rename would silently replace a file that appeared since the plan.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply(identification: Identification, steps: list[Step], *, product: str, name: str,
          choices: dict[str, str] | None = None, licence: str = "unknown") -> dict:
    """Write the planned files and the manifest. Returns what happened."""
    choices = choices or {}
    root = Path(identification.path)
    folder = root.parent if identification.is_file else root
    created, skipped, failed = [], [], []
    for step in steps:
        if step.action not in ("create", "copy", "fetch") or step.content is None:
            continue
        target = folder / step.file
        content = dict(step.content)
        if step.action in ("copy", "fetch"):
            content.setdefault(MARK, {"created": True, "from": step.source})
        try:
            _write_new(target, content)
            created.append(step.file)
        except FileExistsError:
            skipped.append(step.file)
        except OSError as error:
            failed.append({"file": step.file, "error": error.strerror or str(error)})

    record = manifest(identification, product=product, name=name, choices=choices,
                      licence=licence, created=created)
    target = manifest_path(identification)
    try:
        if target.exists():
            existing = read_json(target) or {}
            earlier = set(existing.get("created_files") or [])
            record["created_files"] = sorted(earlier | set(created))
            target.write_text(json.dumps(record, indent=2) + "\n")   # our own file: updated
        else:
            _write_new(target, record)
    except OSError as error:
        failed.append({"file": target.name, "error": error.strerror or str(error)})
    return {"created": created, "skipped": skipped, "failed": failed,
            "manifest": str(target)}
