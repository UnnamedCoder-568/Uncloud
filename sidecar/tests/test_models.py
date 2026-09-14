"""Model identification and metadata: what a model is, and what it is missing.

Every fixture here is built in a temporary folder from the few bytes the code
actually reads — a GGUF key table, a safetensors header, a handful of JSON
configs. No weights, no network, no dependency on anybody's drive. The
behaviours pinned are the ones that went wrong on a real one while this was
being written: an image model filed as a chat model, an adapter filed as a
checkpoint, a five-bit folder of four-bit weights, and a derived pipeline index
that silently swapped a model's scheduler.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from uncloud_engine.core.models import MANIFEST, apply, hub, identify, plan
from uncloud_engine.core.models.headers import read_gguf, read_safetensors
from uncloud_engine.core.models.identify import Confidence, Layout, Task
from uncloud_engine.core.models.metadata import MARK, PIPELINE_SETTINGS, PIPELINE_TEXT_ENCODERS

# ------------------------------------------------------------------ builders

def gguf(path: Path, fields: dict[str, object], *, vocab: int = 0) -> Path:
    """A GGUF file holding only a key-value table. `vocab` adds a tokenizer
    array BEFORE any remaining fields, the order some writers use."""
    def text(value: str) -> bytes:
        raw = value.encode()
        return struct.pack("<Q", len(raw)) + raw

    entries = []
    late = {}
    for key, value in fields.items():
        if vocab and key == "general.file_type":
            late[key] = value
            continue
        entries.append((key, value))
    body = b""
    count = 0
    for key, value in entries:
        body += text(key) + (struct.pack("<I", 8) + text(value) if isinstance(value, str)
                             else struct.pack("<I", 4) + struct.pack("<I", value))
        count += 1
    if vocab:
        body += text("tokenizer.ggml.tokens") + struct.pack("<I", 9) + struct.pack("<I", 8) \
            + struct.pack("<Q", vocab) + b"".join(text(f"tok{i}") for i in range(vocab))
        count += 1
        for key, value in late.items():
            body += text(key) + struct.pack("<I", 4) + struct.pack("<I", value)
            count += 1
    path.write_bytes(b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", 0)
                     + struct.pack("<Q", count) + body)
    return path


def safetensors(path: Path, shapes: dict[str, list[int]], metadata: dict | None = None) -> Path:
    header: dict[str, object] = {name: {"dtype": "F16", "shape": shape, "data_offsets": [0, 0]}
                                 for name, shape in shapes.items()}
    if metadata:
        header["__metadata__"] = metadata
    raw = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(raw)) + raw)
    return path


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def diffusers_parts(root: Path, transformer: str, *, text_encoder: str = "T5EncoderModel",
                    scheduler: str = "FlowMatchEulerDiscreteScheduler",
                    tokenizer: str = "T5Tokenizer", extras: bool = True) -> Path:
    write(root / "transformer" / "config.json",
          {"_class_name": transformer, "_diffusers_version": "0.35.0"})
    safetensors(root / "transformer" / "diffusion_pytorch_model.safetensors", {"w": [1]})
    write(root / "vae" / "config.json", {"_class_name": "AutoencoderKL"})
    safetensors(root / "vae" / "diffusion_pytorch_model.safetensors", {"w": [1]})
    write(root / "text_encoder" / "config.json", {"architectures": [text_encoder]})
    safetensors(root / "text_encoder" / "model.safetensors", {"w": [1]})
    write(root / "tokenizer" / "tokenizer_config.json", {"tokenizer_class": tokenizer})
    write(root / "scheduler" / "scheduler_config.json", {"_class_name": scheduler})
    if extras:
        (root / "assets").mkdir()
        (root / "assets" / "banner.png").write_bytes(b"\x89PNG")
    return root


def mflux(root: Path, *, double: int, single: int, width: int, bits: int,
          recorded: str | None = None, klein: bool = True) -> Path:
    names: dict[str, list[int]] = {}
    if klein:
        names["double_stream_modulation_img.linear.weight"] = [1, 1]
        for i in range(double):
            names[f"transformer_blocks.{i}.attn.to_q.weight"] = [width, width * bits // 32]
        for i in range(single):
            names[f"single_transformer_blocks.{i}.attn.to_q.weight"] = [1, 1]
    else:
        for part in ("txtfusion.w", "tproj.w", "first.w", "last.w"):
            names[part] = [1]
        for i in range(28):
            names[f"blocks.{i}.w"] = [1]
    safetensors(root / "transformer" / "0.safetensors", names)
    write(root / "transformer" / "model.safetensors.index.json", {
        "metadata": {"quantization_level": recorded or str(bits), "mflux_version": "0.18.0"},
        "weight_map": {n: "0.safetensors" for n in names}})
    (root / "vae").mkdir(parents=True, exist_ok=True)
    return root


# ===================================================================== GGUF

def test_gguf_language_model_is_certain(tmp_path: Path) -> None:
    i = identify(gguf(tmp_path / "q.gguf", {"general.architecture": "qwen3",
                                            "general.name": "Qwen3 4B", "general.file_type": 7}))
    assert (i.task, i.family, i.confidence, i.quantization) == \
        (Task.TEXT, "qwen3", Confidence.CERTAIN, "Q8_0")


def test_an_image_model_in_gguf_is_not_filed_as_a_chat_model(tmp_path: Path) -> None:
    """z_image_nsfw_v2-Q8_0.gguf: header lumina2, and a scanner that only knew
    'flux' and 'sd*' put it in the chat picker."""
    i = identify(gguf(tmp_path / "z_image_nsfw_v2-Q8_0.gguf", {"general.architecture": "lumina2"}))
    assert i.task is Task.IMAGE
    assert i.family == "z-image" and "lumina2" in i.candidates
    assert any(n.file == "(pipeline)" for n in i.needs)


def test_wan_gguf_is_video_from_the_header_not_the_filename(tmp_path: Path) -> None:
    i = identify(gguf(tmp_path / "unnamed.gguf", {"general.architecture": "wan"}))
    assert i.task is Task.VIDEO and i.confidence is Confidence.INFERRED
    assert not any("could not be read" in w for w in i.warnings)


def test_a_text_encoder_named_like_an_image_model(tmp_path: Path) -> None:
    i = identify(gguf(tmp_path / "flux2-klein-4b-uncensored-f16.gguf", {
        "general.architecture": "qwen3", "general.name": "Flux2 Klein 4b Text Encoder"}))
    assert i.task is Task.TEXT_ENCODER


def test_file_type_is_read_even_after_the_vocabulary(tmp_path: Path) -> None:
    i = identify(gguf(tmp_path / "late.gguf", {"general.architecture": "qwen3",
                                               "general.file_type": 15}, vocab=500))
    assert i.quantization == "Q4_K_M"


def test_not_a_gguf_file(tmp_path: Path) -> None:
    (tmp_path / "fake.gguf").write_bytes(b"NOPE" * 10)
    assert read_gguf(tmp_path / "fake.gguf") is None
    assert identify(tmp_path / "fake.gguf").warnings


# =============================================================== safetensors

def test_lokr_adapter_is_an_adapter_not_a_checkpoint(tmp_path: Path) -> None:
    i = identify(safetensors(tmp_path / "klein_snofs.safetensors", {
        "diffusion_model.double_blocks.0.img_attn.qkv.lokr_w1": [4, 4],
        "diffusion_model.double_blocks.0.img_attn.qkv.lokr_w2": [4, 4],
        "diffusion_model.single_blocks.0.linear1.lokr_w1": [4, 4],
    }, {"ss_base_model_version": "flux2"}))
    assert i.task is Task.ADAPTER and i.family == "flux"
    assert any("not a model" in w for w in i.warnings)


@pytest.mark.parametrize("keys, family, task", [
    ({"double_blocks.0.a": [1], "single_blocks.0.a": [1]}, "flux", Task.IMAGE),
    ({"model.diffusion_model.input_blocks.0.w": [1], "model.diffusion_model.label_emb.w": [1]},
     "sdxl", Task.IMAGE),
    ({"patch_embedding.weight": [1], "blocks.0.self_attn.q.weight": [1]}, "wan", Task.VIDEO),
    ({"decoder.up_blocks.0.w": [1], "encoder.down_blocks.0.w": [1]}, "vae", Task.COMPONENT),
])
def test_single_files_by_tensor_names(tmp_path: Path, keys, family, task) -> None:
    i = identify(safetensors(tmp_path / "anonymous.safetensors", keys))
    assert (i.family, i.task, i.confidence) == (family, task, Confidence.INFERRED)


def test_an_implausible_header_length_is_refused(tmp_path: Path) -> None:
    (tmp_path / "x.safetensors").write_bytes(struct.pack("<Q", 1 << 40) + b"{}")
    assert read_safetensors(tmp_path / "x.safetensors") is None


# ================================================================ diffusers

def test_a_declared_pipeline_is_certain_and_missing_parts_are_needs(tmp_path: Path) -> None:
    root = diffusers_parts(tmp_path / "ltx", "LTXVideoTransformer3DModel", extras=False)
    write(root / "model_index.json", {"_class_name": "LTXPipeline",
                                      "transformer": ["diffusers", "LTXVideoTransformer3DModel"],
                                      "image_encoder": ["transformers", "CLIPVisionModel"]})
    i = identify(root)
    assert (i.layout, i.task, i.family, i.confidence) == \
        (Layout.DIFFUSERS, Task.VIDEO, "ltx-video", Confidence.CERTAIN)
    assert any(n.file == "image_encoder/" for n in i.needs)


def test_components_without_an_index_produce_the_published_index(tmp_path: Path) -> None:
    """The shape of LTX-Video 2B's own model_index.json, which this matched
    exactly when checked against the real file."""
    root = diffusers_parts(tmp_path / "ltx", "LTXVideoTransformer3DModel")
    i = identify(root)
    assert i.layout is Layout.DIFFUSERS_PARTS and i.pipeline == "LTXPipeline"
    [step] = plan(i)
    assert step.action == "create" and not step.caution
    assert {k: v for k, v in step.content.items() if not k.startswith("_") or k == "_class_name"} \
        == {"_class_name": "LTXPipeline",
            "scheduler": ["diffusers", "FlowMatchEulerDiscreteScheduler"],
            "text_encoder": ["transformers", "T5EncoderModel"],
            "tokenizer": ["transformers", "T5Tokenizer"],
            "transformer": ["diffusers", "LTXVideoTransformer3DModel"],
            "vae": ["diffusers", "AutoencoderKL"]}
    assert step.content["_diffusers_version"] == "0.35.0"


def test_a_models_own_scheduler_is_never_replaced(tmp_path: Path) -> None:
    """An earlier version rewrote Wan's UniPC scheduler to the class the
    constructor's type hint names. The files are what gets written."""
    root = diffusers_parts(tmp_path / "wan", "WanTransformer3DModel",
                           text_encoder="UMT5EncoderModel", scheduler="UniPCMultistepScheduler")
    [step] = plan(identify(root))
    assert step.content["scheduler"] == ["diffusers", "UniPCMultistepScheduler"]


