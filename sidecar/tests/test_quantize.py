"""Quantising: the refusals, and what survives a failure.

The module this one covers is the shape `training/jobs.py` was built on — and
it was the only module in either engine with no tests at all, which is an
uncomfortable place for the thing everything else was modelled after.

Almost all of it is about refusing early. A quantisation run is tens of
minutes and tens of gigabytes; every mistake worth catching is knowable before
a subprocess is spawned, and the one that is not — a run that dies half way —
must not leave a half-written model where a whole one is supposed to be.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from uncloud_engine import quantize


@pytest.fixture
def manager():
    return quantize.QuantizeManager()


@pytest.fixture
def model(tmp_path):
    """Something that exists on disk. Nothing reads it before the refusals."""
    source = tmp_path / "source-model"
    source.mkdir()
    (source / "model.safetensors").write_bytes(b"0" * 64)
    return source


@pytest.fixture
def quiet(monkeypatch):
    """`start` schedules the real run as a task. These tests are about what it
    refuses and what it reports, so the run itself is replaced — otherwise
    every one of them would try to spawn mflux."""
    async def nothing(self, *args, **kwargs):
        return None

    monkeypatch.setattr(quantize.QuantizeManager, "_run", nothing)


def start(manager, model, tmp_path, **over):
    """Call `start` inside a loop, because it schedules a task.

    The `sleep(0)` lets that task run to completion, so the loop does not close
    over a pending one and fill the output with warnings about it.
    """
    body = dict(source=str(model), base="dev", dest_dir=str(tmp_path / "out"),
                name="Test 6-bit", transformer_bits=6, encoder_bits=6)

    async def go():
        job = manager.start(**{**body, **over})
        await asyncio.sleep(0)
        return job

    return asyncio.run(go())


# ------------------------------------------------------------------ refusals
@pytest.mark.parametrize("bits", [0, 1, 2, 7, 9, 16, -4])
def test_a_precision_mflux_cannot_write_is_refused(manager, model, tmp_path,
                                                   bits, quiet) -> None:
    with pytest.raises(ValueError) as raised:
        start(manager, model, tmp_path, transformer_bits=bits, encoder_bits=bits)
    assert str(quantize.BITS) in str(raised.value)


def test_a_mixed_build_is_refused_with_the_reason_it_cannot_work(
        manager, model, tmp_path, quiet) -> None:
    """The refusal worth having. mflux reads ONE precision per checkpoint and
    applies it to every component, so 8-bit weights beside a 4-bit encoder are
    read at a single width and return nonsense — a model that loads, runs, and
    produces garbage, which is far worse than one that refuses."""
    with pytest.raises(ValueError) as raised:
        start(manager, model, tmp_path, transformer_bits=8, encoder_bits=4)

    message = str(raised.value)
    assert "one precision to every component" in message
    # And it says what to do instead, rather than only what is wrong.
    assert "6-bit" in message


def test_a_uniform_build_at_every_supported_precision_is_accepted(
        manager, model, tmp_path, quiet) -> None:
    for bits in quantize.BITS:
        job = start(manager, model, tmp_path,
                    transformer_bits=bits, encoder_bits=bits)
        assert job.status == "running"


def test_a_source_that_is_not_there_is_refused_before_anything_starts(
        manager, tmp_path) -> None:
    with pytest.raises(FileNotFoundError) as raised:
        manager.start(source=str(tmp_path / "gone"), base="dev",
                      dest_dir=str(tmp_path), name="x",
                      transformer_bits=6, encoder_bits=6)
    assert "gone" in str(raised.value)


def test_nothing_is_registered_when_a_run_is_refused(manager, model,
                                                     tmp_path, quiet) -> None:
    """A refused run that still appeared in the list would read as a job that
    silently failed, and somebody would go looking for a log."""
    with pytest.raises(ValueError):
        start(manager, model, tmp_path, transformer_bits=7, encoder_bits=7)
    assert manager.list_jobs() == []


# -------------------------------------------------------------- job reporting
def test_a_job_reports_enough_to_draw_a_row(manager, model, tmp_path, quiet) -> None:
    job = start(manager, model, tmp_path)
    row = job.to_dict()

    assert row["id"] and row["name"] == "Test 6-bit"
    assert row["status"] == "running" and row["done"] is False
    assert row["dest"].endswith("Test 6-bit")


@pytest.mark.parametrize("status,done", [("running", False), ("done", True),
                                         ("error", True)])
def test_done_means_stopped_not_succeeded(status, done) -> None:
    """An interface that treats `done` as success shows a green tick on a run
    that failed."""
    job = quantize.QuantizeJob(id="x", name="n", dest="d", status=status)
    assert job.to_dict()["done"] is done


def test_the_log_is_trimmed_so_a_long_run_stays_readable() -> None:
    job = quantize.QuantizeJob(id="x", name="n", dest="d")
    job.log = [f"line {i}" for i in range(500)]
    tail = job.to_dict()["log"]

    assert len(tail) == 12
    assert tail[-1] == "line 499", "it kept the beginning rather than the end"


def test_two_jobs_do_not_share_an_id(manager, model, tmp_path, quiet) -> None:
    first = start(manager, model, tmp_path)
    second = start(manager, model, tmp_path, name="Another")
    assert first.id != second.id
    assert len(manager.list_jobs()) == 2


# ------------------------------------------------------- surviving a failure
def test_a_failed_run_leaves_no_half_written_model(manager, model,
                                                   tmp_path, monkeypatch) -> None:
    """The one failure that cannot be refused in advance. A run that dies part
    way must not leave something in the destination that looks like a model —
    the library would offer it, and loading it fails much later and much less
    clearly."""
    async def dies(self, job, source, base, out, bits, lora_paths, lora_scales):
        out.mkdir(parents=True, exist_ok=True)
        (out / "partial.safetensors").write_bytes(b"half")
        raise RuntimeError("quantising at 6-bit failed: out of memory")

    monkeypatch.setattr(quantize.QuantizeManager, "_mflux_save", dies)

    destination = tmp_path / "out"
    job = quantize.QuantizeJob(id="j", name="Test", dest=str(destination / "Test"))
    asyncio.run(manager._run(job, str(model), "dev", destination / "Test",
                             6, 6, [], []))

    assert job.status == "error"
    assert "out of memory" in job.error
    assert not (destination / "Test").exists(), "a broken model was left behind"
    assert not list(destination.glob(".*building")), "staging was left behind"


def test_a_finished_run_writes_the_card_that_says_what_it_is(
        manager, model, tmp_path, monkeypatch) -> None:
    """Without this the result is an anonymous folder of weights, and six weeks
    later nobody can say which model it came from or at what precision."""
    async def succeeds(self, job, source, base, out, bits, lora_paths, lora_scales):
        out.mkdir(parents=True, exist_ok=True)
        (out / "weights.safetensors").write_bytes(b"0" * 32)

    monkeypatch.setattr(quantize.QuantizeManager, "_mflux_save", succeeds)

    destination = tmp_path / "out"
    job = quantize.QuantizeJob(id="j", name="Kontext 6-bit",
                               dest=str(destination / "Kontext 6-bit"))
    asyncio.run(manager._run(job, str(model), "dev",
                             destination / "Kontext 6-bit", 6, 6, [], []))

    assert job.status == "done", job.error
    card = json.loads(
        (destination / "Kontext 6-bit" / quantize.MLX_MARKER).read_text())
    assert card["quantize"] == 6
    assert card["base_model"] == "dev"
    assert card["source"] == str(model)


def test_a_failure_does_not_destroy_the_model_it_was_replacing(
        manager, model, tmp_path, monkeypatch) -> None:
    """Rebuilding over an existing quantisation must not leave the user with
    neither. The destination is only replaced once the new one is complete."""
    async def dies(self, job, source, base, out, bits, lora_paths, lora_scales):
        raise RuntimeError("failed")

    monkeypatch.setattr(quantize.QuantizeManager, "_mflux_save", dies)

    destination = tmp_path / "out" / "Existing"
    destination.mkdir(parents=True)
    (destination / "weights.safetensors").write_bytes(b"the old one")

    job = quantize.QuantizeJob(id="j", name="Existing", dest=str(destination))
    asyncio.run(manager._run(job, str(model), "dev", destination, 6, 6, [], []))

    assert job.status == "error"
    assert (destination / "weights.safetensors").read_bytes() == b"the old one"


# ------------------------------------------------------------------- tooling
def test_a_missing_mflux_is_a_sentence_not_a_traceback(monkeypatch, tmp_path) -> None:
    import sys

    # `quantize` imports sys inside the function, so the real module is the one
    # it reads — patching it here is what the function will see.
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
    monkeypatch.setattr(quantize.shutil, "which", lambda _: None)

    with pytest.raises(RuntimeError) as raised:
        quantize._mflux_save_bin()
    assert "mflux" in str(raised.value)
