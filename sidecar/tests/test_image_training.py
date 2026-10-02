"""Native MFlux configuration validation and job lifecycle without loading weights."""

import asyncio
import json
import zipfile
from types import SimpleNamespace

import pytest

from uncloud_engine.training import image_jobs, jobs


@pytest.fixture
def config(tmp_path, monkeypatch):
    pytest.importorskip("mflux")
    from PIL import Image

    from uncloud_engine import budget

    monkeypatch.setattr(budget, "memory_budget", lambda: {"budget_gb": 20})
    monkeypatch.setattr(jobs, "TRAINING_DIR", tmp_path / "training")
    model = tmp_path / "model"
    model.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    Image.new("RGB", (64, 64), "white").save(data / "sample.png")
    (data / "sample.txt").write_text("A white square")
    value = image_jobs.template()["config"]
    value.update(model="z-image", model_path=str(model), data=str(data))
    value["training_loop"]["num_epochs"] = 1
    return value


def test_native_schema_validates_captioned_dataset_without_creating_output(config):
    plan = image_jobs.prepare(config)
    assert plan["examples"] == 1
    assert not (jobs.TRAINING_DIR / "image-validation").exists()


def test_missing_model_refuses_before_job_registration(config):
    config["model_path"] = "/does/not/exist"
    with pytest.raises(jobs.Refused, match="complete local"):
        image_jobs.prepare(config)


def test_memory_pressure_refuses_before_training(config, monkeypatch):
    from uncloud_engine import budget

    monkeypatch.setattr(budget, "memory_budget", lambda: {"budget_gb": 0.1})
    with pytest.raises(jobs.Refused, match="available budget"):
        image_jobs.prepare(config)


def test_training_exports_only_adapter_from_checkpoint(config, tmp_path, monkeypatch):
    from uncloud_engine.engines import engine_manager

    monkeypatch.setattr(engine_manager, "stop", lambda: None)
    output = tmp_path / "output"
    output.mkdir()
    with zipfile.ZipFile(output / "000001_checkpoint.zip", "w") as archive:
        archive.writestr("000001_lora_adapter.safetensors", b"weights")
        archive.writestr("../../escape.txt", b"not extracted")

    async def lines():
        yield b"Step 1\n"

    async def wait():
        return 0

    proc = SimpleNamespace(stdout=lines(), returncode=0, wait=wait)

    async def spawn(*args, **kwargs):
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        assert args[2] == "mflux.models.common.cli.train"
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    job = jobs.TrainingJob(
        id="image-test",
        model_path=config["model_path"],
        dataset_path=config["data"],
        preset="image-lora",
        output_dir=str(output),
        iterations=1,
        examples=1,
    )
    asyncio.run(image_jobs._run(job, output / "config.json"))
    assert job.status == "done", job.error
    assert job.ended_at is not None
    assert (output / "adapter.safetensors").read_bytes() == b"weights"
    assert json.loads((output / "uncloud-adapter.json").read_text())["kind"] == "image"
    assert not (tmp_path / "escape.txt").exists()
