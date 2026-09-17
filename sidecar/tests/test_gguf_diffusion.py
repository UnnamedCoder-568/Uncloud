"""A lone diffusion transformer, completed from a pipeline already on disk.

What gets shared for a fine-tuned image model is one quantised file. Uncloud
listed it, greyed out, saying it needed a VAE, a text encoder and a scheduler —
true, and unhelpful when all three were sitting in the same folder inside the
official release the fine-tune was cut from.

These tests cover the judgement, not the arithmetic of denoising: which files
can be completed, from what, and what a person is told when nothing fits.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uncloud_engine.gguf_diffusion import assembly_for


def _pipeline(root: Path, pipeline_class: str, transformer_class: str) -> Path:
    """A folder shaped like a complete diffusers pipeline."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "model_index.json").write_text(json.dumps({"_class_name": pipeline_class}))
    for part in ("scheduler", "text_encoder", "tokenizer", "vae", "transformer"):
        (root / part).mkdir(exist_ok=True)
    (root / "transformer" / "config.json").write_text(
        json.dumps({"_class_name": transformer_class}))
    return root


def test_a_lone_transformer_borrows_from_its_own_family(tmp_path: Path) -> None:
    _pipeline(tmp_path / "z-image-turbo", "ZImagePipeline", "ZImageTransformer2DModel")
    loose = tmp_path / "z_image_nsfw-Q8_0.gguf"
    loose.touch()

    assembly = assembly_for(loose, "z-image", tmp_path)

    assert assembly.ready
    assert assembly.base is not None and assembly.base.name == "z-image-turbo"
    assert "z-image-turbo" in assembly.note()


def test_another_family_is_not_borrowed_from(tmp_path: Path) -> None:
    """A VAE from the wrong pipeline does not make a picture, it makes soup."""
    _pipeline(tmp_path / "some-sdxl", "StableDiffusionXLPipeline", "UNet2DConditionModel")
    loose = tmp_path / "z_image_nsfw-Q8_0.gguf"
    loose.touch()

    assembly = assembly_for(loose, "z-image", tmp_path)

    assert not assembly.ready
    assert assembly.base is None
    assert "z-image" in assembly.note()


def test_an_incomplete_donor_is_no_donor(tmp_path: Path) -> None:
    donor = _pipeline(tmp_path / "half-a-pipeline", "ZImagePipeline",
                      "ZImageTransformer2DModel")
    (donor / "vae").rmdir()
    loose = tmp_path / "z_image_nsfw-Q8_0.gguf"
    loose.touch()

    assert not assembly_for(loose, "z-image", tmp_path).ready


def test_an_unknown_family_says_so_rather_than_guessing(tmp_path: Path) -> None:
    _pipeline(tmp_path / "z-image-turbo", "ZImagePipeline", "ZImageTransformer2DModel")
    loose = tmp_path / "something-Q8_0.gguf"
    loose.touch()

    note = assembly_for(loose, "kandinsky", tmp_path).note()

    assert not assembly_for(loose, "kandinsky", tmp_path).ready
    assert "kandinsky" in note


def test_the_same_donor_every_time(tmp_path: Path) -> None:
    """Which pipeline lent the VAE changes the picture. Picking by directory
    order would move that answer for no reason anybody could see."""
    for name in ("b-release", "a-release", "c-release"):
        _pipeline(tmp_path / name, "ZImagePipeline", "ZImageTransformer2DModel")
    loose = tmp_path / "z_image-Q8_0.gguf"
    loose.touch()

    picked = {assembly_for(loose, "z-image", tmp_path).base for _ in range(3)}

    assert picked == {tmp_path / "a-release"}


def test_the_engine_loads_a_gguf_through_the_assembly(tmp_path: Path) -> None:
    """The branch that matters at generation time: a .gguf image model must not
    be handed to the single-file SDXL loader, which is what every other loose
    checkpoint is."""
    # The loader reaches for torch and diffusers before it reaches the branch,
    # and neither is installed where these tests run in CI.
    pytest.importorskip("diffusers")

    from uncloud_engine import gguf_diffusion
    from uncloud_engine import image_engine as engine_mod

    loose = tmp_path / "z_image_nsfw-Q8_0.gguf"
    loose.touch()
    _pipeline(tmp_path / "z-image-turbo", "ZImagePipeline", "ZImageTransformer2DModel")
    asked: dict = {}

    def fake_load(path, models_dir, family, *, dtype=None):
        asked.update(path=str(path), family=family)

        class Pipe:
            def to(self, _device):
                return self

        return Pipe()

    original = gguf_diffusion.load_pipeline
    gguf_diffusion.load_pipeline = fake_load  # type: ignore[assignment]
    try:
        engine_mod.ImageEngine()._load_pipeline(str(loose))
    finally:
        gguf_diffusion.load_pipeline = original  # type: ignore[assignment]

    assert asked["path"] == str(loose)
    # Read from the file's own header, not from its name.
    assert asked["family"] in ("z-image", "lumina2", "")
