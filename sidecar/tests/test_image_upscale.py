"""Enhancement stays inside Outputs, preserves originals, and queues safely."""

import asyncio
import hashlib
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from PIL import Image

from uncloud_engine import image_upscale as upscale
from uncloud_engine.cancellation import Cancelled


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "outputs"
    root.mkdir()
    source = root / "original.png"
    Image.new("RGB", (65, 63), "blue").save(source)
    return source


def test_only_bounded_still_images_inside_outputs_are_accepted(source, tmp_path):
    assert upscale.validate_source(source, source.parent) == source
    outside = tmp_path / "private.png"
    Image.new("RGB", (4, 4)).save(outside)
    with pytest.raises(ValueError, match="Outputs"):
        upscale.validate_source(outside, source.parent)
    link = source.parent / "escape.png"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this filesystem")
    with pytest.raises(ValueError, match="Outputs"):
        upscale.validate_source(link, source.parent)
    huge = source.parent / "large.png"
    Image.new("RGB", (2049, 2048)).save(huge)
    with pytest.raises(ValueError, match="16 megapixels"):
        upscale.validate_source(huge, source.parent)
    animated = source.parent / "animated.png"
    Image.new("RGB", (4, 4)).save(animated, save_all=True,
                                 append_images=[Image.new("RGB", (4, 4), "red")])
    with pytest.raises(ValueError, match="still"):
        upscale.validate_source(animated, source.parent)


@pytest.fixture
def download(monkeypatch, tmp_path):
    path = tmp_path / "models" / upscale.MODEL_NAME
    raw = b"verified test weights"
    monkeypatch.setattr(upscale, "model_path", lambda: path)
    monkeypatch.setattr(upscale, "MODEL_BYTES", len(raw))
    monkeypatch.setattr(upscale, "MODEL_SHA256", hashlib.sha256(raw).hexdigest())

    def respond(content):
        @contextmanager
        def stream(*args, **kwargs):
            yield httpx.Response(200, request=httpx.Request("GET", upscale.MODEL_URL),
                                 content=content)
        monkeypatch.setattr(httpx, "stream", stream)

    respond(raw)
    return path, raw, respond


def test_download_is_optional_verified_and_reused(download):
    path, raw, _ = download
    with pytest.raises(ValueError, match="Download"):
        upscale.ensure_model(download=False, check=lambda: None, progress=lambda s: None)
    assert not path.exists()
    upscale.ensure_model(download=True, check=lambda: None, progress=lambda s: None)
    assert path.read_bytes() == raw
    assert upscale.model_info()["ready"]
    upscale.ensure_model(download=False, check=lambda: None, progress=lambda s: None)


@pytest.mark.parametrize("wrong", [b"x", b"x" * 100])
def test_bad_download_never_replaces_a_model(download, wrong):
    path, _, respond = download
    path.parent.mkdir()
    path.write_bytes(b"existing")
    respond(wrong)
    with pytest.raises(ValueError, match="integrity|size"):
        upscale.ensure_model(download=True, check=lambda: None, progress=lambda s: None)
    assert path.read_bytes() == b"existing"
    assert not list(path.parent.glob(".*.part"))


def test_cancelled_download_removes_partial_file(download):
    path, _, _ = download
    stopped = False

    def check():
        if stopped:
            raise Cancelled("stopped")

    def progress(message):
        nonlocal stopped
        stopped = True

    with pytest.raises(Cancelled):
        upscale.ensure_model(download=True, check=check, progress=progress)
    assert not path.exists()
    assert not list(path.parent.glob(".*.part"))


def test_enhancement_never_overwrites_the_input(source):
    with pytest.raises(ValueError, match="new image"):
        upscale.enhance(source, source, download=False, cancelled=lambda: False,
                        phase=lambda s: None, progress=lambda n, total: None)