def test_pipeline_settings_no_component_records_are_a_caution(tmp_path: Path) -> None:
    root = diffusers_parts(tmp_path / "wan", "WanTransformer3DModel",
                           text_encoder="UMT5EncoderModel")
    [step] = plan(identify(root))
    assert step.caution and "expand_timesteps" in step.detail


def test_a_head_class_encoder_under_a_generic_pipeline_is_a_caution(tmp_path: Path) -> None:
    root = diffusers_parts(tmp_path / "z", "ZImageTransformer2DModel",
                           text_encoder="Qwen3ForCausalLM", tokenizer="Qwen2Tokenizer")
    [step] = plan(identify(root))
    assert step.caution and "language-model head" in step.detail
    assert step.content["tokenizer"] == ["transformers", "Qwen2Tokenizer"]


def test_weights_with_no_config_block_the_index(tmp_path: Path) -> None:
    root = diffusers_parts(tmp_path / "x", "LTXVideoTransformer3DModel")
    safetensors(root / "mystery" / "weights.safetensors", {"w": [1]})
    [step] = plan(identify(root))
    assert step.action == "unavailable" and "mystery" in step.detail


def test_flux2_klein_is_told_apart_by_its_encoder(tmp_path: Path) -> None:
    root = diffusers_parts(tmp_path / "k", "Flux2Transformer2DModel",
                           text_encoder="Qwen3ForCausalLM")
    assert identify(root).pipeline == "Flux2KleinPipeline"


