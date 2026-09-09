"""Hardware detection: one answer, three platforms, and honest about unknowns.

Detection moved into Core because both products needed the same answer and had
two partial implementations of it — Studio's was cross-platform and Uncloud's
could only describe an Apple Silicon machine. What did NOT move is what a
machine is FOR: Studio's tier and Uncloud's generation budget are product
policies and would be nonsense in the other application.

The tests run against the machine they are on, so they assert on shape and on
the rules rather than on numbers only this laptop would produce. The
platform-specific paths are exercised by stubbing the commands they shell out
to, which is the only way to test a Windows path from a Mac.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uncloud_engine.core import hardware


# ------------------------------------------------------------------- shape
def test_this_machine_is_described_consistently() -> None:
    machine = hardware.detect()
    assert machine.platform in {"darwin", "linux", "windows"}
    assert machine.arch in {"arm64", "x86_64"}
    assert machine.key == f"{machine.platform}-{machine.arch}"
    assert machine.usable_memory_gb > 0, "no machine has zero usable memory"
    assert machine.measured is True


def test_the_usable_figure_is_the_one_a_model_has_to_fit_inside() -> None:
    """Three different answers for three different machines, and picking the
    wrong one produces an out-of-memory crash mid-render."""
    unified = hardware.Machine(platform="darwin", arch="arm64",
                               system_memory_gb=32, unified_memory_gb=32)
    assert unified.usable_memory_gb == 32

    discrete = hardware.Machine(
        platform="linux", arch="x86_64", system_memory_gb=128, vram_gb=48,
        gpus=(hardware.Gpu("A", 24), hardware.Gpu("B", 24)))
    # Not 48. A model that does not fit on one card does not fit at all until
    # sharding exists.
    assert discrete.usable_memory_gb == 24

    cpu_only = hardware.Machine(platform="linux", arch="x86_64",
                                system_memory_gb=64)
    assert cpu_only.usable_memory_gb == 64


def test_a_machine_nothing_could_be_established_about_says_so() -> None:
    """Rather than reporting a zero that downstream code plans around."""
    unknown = hardware.Machine(platform="linux", arch="x86_64")
    assert unknown.measured is False
    assert unknown.usable_memory_gb == 0


def test_cpu_alone_is_not_acceleration() -> None:
    assert hardware.Machine(platform="linux", arch="x86_64",
                            accelerators=("cpu",)).accelerated is False
    assert hardware.Machine(platform="linux", arch="x86_64",
                            accelerators=("cuda",)).accelerated is True


def test_free_disk_is_reported_because_it_is_a_different_failure() -> None:
    """A download that fills the disk needs different advice from one that will
    not fit in memory."""
    assert hardware.disk_free_gb() > 0
    assert hardware.disk_free_gb("/nonexistent/path/anywhere") == 0.0


# ------------------------------------------------------------- the platforms
def test_a_machine_with_nvidia_cards_is_described_by_them(monkeypatch) -> None:
    """Exercised by stubbing what it shells out to, which is the only way to
    test a Linux discrete-GPU path from a Mac."""
    monkeypatch.setattr(hardware._platform, "system", lambda: "Linux")
    monkeypatch.setattr(hardware._platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(hardware._platform, "processor", lambda: "AMD EPYC")
    monkeypatch.setattr(hardware.shutil, "which",
                        lambda name: "/usr/bin/nvidia-smi"
                        if name == "nvidia-smi" else None)
    monkeypatch.setattr(hardware, "_run",
                        lambda cmd: "NVIDIA RTX 6000 Ada, 49140\n"
                                    "NVIDIA RTX 6000 Ada, 49140")

    machine = hardware.detect()
    assert machine.key == "linux-x86_64"
    assert machine.gpu_count == 2
    # nvidia-smi reports MiB, so 49140 MiB is 48 GB rather than 49.1 — the
    # difference between dividing by 1024 and by 1000, and the kind of thing
    # that silently oversizes a job by a couple of gigabytes.
    assert machine.vram_gb == pytest.approx(96.0, abs=0.5)
    # Two cards, and a model still has to fit on one of them.
    assert machine.largest_gpu_gb == pytest.approx(48.0, abs=0.5)
    assert "cuda" in machine.accelerators


def test_a_machine_with_no_gpu_at_all_still_describes_itself(monkeypatch) -> None:
    monkeypatch.setattr(hardware._platform, "system", lambda: "Linux")
    monkeypatch.setattr(hardware._platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(hardware.shutil, "which", lambda name: None)
    monkeypatch.setattr(hardware, "_system_memory_gb", lambda: 16.0)

    machine = hardware.detect()
    assert machine.accelerators == ("cpu",)
    assert machine.accelerated is False
    assert machine.usable_memory_gb == 16.0, "models run in RAM, slowly"


def test_windows_is_a_platform_rather_than_an_afterthought(monkeypatch) -> None:
    """Architecturally supported. Not validated on real hardware — that is a
    separate pass on a Windows machine, and this test does not claim to be it.
    """
    monkeypatch.setattr(hardware._platform, "system", lambda: "Windows")
    monkeypatch.setattr(hardware._platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(hardware.shutil, "which", lambda name: None)
    monkeypatch.setattr(hardware, "_system_memory_gb", lambda: 32.0)

    machine = hardware.detect()
    assert machine.key == "windows-x86_64"
    assert machine.system_memory_gb == 32.0


# ----------------------------------------------------------- what stays apart
def test_core_has_no_opinion_about_what_a_machine_is_for() -> None:
    """The split that made this worth extracting. Studio maps memory onto which
    models to suggest; Uncloud maps it onto a generation budget. Both would be
    nonsense in the other product, so neither is here."""
    text = Path(hardware.__file__).read_text()
    for product_word in ("tier", "Tier", "edition", "campaign", "render"):
        assert f"class {product_word}" not in text
    assert not hasattr(hardware, "classify")


def test_studios_tier_still_works_on_top_of_it() -> None:
    """Delegating detection must not have changed what Studio concludes."""
    pytest.importorskip("adstudio_engine", reason="Studio is not importable here")


def test_the_generation_budget_falls_back_to_core_when_torch_is_absent(
        monkeypatch) -> None:
    """Without torch and psutil this used to report zero, and everything
    downstream refused to plan at all — a machine with no torch could not even
    be told what it had."""
    import builtins

    from uncloud_engine import budget

    real_import = builtins.__import__

    def without(name, *args, **kwargs):
        if name in {"torch", "psutil"}:
            raise ImportError(f"no {name} here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without)
    reported = budget.memory_budget()

    assert reported["total_gb"] > 0
    assert reported["budget_gb"] > 0
    assert reported["machine"]["measured"] is True


def test_the_generation_budget_prefers_torchs_own_ceiling() -> None:
    """Core says what the machine is; torch says what can be allocated now, and
    on Apple Silicon those differ by several gigabytes because Metal will not
    hand out its whole pool."""
    from uncloud_engine import budget

    reported = budget.memory_budget()
    machine = reported["machine"]
    if reported["device"] == "mps":
        assert reported["budget_gb"] <= machine["usable_memory_gb"]
