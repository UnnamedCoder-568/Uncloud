"""Training: refusing early, and refusing for a reason.

Almost everything here is about the same failure. A fine-tune on a bad dataset,
or on a machine that cannot hold the model, does not fail cleanly — it either
dies forty minutes in, or succeeds and produces an adapter that quietly makes
the model worse. Both cost somebody an afternoon and neither leaves a signal
they can act on.

So the tests are mostly about what happens BEFORE a subprocess is spawned.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from uncloud_engine.training import datasets, feasibility, jobs


def fake_model(path: Path, gigabytes: float) -> Path:
    """A checkpoint of a given size, without writing it.

    Sparse. Writing forty gigabytes of zeros to test a size check would make
    the suite slower than the thing it is testing, and on a full disk it would
    fail for the wrong reason.
    """
    path.write_bytes(b"0")
    os.truncate(path, int(gigabytes * 1e9))
    return path


def write_jsonl(path: Path, records: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def chat(n: int) -> list[dict]:
    return [{"messages": [{"role": "user", "content": f"question {i}"},
                          {"role": "assistant", "content": f"answer {i}"}]}
            for i in range(n)]


# ----------------------------------------------------------------- reading
def test_both_common_shapes_are_read(tmp_path) -> None:
    path = write_jsonl(tmp_path / "d.jsonl", [
        {"messages": [{"role": "user", "content": "hi"},
                      {"role": "assistant", "content": "hello"}]},
        {"prompt": "hi again", "completion": "hello again"},
        {"text": "a plain completion example"},
    ])
    dataset = datasets.read(path)
    assert dataset.count == 3
    assert dataset.usable is True


def test_a_bad_line_is_reported_with_its_line_number(tmp_path) -> None:
    """Reported rather than skipped. A file where a third of the lines were
    silently dropped trains on a third of what its author intended, and the
    only symptom is an adapter that underperforms for no visible reason."""
    path = tmp_path / "d.jsonl"
    path.write_text('{"prompt": "a", "completion": "b"}\nnot json at all\n'
                    '{"messages": []}\n')
    dataset = datasets.read(path)
    assert dataset.count == 1
    assert [p.line for p in dataset.problems] == [2, 3]
    assert "not valid JSON" in dataset.problems[0].what


def test_an_empty_turn_is_a_problem_not_an_example(tmp_path) -> None:
    path = write_jsonl(tmp_path / "d.jsonl", [
        {"messages": [{"role": "user", "content": "hi"},
                      {"role": "assistant", "content": "   "}]}])
    dataset = datasets.read(path)
    assert dataset.count == 0
    assert "assistant turn is empty" in dataset.problems[0].what


def test_a_missing_file_is_fatal(tmp_path) -> None:
    dataset = datasets.read(tmp_path / "nothing.jsonl")
    assert dataset.usable is False
    assert dataset.problems[0].fatal is True


def test_an_empty_file_is_fatal(tmp_path) -> None:
    path = tmp_path / "d.jsonl"
    path.write_text("")
    assert datasets.read(path).usable is False


# ---------------------------------------------------------------- warnings
def test_a_tiny_dataset_warns_rather_than_refuses(tmp_path) -> None:
    """Somebody testing the pipeline with ten examples is doing something
    reasonable. What is not acceptable is letting them do it unknowingly."""
    dataset = datasets.read(write_jsonl(tmp_path / "d.jsonl", chat(10)))
    assert dataset.usable is True
    assert any("very few" in w for w in dataset.warnings)


def test_a_repetitive_dataset_is_flagged(tmp_path) -> None:
    """A fine-tune on a repetitive set learns the repetition."""
    same = {"messages": [{"role": "user", "content": "same"},
                         {"role": "assistant", "content": "same"}]}
    dataset = datasets.read(write_jsonl(tmp_path / "d.jsonl", [same] * 80))
    assert dataset.variety < 0.1
    assert any("distinct" in w for w in dataset.warnings)


def test_a_varied_dataset_is_not_flagged(tmp_path) -> None:
    dataset = datasets.read(write_jsonl(tmp_path / "d.jsonl", chat(80)))
    assert dataset.variety == 1.0
    assert dataset.warnings == []


def test_examples_that_will_be_truncated_are_counted(tmp_path) -> None:
    long = {"messages": [{"role": "user", "content": "x" * 9000},
                         {"role": "assistant", "content": "y"}]}
    dataset = datasets.read(write_jsonl(tmp_path / "d.jsonl", chat(60) + [long]))
    assert any("truncated" in w for w in dataset.warnings)


# ------------------------------------------------------------------- split
def test_the_holdout_is_the_same_every_run(tmp_path) -> None:
    """A validation set that changes between runs makes two runs incomparable,
    which is the whole reason to have one."""
    dataset = datasets.read(write_jsonl(tmp_path / "d.jsonl", chat(100)))
    first = datasets.split(dataset)[1]
    second = datasets.split(dataset)[1]
    assert [e.signature for e in first] == [e.signature for e in second]


def test_a_tiny_set_is_not_split_into_nothing(tmp_path) -> None:
    dataset = datasets.read(write_jsonl(tmp_path / "d.jsonl", chat(6)))
    train, held = datasets.split(dataset)
    assert len(train) == 6 and held == []


def test_examples_round_trip_through_the_trainers_format(tmp_path) -> None:
    dataset = datasets.read(write_jsonl(tmp_path / "d.jsonl", chat(20)))
    out = datasets.write(dataset.examples, tmp_path / "train.jsonl")
    assert datasets.read(out).count == 20


# ------------------------------------------------------------ feasibility
def test_an_unmeasurable_model_is_a_no_rather_than_an_optimistic_yes() -> None:
    guess = feasibility.estimate("/does/not/exist", budget_gb=64.0)
    assert guess.feasible is False
    assert "not a yes" in guess.reason


def test_a_machine_whose_memory_is_unknown_refuses(tmp_path) -> None:
    model = fake_model(tmp_path / "model.safetensors", 2.0)
    assert feasibility.estimate(model, budget_gb=0.0).feasible is False


def test_a_model_that_fits_is_allowed(tmp_path) -> None:
    model = fake_model(tmp_path / "model.safetensors", 2.0)
    guess = feasibility.estimate(model, budget_gb=19.0, batch_size=4)
    assert guess.feasible is True
    assert guess.memory_gb > 0 and guess.seconds > 0


def test_a_model_that_does_not_fit_suggests_a_batch_size_that_would(tmp_path) -> None:
    model = fake_model(tmp_path / "model.safetensors", 12.0)
    guess = feasibility.estimate(model, budget_gb=15.0, batch_size=4)
    assert guess.feasible is False
    assert guess.suggestion == {"batch_size": 1}


def test_a_model_too_large_for_any_batch_size_offers_nothing(tmp_path) -> None:
    """A suggestion that cannot help wastes the reader's attention at the
    moment they are already being told no."""
    model = fake_model(tmp_path / "model.safetensors", 40.0)
    guess = feasibility.estimate(model, budget_gb=15.0, batch_size=4)
    assert guess.suggestion is None
    assert "too large to train here" in guess.reason


def test_the_time_estimate_is_readable() -> None:
    assert "seconds" in feasibility.Estimate(True, seconds=30).human_time
    assert "minutes" in feasibility.Estimate(True, seconds=900).human_time
    assert "hours" in feasibility.Estimate(True, seconds=9000).human_time
    assert feasibility.Estimate(False).human_time == "unknown"


# ------------------------------------------------------------------- jobs
def test_the_presets_are_named_for_what_they_do() -> None:
    """Nobody arriving at this feature knows what a sensible rank is."""
    for preset in jobs.presets():
        assert preset["label"] and preset["note"]
        assert preset["iterations"] > 0 and preset["rank"] > 0


def test_an_unknown_preset_is_refused(tmp_path) -> None:
    with pytest.raises(jobs.Refused):
        jobs.prepare("/model", str(tmp_path / "d.jsonl"), "aggressive")


def test_preparing_reports_the_dataset_and_the_cost_without_starting(tmp_path) -> None:
    """Called before the button is offered, so a run that cannot work is
    explained while the user is still deciding."""
    path = write_jsonl(tmp_path / "d.jsonl", chat(80))
    plan = jobs.prepare("/does/not/exist", str(path))
    assert plan["dataset"]["count"] == 80
    assert plan["estimate"]["feasible"] is False
    assert plan["preset"]["id"] == "standard"


def test_an_unusable_dataset_is_refused_before_anything_spawns(tmp_path) -> None:
    empty = tmp_path / "d.jsonl"
    empty.write_text("")
    with pytest.raises(jobs.Refused) as raised:
        asyncio.run(jobs.start("/model", str(empty)))
    assert "cannot be trained on" in str(raised.value)


def test_a_machine_that_cannot_hold_the_model_is_refused(tmp_path) -> None:
    """The refusal this module exists for. A run that dies forty minutes in has
    cost somebody their afternoon."""
    path = write_jsonl(tmp_path / "d.jsonl", chat(80))
    model = fake_model(tmp_path / "model.safetensors", 40.0)
    with pytest.raises(jobs.Refused) as raised:
        asyncio.run(jobs.start(str(model), str(path)))
    assert "GB" in str(raised.value)


def test_cancelling_a_job_that_does_not_exist_is_not_an_error() -> None:
    assert jobs.cancel("nope") is False


def test_an_adapter_card_says_what_it_belongs_to(tmp_path, monkeypatch) -> None:
    """An adapter with no provenance is unusable six weeks later. It travels
    with the weights, so copying the folder copies the answer."""
    monkeypatch.setattr(jobs, "TRAINING_DIR", tmp_path)
    output = tmp_path / "adapters" / "test-adapter"
    output.mkdir(parents=True)
    (output / "adapters.safetensors").write_bytes(b"0" * 100)

    job = jobs.TrainingJob(id="x", model_path="/models/qwen", dataset_path="/d.jsonl",
                           preset="standard", output_dir=str(output),
                           iterations=600, examples=80)
    jobs._write_card(job)

    card = json.loads((output / "uncloud-adapter.json").read_text())
    assert card["base_model"] == "/models/qwen"
    assert card["examples"] == 80
    assert "not a model" in card["note"]

    listed = jobs.adapters()
    assert listed and listed[0]["ready"] is True


def test_forgetting_only_ever_touches_an_adapter_uncloud_trained(tmp_path,
                                                                 monkeypatch) -> None:
    monkeypatch.setattr(jobs, "TRAINING_DIR", tmp_path)
    (tmp_path / "adapters").mkdir(parents=True)
    assert jobs.forget("../../etc") is False
    assert jobs.forget("nothing-here") is False


def test_progress_is_read_from_the_trainers_own_output() -> None:
    """A progress bar driven by a clock is a lie the moment the machine gets
    busy, and this is exactly the kind of job somebody walks away from."""
    job = jobs.TrainingJob(id="x", model_path="m", dataset_path="d",
                           preset="standard", output_dir="o", iterations=600)
    jobs._absorb(job, "Iter 120: Train loss 1.842, Learning Rate 1.000e-05")
    jobs._absorb(job, "Iter 120: Val loss 1.913, Val took 2.1s")
    assert job.iteration == 120
    assert job.train_loss == 1.842
    assert job.val_loss == 1.913
    assert 19 < job.percent < 21


def test_a_failure_reports_the_line_a_person_can_act_on() -> None:
    log = ["Traceback (most recent call last):",
           '  File "/x/y.py", line 3, in <module>',
           "    train()",
           "ValueError: expected 2 dimensions, got 3"]
    assert jobs._why(log) == "ValueError: expected 2 dimensions, got 3"