# ==================================================================== mflux

@pytest.mark.parametrize("double, single, width, bits, base", [
    (5, 20, 3072, 4, "flux2_klein_4b"),
    (8, 24, 4096, 6, "flux2_klein_9b"),
])
def test_mflux_base_and_bits_come_from_the_tensors(tmp_path: Path, double, single, width,
                                                    bits, base) -> None:
    i = identify(mflux(tmp_path / "m", double=double, single=single, width=width, bits=bits))
    assert (i.layout, i.family, i.quantization) == (Layout.MFLUX, base, f"{bits}bit")
    [step] = plan(i)
    assert step.action == "create" and step.content["base_model"] == base


def test_krea2_layout(tmp_path: Path) -> None:
    assert identify(mflux(tmp_path / "k", double=0, single=0, width=0, bits=4,
                          klein=False)).family == "krea2"


def test_a_folder_named_five_bit_holding_four_bit_weights(tmp_path: Path) -> None:
    i = identify(mflux(tmp_path / "klein (5-bit MLX)", double=5, single=20, width=3072, bits=4))
    assert i.quantization == "4bit"
    assert any("says 5-bit" in w for w in i.warnings)


def test_an_unrecognised_mflux_checkpoint_asks_rather_than_guesses(tmp_path: Path) -> None:
    root = mflux(tmp_path / "m", double=3, single=3, width=1024, bits=4)
    i = identify(root)
    assert i.candidates and plan(i)[0].action == "choose"
    [chosen] = plan(i, choices={"family": "flux2_klein_4b"})
    assert chosen.action == "create" and chosen.source == "your choice"


