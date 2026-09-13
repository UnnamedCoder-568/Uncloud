"""Recasting a component to the precision it is already used at.

Measured on LTX: a 19 GB float32 text encoder that every load converts to
bfloat16 before touching. Nineteen seconds of reading at the 1.0 GB/s this
drive does, to produce nine and a half gigabytes — the rest read, converted
and discarded, on every cold start.

The tests are mostly about refusing. This is the rare optimisation with no
trade to weigh, which makes it exactly the kind that gets applied somewhere it
does not belong — to something already narrow, or to a model where a half
written copy would be discovered on a user's machine rather than here.
"""

from __future__ import annotations

import json

import pytest

torch = pytest.importorskip("torch")
safetensors = pytest.importorskip("safetensors.torch")

from uncloud_engine import recast as recast_module  # noqa: E402


def build(root, *, dtype="float32", component="text_encoder", shards=2,
          config=True):
    folder = root / component
    folder.mkdir(parents=True, exist_ok=True)
    torch_dtype = getattr(torch, dtype) if hasattr(torch, dtype) else torch.float32
    for n in range(shards):
        safetensors.save_file(
            {f"layer{n}.weight": torch.ones(64, 64, dtype=torch_dtype),
             f"layer{n}.count": torch.tensor([n], dtype=torch.int64)},
            str(folder / f"model-{n}.safetensors"), metadata={"format": "pt"})
    if config:
        (folder / "config.json").write_text(json.dumps({"torch_dtype": dtype}))
    (folder / "tokenizer_stub.txt").write_text("carried across unchanged")
    return folder


# ------------------------------------------------------------------ refusing
def test_a_component_already_at_bfloat16_is_left_alone(tmp_path) -> None:
    build(tmp_path, dtype="bfloat16")
    found = recast_module.inspect(tmp_path)
    assert found.skipped and "already stored" in found.skipped


def test_a_missing_component_is_reported_not_raised(tmp_path) -> None:
    found = recast_module.inspect(tmp_path, "does_not_exist")
    assert found.skipped and found.written is None


def test_a_component_with_no_config_is_left_alone(tmp_path) -> None:
    """Without a declared dtype there is nothing to say the stored precision
    is wasteful, and guessing from the tensors would recast things that were
    float32 on purpose."""
    build(tmp_path, config=False)
    assert recast_module.inspect(tmp_path).skipped


def test_nothing_is_ever_recast_to_something_narrower(tmp_path) -> None:
    """Quantisation wearing this function's clothes. float16 is not widened
    to bfloat16 and nothing goes below it."""
    build(tmp_path, dtype="float16")
    assert recast_module.inspect(tmp_path).skipped


# -------------------------------------------------------------- the estimate
def test_the_saving_is_half_the_weights(tmp_path) -> None:
    """Asserted on the bytes rather than the reported GB: the fixture's
    tensors are kilobytes and `saved_gb` rounds to two decimals, which is the
    right resolution for a figure shown to a person and the wrong one to test
    arithmetic with."""
    folder = build(tmp_path)
    found = recast_module.inspect(tmp_path)
    assert not found.skipped

    weights = sum(f.stat().st_size for f in folder.glob("*.safetensors"))
    shrink = (found.before_gb - found.after_gb) * 1e9
    assert abs(shrink - weights / 2) < weights * 0.05


def test_a_real_sized_saving_is_reported_in_whole_gigabytes(tmp_path) -> None:
    """What a person actually sees. Constructed rather than measured, so it
    checks the reporting and not the drive."""
    found = recast_module.Recast(component="text_encoder", source=tmp_path,
                                 before_gb=19.0, after_gb=9.5)
    assert found.saved_gb == 9.5
    assert found.worthwhile is True


# ------------------------------------------------------------------- doing it
def test_the_original_is_never_touched(tmp_path) -> None:
    """A model is somebody's download, often tens of gigabytes over a slow
    connection. Removing it is their decision, not this function's."""
    folder = build(tmp_path)
    before = sorted(p.name for p in folder.iterdir())

    found = recast_module.recast(tmp_path)
    assert found.written is not None
    assert sorted(p.name for p in folder.iterdir()) == before
    assert json.loads((folder / "config.json").read_text())["torch_dtype"] == "float32"


def test_the_copy_is_bfloat16_and_says_so(tmp_path) -> None:
    build(tmp_path)
    found = recast_module.recast(tmp_path)

    written = safetensors.load_file(str(found.written / "model-0.safetensors"))
    assert written["layer0.weight"].dtype is torch.bfloat16

    config = json.loads((found.written / "config.json").read_text())
    assert config["torch_dtype"] == "bfloat16", \
        "a copy that does not declare its precision will be reconverted on load"


def test_integers_are_not_turned_into_floats(tmp_path) -> None:
    """Token ids, position indices and the like are not weights. Casting them
    would corrupt the model in a way that only shows up as bad output."""
    build(tmp_path)
    found = recast_module.recast(tmp_path)
    written = safetensors.load_file(str(found.written / "model-0.safetensors"))
    assert written["layer0.count"].dtype is torch.int64


def test_every_tensor_survives_with_its_shape(tmp_path) -> None:
    build(tmp_path, shards=3)
    found = recast_module.recast(tmp_path)
    for n in range(3):
        before = safetensors.load_file(str(tmp_path / "text_encoder" / f"model-{n}.safetensors"))
        after = safetensors.load_file(str(found.written / f"model-{n}.safetensors"))
        assert set(before) == set(after)
        assert all(before[k].shape == after[k].shape for k in before)


def test_the_files_that_are_not_weights_travel_across(tmp_path) -> None:
    build(tmp_path)
    found = recast_module.recast(tmp_path)
    assert (found.written / "tokenizer_stub.txt").read_text() == \
        "carried across unchanged"


def test_a_half_written_copy_is_never_left_behind(tmp_path, monkeypatch) -> None:
    """It would fail at load time on somebody's machine rather than here."""
    build(tmp_path)
    real = safetensors.save_file

    calls = {"n": 0}

    def fails_partway(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("the disk filled up")
        return real(*args, **kwargs)

    monkeypatch.setattr(safetensors, "save_file", fails_partway)
    with pytest.raises(OSError):
        recast_module.recast(tmp_path)

    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert leftovers == [], f"staging was left behind: {leftovers}"
