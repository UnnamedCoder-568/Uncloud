"""Resident models must not retain completed jobs' callbacks."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from uncloud_engine.cancellation import Cancelled
from uncloud_engine.mflux_runtime import MfluxRuntime


class Registry:
    def __init__(self):
        self.in_loop = []
        self.before_loop = []
        self.after_loop = []

    def register(self, callback):
        self.in_loop.append(callback)
        if hasattr(callback, "call_before_loop"):
            self.before_loop.append(callback)
        if hasattr(callback, "call_after_loop"):
            self.after_loop.append(callback)


@pytest.fixture
def resident(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "mflux.callbacks.callback_registry",
                        SimpleNamespace(CallbackRegistry=Registry))
    registry = Registry()
    vendor = SimpleNamespace(call_in_loop=lambda **kw: None)
    registry.register(vendor)
    image = SimpleNamespace(save=lambda path: Path(path).write_bytes(b"image"))
    model = SimpleNamespace(callbacks=registry, failure=None)

    def generate(**kw):
        for callback in registry.before_loop:
            callback.call_before_loop()
        for callback in list(registry.in_loop):
            callback.call_in_loop(t=0, seed=kw["seed"], prompt=kw["prompt"],
                                  latents=None, config=None, time_steps=None)
        if model.failure:
            raise model.failure
        for callback in registry.after_loop:
            callback.call_after_loop()
        return image

    model.generate_image = generate
    runtime = MfluxRuntime()
    builds = []

    def build(*args):
        builds.append(args)
        return model

    monkeypatch.setattr(runtime, "_build", build)

    def render(on_step=None, on_phase=None):
        return runtime.generate(
            cli="mflux-generate-flux2-klein", model_path="unchanged-model",
            prompt="a teapot", seed=42, steps=4, width=512, height=512,
            guidance=1, out_path=tmp_path / "image.png", on_step=on_step,
            on_phase=on_phase,
        )

    return SimpleNamespace(render=render, registry=registry, vendor=vendor,
                           model=model, image=image, builds=builds)


def test_each_job_only_receives_its_own_progress(resident):
    progress = [[] for _ in range(5)]
    for received in progress:
        resident.render(received.append)
        assert resident.registry.in_loop == [resident.vendor]
        assert resident.registry.before_loop == resident.registry.after_loop == []
    resident.render()
    assert progress == [[1]] * 5
    assert len(resident.builds) == 1


@pytest.mark.parametrize("failure", [Cancelled("stopped"), RuntimeError("render failed")])
def test_failed_job_does_not_leak_callback(resident, failure):
    resident.model.failure = failure
    with pytest.raises(type(failure)):
        resident.render(lambda n: None)
    assert resident.registry.in_loop == [resident.vendor]
    resident.model.failure = None
    resident.render()


def test_old_cancellation_does_not_stop_the_next_render(resident):
    def stop(n):
        raise Cancelled("stopped")

    with pytest.raises(Cancelled):
        resident.render(stop)
    received = []
    resident.render(received.append)
    assert received == [1]
    assert resident.registry.in_loop == [resident.vendor]


def test_save_failure_still_removes_job_callback(resident):
    def fail(path):
        raise OSError("disk full")

    resident.image.save = fail
    with pytest.raises(OSError, match="disk full"):
        resident.render(lambda n: None)
    assert resident.registry.in_loop == [resident.vendor]


def test_reports_actual_decode_and_save_phases_and_releases_hooks(resident):
    phases = []
    resident.render(on_phase=phases.append)
    assert phases == ["Loading model", "Reading prompt", "Rendering", "Decoding image",
                      "Saving image"]
    assert resident.registry.before_loop == resident.registry.after_loop == []