def test_a_recipe_resolves_its_checkpoint_and_notes_missing_adapters(tmp_path: Path) -> None:
    mflux(tmp_path / "weights", double=8, single=24, width=4096, bits=6)
    write(tmp_path / "recipe" / "uncloud-mlx.json", {
        "base_model": "flux2_klein_9b", "checkpoint": "../weights",
        "lora_paths": ["../adapters/gone.safetensors"]})
    i = identify(tmp_path / "recipe")
    assert (i.layout, i.family, i.confidence) == (Layout.MFLUX, "flux2_klein_9b",
                                                  Confidence.CERTAIN)
    assert any("MISSING" in e.finding for e in i.evidence)


# ========================================================= configs and folders

@pytest.mark.parametrize("config, task, layout", [
    ({"architectures": ["Qwen3ForCausalLM"], "model_type": "qwen3",
      "quantization": {"bits": 4, "group_size": 64}}, Task.TEXT, Layout.MLX),
    ({"architectures": ["WhisperForConditionalGeneration"], "model_type": "whisper"},
     Task.SPEECH_TO_TEXT, Layout.TRANSFORMERS),
    ({"architectures": ["BarkModel"], "model_type": "bark"}, Task.TEXT_TO_SPEECH,
     Layout.TRANSFORMERS),
    ({"architectures": ["AceStepConditionGenerationModel"], "model_type": "acestep"},
     Task.MUSIC, Layout.BUNDLE),
])
def test_configs_that_declare_what_they_are(tmp_path: Path, config, task, layout) -> None:
    root = tmp_path / "m"
    write(root / "config.json", config)
    write(root / "tokenizer.json", {})
    write(root / "tokenizer_config.json", {})
    safetensors(root / "model.safetensors", {"w": [1]})
    i = identify(root)
    assert (i.task, i.layout) == (task, layout)


def test_a_language_model_without_its_tokenizer_needs_one(tmp_path: Path) -> None:
    write(tmp_path / "m" / "config.json", {"architectures": ["LlamaForCausalLM"],
                                           "model_type": "llama"})
    safetensors(tmp_path / "m" / "model.safetensors", {"w": [1]})
    assert {n.file for n in identify(tmp_path / "m").needs} == \
        {"tokenizer.json", "tokenizer_config.json"}