def test_upscale_shares_render_queue_and_does_not_unload_models(monkeypatch, source):
    from uncloud_engine.config import settings
    from uncloud_engine.image_engine import ImageEngine

    monkeypatch.setitem(settings._data, "output_dir", str(source.parent))
    before = source.read_bytes()
    engine = ImageEngine()
    order = []

    async def render(job, *args):
        order.append("render")
        await asyncio.sleep(0.02)
        job.status = "done"

    def enhance(src, dest, **kwargs):
        assert order == ["render", "finished"]
        assert src == source
        assert dest != source
        kwargs["progress"](1, 1)
        Image.open(src).resize((130, 126)).save(dest)
        order.append("enhanced")

    monkeypatch.setattr(engine, "_run_now", render)
    monkeypatch.setattr(upscale, "enhance", enhance)
    monkeypatch.setattr(engine, "_free_memory_for", lambda *a: pytest.fail("unloaded model"))

    async def go():
        engine.start("m", "mflux", "teapot")
        job = engine.start_upscale(str(source))
        await asyncio.sleep(0.01)
        order.append("finished")
        while not job.to_dict()["done"]:
            await asyncio.sleep(0.01)
        return job

    job = asyncio.run(go())
    assert job.status == "done", job.error
    assert order == ["render", "finished", "enhanced"]
    assert job.to_dict()["elapsed_seconds"] >= 0
    assert Path(job.output_path).exists()
    assert source.read_bytes() == before


def test_cancelled_queued_enhancement_does_not_start(monkeypatch, source):
    from uncloud_engine.image_engine import ImageEngine

    engine = ImageEngine()
    monkeypatch.setattr(upscale, "enhance", lambda *a, **kw: pytest.fail("started"))

    async def go():
        async with engine._queue:
            job = engine.start_upscale(str(source))
            engine.cancel(job.id)
        while not job.to_dict()["done"]:
            await asyncio.sleep(0.01)
        return job

    assert asyncio.run(go()).status == "cancelled"


def test_enhancement_route_auth_path_and_job_ownership(monkeypatch, source):
    from fastapi.testclient import TestClient

    from uncloud_engine import main
    from uncloud_engine.core.permission import Mode, Risk
    from uncloud_engine.image_engine import ImageJob

    monkeypatch.setitem(main.settings._data, "output_dir", str(source.parent))
    monkeypatch.setattr(upscale, "model_info", lambda: {"ready": True, "size_bytes": 64})
    monkeypatch.setitem(main.gate.policy, Risk.GENERATE, Mode.ALLOW)

    def start(path, **kw):
        job = ImageJob(id="enhancement-test", prompt="", kind="upscale", source_path=path)
        monkeypatch.setitem(main.image_engine.jobs, job.id, job)
        return job

    monkeypatch.setattr(main.image_engine, "start_upscale", start)
    client = TestClient(main.app)
    assert client.post("/api/image/enhance", json={"source_path": str(source)}).status_code == 401
    client.headers.update({"Authorization": f"Bearer {main.settings.token}"})
    outside = str(source.parent.parent / "x")
    assert client.post("/api/image/enhance", json={"source_path": outside}).status_code == 400
    result = client.post("/api/image/enhance", json={"source_path": str(source)})
    assert result.status_code == 200
    assert result.json()["source_path"] == str(source)
    assert client.get("/api/image/jobs/enhancement-test").status_code == 200
    monkeypatch.setattr(main, "principal_of", lambda request: "lan:other")
    assert client.get("/api/image/jobs/enhancement-test").status_code == 404


@pytest.mark.parametrize("backend", [
    "mflux", "flux2-profile", "diffusers", "gguf-diffusion", "edit"])
