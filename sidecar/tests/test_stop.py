"""Stopping a render that is already going.

A generation is minutes of the whole machine. Until there was a Stop, the only
way out of one started by mistake — the wrong model, four images instead of
one, a 25-step default on a distilled checkpoint — was to quit the app.
"""

from __future__ import annotations

import asyncio
from pathlib import Path


def test_stop_ends_a_render_that_has_not_started(tmp_path: Path) -> None:
    """A batch queues behind one render. Stop has to reach the queue too, or
    pressing it leaves three more generations still to come."""
    from uncloud_engine.image_engine import ImageEngine

    engine = ImageEngine()
    started: list[str] = []

    async def fake_render(job, *args) -> None:
        started.append(job.id)
        job.status = "done"

    engine._run_now = fake_render  # type: ignore[method-assign]

    async def go() -> list:
        jobs = [engine.start("m", "mflux", "a cat", seed=i) for i in range(3)]
        engine.cancel()                       # before the loop runs any of them
        while not all(j.to_dict()["done"] for j in jobs):
            await asyncio.sleep(0.01)
        return jobs

    jobs = asyncio.run(go())

    assert started == []
    assert [j.status for j in jobs] == ["cancelled"] * 3


def test_stopping_one_leaves_the_others(tmp_path: Path) -> None:
    from uncloud_engine.image_engine import ImageEngine

    engine = ImageEngine()

    async def fake_render(job, *args) -> None:
        job.status = "done"

    engine._run_now = fake_render  # type: ignore[method-assign]

    async def go() -> list:
        jobs = [engine.start("m", "mflux", "a cat", seed=i) for i in range(3)]
        stopped = engine.cancel(jobs[1].id)
        assert stopped == [jobs[1].id]
        while not all(j.to_dict()["done"] for j in jobs):
            await asyncio.sleep(0.01)
        return jobs

    jobs = asyncio.run(go())

    assert [j.status for j in jobs] == ["done", "cancelled", "done"]