def test_whisper_in_ctranslate2_format(tmp_path: Path) -> None:
    write(tmp_path / "w" / "config.json", {"model_type": "whisper",
                                           "architectures": ["WhisperForConditionalGeneration"]})
    (tmp_path / "w" / "model.bin").write_bytes(b"ct2")
    assert identify(tmp_path / "w").layout is Layout.CTRANSLATE2


def test_chatterbox_set(tmp_path: Path) -> None:
    for name in ("t3_cfg", "s3gen", "ve"):
        safetensors(tmp_path / "c" / f"{name}.safetensors", {"w": [1]})
    assert identify(tmp_path / "c").family == "chatterbox"


def test_a_folder_holding_one_gguf_is_that_gguf(tmp_path: Path) -> None:
    folder = tmp_path / "Qwen3-4B-Q8_0"
    folder.mkdir()
    gguf(folder / "qwen3-4b-q8_0.gguf", {"general.architecture": "qwen3", "general.file_type": 7})
    i = identify(folder)
    assert i.is_file and i.task is Task.TEXT and i.path.endswith(".gguf")


def test_a_folder_of_models_lists_them(tmp_path: Path) -> None:
    mflux(tmp_path / "Krea" / "Quantized-Q8", double=0, single=0, width=0, bits=8, klein=False)
    (tmp_path / "Krea" / "README.md").write_text("# Krea")
    i = identify(tmp_path / "Krea")
    assert [c["family"] for c in i.contents] == ["krea2"]


def test_no_weights_means_no_guess_from_the_name(tmp_path: Path) -> None:
    (tmp_path / "vibevoice-voices-audio").mkdir()
    (tmp_path / "vibevoice-voices-audio" / "sample.wav").write_bytes(b"RIFF")
    i = identify(tmp_path / "vibevoice-voices-audio")
    assert i.confidence is Confidence.UNKNOWN and i.task is Task.UNKNOWN


def test_nothing_at_the_path(tmp_path: Path) -> None:
    assert identify(tmp_path / "missing").warnings


def test_readme_licence_is_a_claim(tmp_path: Path) -> None:
    root = diffusers_parts(tmp_path / "ltx", "LTXVideoTransformer3DModel")
    (root / "README.md").write_text("---\nlicense: other\nbase_model: Lightricks/LTX-Video\n---\n")
    i = identify(root)
    assert i.licence_claim == "other" and i.base_repo == "Lightricks/LTX-Video"
    assert any("not verified" in e.finding for e in i.evidence)


# ================================================================ metadata

def test_lookup_order_sibling_before_online_before_derived(tmp_path: Path) -> None:
    root = diffusers_parts(tmp_path / "models" / "wan-a", "WanTransformer3DModel",
                           text_encoder="UMT5EncoderModel")
    sibling = diffusers_parts(tmp_path / "models" / "wan-b", "WanTransformer3DModel",
                              text_encoder="UMT5EncoderModel", extras=False)
    write(sibling / "model_index.json", {"_class_name": "WanPipeline", "expand_timesteps": True,
                                         "transformer": ["diffusers", "WanTransformer3DModel"]})
    fetched: list[str] = []
    [step] = plan(identify(root), fetch=lambda repo, file: fetched.append(file) or {})
    assert step.action == "copy" and step.content["expand_timesteps"] is True and not fetched


def test_online_lookup_used_when_asked_and_a_repo_is_named(tmp_path: Path) -> None:
    root = diffusers_parts(tmp_path / "w", "WanTransformer3DModel", text_encoder="UMT5EncoderModel")
    (root / "README.md").write_text("---\nbase_model: Wan-AI/Wan2.2-TI2V-5B-Diffusers\n---\n")
    published = {"_class_name": "WanPipeline", "expand_timesteps": True}
    [step] = plan(identify(root), fetch=lambda repo, file: published)
    assert step.action == "fetch" and step.source.endswith("Wan2.2-TI2V-5B-Diffusers")


