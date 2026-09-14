"""Uncloud's side of adding a model: which engine runs it, and the routes.

`core.models` decides what a model IS and has its own tests. These pin what is
Uncloud's alone — that a model is only `ready` when an engine here really
loads it — plus the scanner behaviours that were wrong on a real drive, and the
boundary that keeps a phone paired over the network from writing into folders
on the computer.

Settings are replaced for the duration of each test. Nothing here writes to
the real ~/.uncloud.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_models import diffusers_parts, gguf, mflux, safetensors, write  # same folder

from uncloud_engine.core.models import identify
from uncloud_engine.core.permission import Mode, Risk
from uncloud_engine.model_import import IMAGE2IMAGE, TEXT2IMAGE, verdict


@pytest.fixture
def models(tmp_path: Path, monkeypatch):
    """An isolated models folder and settings that never reach disk."""
    from uncloud_engine import library
    from uncloud_engine.config import settings

    folder = tmp_path / "models"
    folder.mkdir()
    monkeypatch.setattr(settings, "_data", {"models_dir": str(folder)})
    monkeypatch.setattr(settings, "_save", lambda: None)
    library.invalidate_library_cache()
    yield folder
    library.invalidate_library_cache()


def _by_name(found, name: str):
    return next(m for m in found if m.name == name)


# ================================================================ verdicts

def test_an_image_gguf_is_not_a_chat_model(tmp_path: Path) -> None:
    v = verdict(identify(gguf(tmp_path / "z_image_nsfw_v2-Q8_0.gguf",
                              {"general.architecture": "lumina2"})))
    assert v.category == "image" and not v.runnable


def test_whisper_is_only_runnable_as_ctranslate2(tmp_path: Path) -> None:
    write(tmp_path / "hf" / "config.json", {"model_type": "whisper",
                                            "architectures": ["WhisperForConditionalGeneration"]})
    safetensors(tmp_path / "hf" / "model.safetensors", {"w": [1]})
    assert not verdict(identify(tmp_path / "hf")).runnable
    write(tmp_path / "ct2" / "config.json", {"model_type": "whisper"})
    (tmp_path / "ct2" / "model.bin").write_bytes(b"ct2")
    assert verdict(identify(tmp_path / "ct2")).runnable


def test_video_is_ready_only_for_the_families_the_engine_loads(tmp_path: Path) -> None:
    ltx = diffusers_parts(tmp_path / "ltx", "LTXVideoTransformer3DModel")
    write(ltx / "model_index.json", {"_class_name": "LTXPipeline"})
    hunyuan = diffusers_parts(tmp_path / "hy", "HunyuanVideoTransformer3DModel")
    write(hunyuan / "model_index.json", {"_class_name": "HunyuanVideoPipeline"})
    assert verdict(identify(ltx)).runnable
    assert not verdict(identify(hunyuan)).runnable


def test_components_without_an_index_are_not_ready_until_imported(tmp_path: Path) -> None:
    v = verdict(identify(diffusers_parts(tmp_path / "ltx", "LTXVideoTransformer3DModel")))
    assert not v.runnable and "model_index.json" in v.note


def test_adapters_and_unknown_speech_models_explain_themselves(tmp_path: Path) -> None:
    lora = safetensors(tmp_path / "a.safetensors", {"double_blocks.0.lokr_w1": [1]})
    assert verdict(identify(lora)).engine == "adapter"
    for name in ("t3_cfg", "s3gen", "ve"):
        safetensors(tmp_path / "cb" / f"{name}.safetensors", {"w": [1]})
    v = verdict(identify(tmp_path / "cb"))
    assert not v.runnable and "chatterbox" in v.note


def test_pipeline_sets_match_diffusers_auto_pipelines() -> None:
    pytest.importorskip("diffusers")
    from diffusers.pipelines.auto_pipeline import (
        AUTO_IMAGE2IMAGE_PIPELINES_MAPPING,
        AUTO_TEXT2IMAGE_PIPELINES_MAPPING,
    )

    text = {c.__name__ for c in AUTO_TEXT2IMAGE_PIPELINES_MAPPING.values()}
    image = {c.__name__ for c in AUTO_IMAGE2IMAGE_PIPELINES_MAPPING.values()}
    assert text >= TEXT2IMAGE, TEXT2IMAGE - text
    assert (image | text) >= IMAGE2IMAGE, IMAGE2IMAGE - image


# ================================================================= scanner

def test_scanner_lists_what_it_cannot_run_instead_of_hiding_it(models: Path) -> None:
    from uncloud_engine.library import scan_library

    for name in ("t3_cfg", "s3gen", "ve"):
        safetensors(models / "chatterbox-tts" / f"{name}.safetensors", {"w": [1]})
    gguf(models / "z_image_nsfw_v2-Q8_0.gguf", {"general.architecture": "lumina2"})
    write(models / "Whisper Small" / "config.json",
          {"model_type": "whisper", "architectures": ["WhisperForConditionalGeneration"]})
    safetensors(models / "Whisper Small" / "model.safetensors", {"w": [1]})

    found = scan_library(models)
    chatterbox = _by_name(found, "chatterbox-tts")
    image = _by_name(found, "z_image_nsfw_v2-Q8_0")
    whisper = _by_name(found, "Whisper Small")
    assert not chatterbox.ready and chatterbox.note
    assert image.category == "image" and not image.ready
    assert whisper.engine == "faster-whisper" and not whisper.ready


def test_gguf_parts_a_pipeline_names_are_not_listed_twice(models: Path) -> None:
    from uncloud_engine.library import scan_library

    wan = diffusers_parts(models / "Wan", "WanTransformer3DModel",
                          text_encoder="UMT5EncoderModel", extras=False)
    write(wan / "model_index.json", {"_class_name": "WanPipeline"})
    gguf(wan / "wan-Q4_K_M.gguf", {"general.architecture": "wan"})
    write(wan / "uncloud-video.json", {"family": "wan", "transformer_gguf": "wan-Q4_K_M.gguf"})
    names = [m.name for m in scan_library(models)]
    assert "Wan" in names and "wan-Q4_K_M" not in names


def test_an_mflux_checkpoint_without_a_marker_is_ready_from_its_tensors(models: Path) -> None:
    from uncloud_engine.budget import engine_runs_here
    from uncloud_engine.library import scan_library

    mflux(models / "klein-q6", double=8, single=24, width=4096, bits=6)
    entry = _by_name(scan_library(models), "klein-q6")
    assert entry.mflux_base == "flux2_klein_9b"
    assert entry.ready is engine_runs_here("mflux")


def test_studios_marker_is_read_too(models: Path) -> None:
    from uncloud_engine.library import scan_library

    mflux(models / "k4", double=5, single=20, width=3072, bits=4)
    write(models / "k4" / "adstudio-mlx.json", {"base_model": "flux2_klein_4b",
                                                 "name": "FLUX.2 Klein 4B"})
    assert _by_name(scan_library(models), "FLUX.2 Klein 4B").mflux_base == "flux2_klein_4b"


def test_imported_models_survive_a_models_folder_that_does_not_exist(models: Path,
                                                                    tmp_path: Path) -> None:
    from uncloud_engine.config import settings
    from uncloud_engine.library import scan_library

    outside = diffusers_parts(tmp_path / "elsewhere" / "ltx", "LTXVideoTransformer3DModel",
                              extras=False)
    write(outside / "model_index.json", {"_class_name": "LTXPipeline"})
    settings.remember_imported(str(outside))
    assert [m.name for m in scan_library(tmp_path / "never-created")] == ["ltx"]


def test_a_video_pipeline_without_a_marker_opens_with_its_own_family(tmp_path: Path) -> None:
    from uncloud_engine.video_engine import family_for

    wan = diffusers_parts(tmp_path / "unmarked wan", "WanTransformer3DModel",
                          text_encoder="UMT5EncoderModel", extras=False)
    write(wan / "model_index.json", {"_class_name": "WanPipeline"})
    assert family_for(str(wan)).name == "wan"


# ================================================================== routes

@pytest.fixture
def client(models: Path, monkeypatch):
    from fastapi.testclient import TestClient

    from uncloud_engine import main

    saved = dict(main.gate.policy)
    test_client = TestClient(main.app)
    test_client.headers.update({"Authorization": f"Bearer {main.settings.token}"})
    yield main, test_client
    main.gate.policy.update(saved)
    main.gate.forget_session()


def test_inspect_writes_nothing(client, tmp_path: Path) -> None:
    _, http = client
    root = diffusers_parts(tmp_path / "outside" / "ltx", "LTXVideoTransformer3DModel")
    before = sorted(p.name for p in root.iterdir())
    body = http.post("/api/models/inspect", json={"path": str(root)}).json()
    assert body["identification"]["pipeline"] == "LTXPipeline"
    assert body["plan"][0]["action"] == "create"
    assert sorted(p.name for p in root.iterdir()) == before


def test_import_is_gated_as_a_write(client, tmp_path: Path) -> None:
    main, http = client
    main.gate.set_mode(Risk.WRITE, Mode.ASK)
    root = diffusers_parts(tmp_path / "outside" / "ltx", "LTXVideoTransformer3DModel")
    response = http.post("/api/models/import", json={"path": str(root), "name": "LTX"})
    assert response.status_code == 428
    assert not (root / "model_index.json").exists()


def test_import_writes_remembers_and_lists(client, tmp_path: Path) -> None:
    main, http = client
    main.gate.set_mode(Risk.WRITE, Mode.ALLOW)
    root = diffusers_parts(tmp_path / "outside" / "ltx", "LTXVideoTransformer3DModel")
    body = http.post("/api/models/import", json={"path": str(root), "name": "My LTX"}).json()
    assert body["result"]["created"] == ["model_index.json"]
    assert body["verdict"]["runnable"] is True
    assert str(root) in main.settings.imported_models
    manifest = json.loads((root / "uncloud-model.json").read_text())
    assert manifest["licence"]["declared"] == "unknown" and manifest["name"] == "My LTX"
    listed = [m for m in http.get("/api/library").json() if m["path"] == str(root)]
    assert listed and listed[0]["ready"] and "imported" in listed[0]["tags"]

    assert http.post("/api/models/forget", json={"path": str(root)}).json()["forgotten"]
    assert (root / "model_index.json").exists(), "forgetting must not delete files"


def test_online_lookup_is_gated_separately_as_network(client, tmp_path: Path) -> None:
    main, http = client
    main.gate.set_mode(Risk.WRITE, Mode.ALLOW)
    main.gate.set_mode(Risk.NETWORK, Mode.ASK)
    root = diffusers_parts(tmp_path / "outside" / "ltx", "LTXVideoTransformer3DModel")
    response = http.post("/api/models/import", json={"path": str(root), "online": True})
    assert response.status_code == 428
    assert not (root / "model_index.json").exists()


def test_a_paired_device_cannot_touch_the_computers_folders(client, tmp_path: Path) -> None:
    """Only the desktop's bearer token, never a LAN session."""
    _, http = client
    root = diffusers_parts(tmp_path / "outside" / "ltx", "LTXVideoTransformer3DModel")
    for route in ("/api/models/inspect", "/api/models/import", "/api/models/forget"):
        response = http.post(route, json={"path": str(root)}, headers={"Authorization": ""})
        assert response.status_code == 403, route


def test_a_missing_path_is_a_404_not_a_crash(client) -> None:
    _, http = client
    assert http.post("/api/models/inspect", json={"path": "/no/such/model"}).status_code == 404