def test_automatic_enhancement_finishes_in_the_render_job(monkeypatch, source, backend):
    from uncloud_engine import image_engine as module
    from uncloud_engine import job_events
    from uncloud_engine.config import settings

    monkeypatch.setitem(settings._data, "output_dir", str(source.parent))
    monkeypatch.setattr(module, "verify_image", lambda *a, **kw: None)
    engine = module.ImageEngine()
    freed, finished = [], []
    monkeypatch.setattr(engine, "_free_memory_for", lambda name: freed.append(name))
    monkeypatch.setattr(job_events, "finished", lambda _, job: finished.append(job.to_dict()))
    before = source.read_bytes()

    def render(*a, **kw):
        return str(source)

    async def async_render(*a, **kw):
        return render()

    async def edit(job, *a):
        job.output_path = str(source)

    monkeypatch.setattr(engine, "_run_mflux", async_render)
    monkeypatch.setattr(engine, "_run_flux2_profile", render)
    monkeypatch.setattr(engine, "_run_diffusers", render)
    monkeypatch.setattr(engine, "_edit_with_wake_lock", edit)

    def enhance(src, dest, **kw):
        job = next(iter(engine.jobs.values()))
        assert not job.to_dict()["done"]
        assert not finished
        assert engine._queue.locked()
        assert src == source and dest != source
        kw["phase"]("Enhancing 2× · CPU")
        kw["progress"](1, 1)
        Image.open(src).resize((130, 126)).save(dest)

    monkeypatch.setattr(upscale, "enhance", enhance)

    async def go():
        job = (engine.start_edit("m", "edit", str(source), auto_enhance=True) if backend == "edit"
               else engine.start("m", backend, "test", auto_enhance=True))
        await asyncio.wait_for(asyncio.gather(*engine._tasks), 2)
        return job

    job = asyncio.run(go())
    assert job.status == "done", job.error
    assert job.enhanced and job.original_path == str(source)
    assert Image.open(job.output_path).size == (130, 126)
    assert source.read_bytes() == before
    assert len(finished) == 1 and finished[0]["enhanced"]
    assert len(freed) == (0 if backend == "edit" else 1)


@pytest.mark.parametrize("failure", [RuntimeError("GPU unavailable"), Cancelled("stopped")])
def test_automatic_failure_or_stop_keeps_the_original_ready(monkeypatch, source, failure):
    from uncloud_engine.config import settings
    from uncloud_engine.image_engine import ImageEngine, ImageJob

    monkeypatch.setitem(settings._data, "output_dir", str(source.parent))

    def fail(*a, **kw):
        raise failure

    monkeypatch.setattr(upscale, "enhance", fail)
    job = ImageJob(id="fallback", prompt="test", auto_enhance=True, output_path=str(source))
    asyncio.run(ImageEngine()._enhance_generated(job))
    assert job.output_path == str(source)
    assert job.original_path == str(source) and not job.enhanced
    assert "Original image is ready" in job.enhancement_error


def test_auto_option_off_does_not_load_or_download_enhancement(monkeypatch, source):
    from uncloud_engine.image_engine import ImageEngine, ImageJob

    monkeypatch.setattr(upscale, "enhance", lambda *a, **kw: pytest.fail("enhanced"))
    job = ImageJob(id="normal", prompt="test", output_path=str(source))
    asyncio.run(ImageEngine()._enhance_generated(job))
    assert job.original_path is None and job.output_path == str(source)


def test_original_output_has_the_same_job_ownership_check(monkeypatch, source):
    from fastapi.testclient import TestClient

    from uncloud_engine import main
    from uncloud_engine.image_engine import ImageJob

    enhanced = source.with_name("final.png")
    Image.open(source).resize((130, 126)).save(enhanced)
    job = ImageJob(id="auto-owned", prompt="", status="done", output_path=str(enhanced),
                   original_path=str(source), enhanced=True)
    monkeypatch.setitem(main.image_engine.jobs, job.id, job)
    client = TestClient(main.app)
    client.headers.update({"Authorization": f"Bearer {main.settings.token}"})
    assert client.get("/api/image/output/auto-owned").content == enhanced.read_bytes()
    assert client.get("/api/image/output/auto-owned?original=true").content == source.read_bytes()
    monkeypatch.setattr(main, "principal_of", lambda request: "lan:other")
    assert client.get("/api/image/output/auto-owned?original=true").status_code == 404


def test_auto_download_requires_existing_install_approval_before_queuing(monkeypatch):
    from fastapi.testclient import TestClient

    from uncloud_engine import main
    from uncloud_engine.core.permission import Mode, Risk

    monkeypatch.setattr(upscale, "model_info", lambda: {"ready": False, "size_bytes": 67061725})
    monkeypatch.setitem(main.gate.policy, Risk.INSTALL, Mode.DENY)
    monkeypatch.setattr(main.image_engine, "start",
                        lambda *a, **kw: pytest.fail("queued before approval"))
    client = TestClient(main.app)
    client.headers.update({"Authorization": f"Bearer {main.settings.token}"})
    response = client.post("/api/image/generate", json={
        "model_path": "m", "engine": "mflux", "prompt": "teapot", "auto_enhance": True})
    assert response.status_code == 403
