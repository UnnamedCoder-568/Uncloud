"""Several images from one press, and one render at a time.

Product shots were documented as running one after another and were in fact
started together, each loading several gigabytes. The image engine now queues
every render; a batch is just several queued jobs on consecutive seeds.
"""

from __future__ import annotations

import asyncio

import pytest

from uncloud_engine.core.permission import Mode, Risk


def test_renders_wait_for_each_other() -> None:
    from uncloud_engine.image_engine import ImageEngine

    engine = ImageEngine()
    running, most = 0, 0

    async def fake_render(job, *args) -> None:
        nonlocal running, most
        running += 1
        most = max(most, running)
        job.status = "running"
        await asyncio.sleep(0.02)
        job.status = "done"
        running -= 1

    engine._run_now = fake_render  # type: ignore[method-assign]
    engine._run_edit_now = fake_render  # type: ignore[method-assign]

    async def go() -> list:
        jobs = [engine.start("m", "mflux", "a cat", seed=i) for i in range(3)]
        jobs.append(engine.start_edit("m", "a dog", "ref.png", seed=9))
        while not all(j.status == "done" for j in jobs):
            await asyncio.sleep(0.01)
        return jobs

    jobs = asyncio.run(go())
    assert most == 1
    assert [j.seed for j in jobs] == [0, 1, 2, 9]


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from uncloud_engine import main

    started: list[dict] = []

    def fake_start(model_path, engine, prompt, **kwargs):
        from uncloud_engine.image_engine import ImageJob

        job = ImageJob(id=f"j{len(started)}", prompt=prompt, label=kwargs.get("label"),
                       seed=kwargs.get("seed"))
        started.append(kwargs)
        return job

    monkeypatch.setattr(main.image_engine, "start", fake_start)
    saved = dict(main.gate.policy)
    main.gate.set_mode(Risk.GENERATE, Mode.ALLOW)
    http = TestClient(main.app)
    http.headers.update({"Authorization": f"Bearer {main.settings.token}"})
    yield http, started
    main.gate.policy.update(saved)


def test_a_batch_is_consecutive_seeds_labelled_in_order(client) -> None:
    http, started = client
    body = http.post("/api/image/generate", json={
        "model_path": "m", "engine": "mflux", "prompt": "a lighthouse", "count": 3,
        "seed": 41}).json()
    assert [j["seed"] for j in body["batch"]] == [41, 42, 43]
    assert [j["label"] for j in body["batch"]] == ["1 of 3", "2 of 3", "3 of 3"]
    assert body["id"] == body["batch"][0]["id"]


def test_a_random_batch_still_records_every_seed(client) -> None:
    http, _ = client
    body = http.post("/api/image/generate", json={
        "model_path": "m", "engine": "mflux", "prompt": "a lighthouse", "count": 2}).json()
    first, second = (j["seed"] for j in body["batch"])
    assert isinstance(first, int) and second == first + 1


def test_one_image_is_unlabelled_and_a_huge_batch_is_refused(client) -> None:
    http, _ = client
    one = http.post("/api/image/generate", json={
        "model_path": "m", "engine": "mflux", "prompt": "x"}).json()
    assert one["label"] is None and len(one["batch"]) == 1
    too_many = http.post("/api/image/generate", json={
        "model_path": "m", "engine": "mflux", "prompt": "x", "count": 9})
    assert too_many.status_code == 400