def test_a_gated_repository_falls_back_rather_than_forcing(tmp_path: Path) -> None:
    root = diffusers_parts(tmp_path / "w", "LTXVideoTransformer3DModel")
    (root / "README.md").write_text("---\nbase_model: org/gated\n---\n")

    def gated(repo: str, file: str) -> dict:
        raise hub.Gated("org/gated is gated.")

    [step] = plan(identify(root), fetch=gated)
    assert step.action == "create"          # derivable, so built from disk instead


def test_apply_never_overwrites_and_marks_what_it_made(tmp_path: Path) -> None:
    root = diffusers_parts(tmp_path / "ltx", "LTXVideoTransformer3DModel")
    i = identify(root)
    steps = plan(i)
    first = apply(i, steps, product="Uncloud", name="LTX", licence="unknown")
    assert first["created"] == ["model_index.json"]
    assert json.loads((root / "model_index.json").read_text())[MARK]["created"] is True
    manifest = json.loads((root / MANIFEST).read_text())
    assert manifest["licence"] == {"claimed": "", "declared": "unknown"}
    assert manifest["created_files"] == ["model_index.json"]

    (root / "model_index.json").write_text('{"_class_name": "HandWritten"}')
    second = apply(identify(root), steps, product="Uncloud", name="LTX")
    assert second["skipped"] == ["model_index.json"]
    assert json.loads((root / "model_index.json").read_text())["_class_name"] == "HandWritten"
    assert json.loads((root / MANIFEST).read_text())["created_files"] == ["model_index.json"]


def test_a_single_file_manifest_sits_beside_it(tmp_path: Path) -> None:
    path = gguf(tmp_path / "enc.gguf", {"general.architecture": "qwen3"})
    result = apply(identify(path), [], product="Studio", name="Encoder")
    assert Path(result["manifest"]) == tmp_path / f"enc.gguf.{MANIFEST}"


def test_a_recorded_choice_settles_ambiguity_next_time(tmp_path: Path) -> None:
    root = mflux(tmp_path / "m", double=3, single=3, width=1024, bits=4)
    i = identify(root)
    apply(i, plan(i, choices={"family": "z_image_turbo"}), product="Uncloud", name="Mine",
          choices={"family": "z_image_turbo"})
    again = identify(root)
    assert again.family == "z_image_turbo" and not again.candidates and again.name == "Mine"


# ===================================================================== hub

@pytest.mark.parametrize("repo, file", [("not a repo", "config.json"), ("a/b", "../x.json"),
                                        ("a/b", "weights.safetensors"), ("../../x/y", "a.json")])
def test_hub_refuses_anything_but_a_json_config_in_a_repo(repo, file) -> None:
    with pytest.raises(hub.NotFound):
        hub.fetch_json(repo, file)


@pytest.mark.parametrize("code, error", [(401, hub.Gated), (403, hub.Gated), (404, hub.NotFound),
                                         (500, hub.Unreachable)])
def test_hub_status_codes(monkeypatch, code, error) -> None:
    import urllib.error

    def refuse(*args, **kwargs):
        raise urllib.error.HTTPError("u", code, "x", {}, None)

    monkeypatch.setattr(hub.urllib.request, "urlopen", refuse)
    with pytest.raises(error):
        hub.fetch_json("org/model", "model_index.json")


# ======================================================== against diffusers

def test_tables_match_diffusers_itself() -> None:
    """Every class and setting named in the tables exists in diffusers, where
    diffusers is installed. A renamed pipeline fails here, not on import day."""
    diffusers = pytest.importorskip("diffusers")
    import inspect

    from uncloud_engine.core.models.identify import TRANSFORMER_PIPELINES

    for transformer, pipeline in TRANSFORMER_PIPELINES.items():
        assert hasattr(diffusers, transformer), transformer
        assert hasattr(diffusers, pipeline), pipeline
    for pipeline, settings in PIPELINE_SETTINGS.items():
        parameters = inspect.signature(getattr(diffusers, pipeline).__init__).parameters
        for setting in settings:
            assert setting in parameters, f"{pipeline}.{setting}"
    for pipeline, encoders in PIPELINE_TEXT_ENCODERS.items():
        parameters = inspect.signature(getattr(diffusers, pipeline).__init__).parameters
        for component in encoders:
            assert component in parameters, f"{pipeline}.{component}"
