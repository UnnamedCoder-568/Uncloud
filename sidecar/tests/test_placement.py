"""Placement: the difference between "does not fit" and "cannot run".

The distinction this module exists for. Before it, a machine whose graphics
card could not hold a whole pipeline was told the model was unsupported —
while the loader two files away already knew how to run exactly that case by
holding one component at a time. The gate and the loader disagreed, and the
gate was the one the user heard.

So most of these tests are about the arrangement being chosen for the right
reason, and about the two cases where the honest answer is still no.
"""

from __future__ import annotations

from uncloud_engine.core.placement import (
    Component,
    Hardware,
    Placement,
    plan,
)


def pipeline(*sizes: float) -> list[Component]:
    return [Component(name=f"part-{n}", gb=gb) for n, gb in enumerate(sizes)]


# ----------------------------------------------------------------- resident
def test_a_model_that_fits_is_never_offloaded() -> None:
    """The rule that protects everybody who already had enough memory. An
    offload for a model that fits buys nothing and costs a copy of itself."""
    made = plan(pipeline(4.0, 2.0), activations_gb=2.0,
                hardware=Hardware(device="cuda", accelerator_gb=24.0, host_gb=32.0))

    assert made.placement is Placement.RESIDENT
    assert made.degraded is False
    assert made.peak_accelerator_gb == 8.0


def test_fitting_exactly_still_counts_as_fitting() -> None:
    made = plan(pipeline(10.0), activations_gb=2.0,
                hardware=Hardware(device="cuda", accelerator_gb=12.0, host_gb=32.0))
    assert made.placement is Placement.RESIDENT


# ------------------------------------------------------- the brief's machine
def test_a_pipeline_larger_than_vram_runs_a_component_at_a_time() -> None:
    """12 GB of VRAM, 32 GB of RAM, a 16 GB pipeline. This is the case the
    whole module exists for: the sum does not fit, the largest part does."""
    made = plan(pipeline(6.0, 6.0, 4.0), activations_gb=2.0,
                hardware=Hardware(device="cuda", accelerator_gb=12.0, host_gb=32.0))

    assert made.placement is Placement.MODEL_OFFLOAD
    assert made.feasible is True
    assert made.degraded is True, "it runs, and it is slower — say both"
    # The peak is the largest part plus the working set, not the sum.
    assert made.peak_accelerator_gb == 8.0
    assert made.peak_host_gb == 16.0


def test_the_reason_names_both_numbers_a_person_would_compare() -> None:
    made = plan(pipeline(6.0, 6.0, 4.0), activations_gb=2.0,
                hardware=Hardware(device="cuda", accelerator_gb=12.0, host_gb=32.0))
    assert "8.0 GB" in made.reason and "18.0 GB" in made.reason


def test_one_component_too_large_for_the_card_falls_to_layer_at_a_time() -> None:
    made = plan(pipeline(20.0, 2.0), activations_gb=2.0,
                hardware=Hardware(device="cuda", accelerator_gb=12.0, host_gb=64.0))

    assert made.placement is Placement.SEQUENTIAL_OFFLOAD
    assert made.feasible is True
    assert "slower" in made.notes[0]


# -------------------------------------------------------------- unified memory
def test_shared_memory_is_never_offered_an_offload() -> None:
    """Apple Silicon. Moving a part to "the CPU" frees nothing because there is
    one pool, so an offload here is a slower way to fail. Encoded once rather
    than left for each caller to remember."""
    made = plan(pipeline(10.0, 8.0), activations_gb=4.0,
                hardware=Hardware(device="mps", accelerator_gb=16.0, host_gb=32.0,
                         unified=True))

    assert made.placement is Placement.INFEASIBLE
    assert made.limited_by == "accelerator"
    assert "same memory" in made.reason


def test_shared_memory_still_runs_what_actually_fits() -> None:
    made = plan(pipeline(6.0), activations_gb=2.0,
                hardware=Hardware(device="mps", accelerator_gb=16.0, host_gb=32.0,
                         unified=True))
    assert made.placement is Placement.RESIDENT


# ------------------------------------------------------- the honest refusals
def test_a_working_set_too_large_for_the_card_cannot_be_arranged_around() -> None:
    """The refusal that matters. No placement helps when what does not fit is
    the data being worked on rather than the weights — and the remedy is a
    smaller frame, which the note says."""
    made = plan(pipeline(4.0), activations_gb=30.0,
                hardware=Hardware(device="cuda", accelerator_gb=12.0, host_gb=64.0))

    assert made.placement is Placement.INFEASIBLE
    assert made.limited_by == "accelerator"
    assert "working set" in made.reason
    assert any("frame size" in n for n in made.notes)


def test_too_little_host_memory_to_offload_into_says_so() -> None:
    """Naming the right resource. "Not enough VRAM" would send somebody to buy
    the wrong thing."""
    made = plan(pipeline(20.0, 20.0), activations_gb=1.0,
                hardware=Hardware(device="cuda", accelerator_gb=24.0, host_gb=8.0))

    assert made.placement is Placement.INFEASIBLE
    assert made.limited_by == "host"
    assert "system memory" in made.reason


def test_host_memory_is_not_counted_to_the_last_byte() -> None:
    """What is reported free is shared with the OS cache and everything else
    running. A plan sized against all of it is a plan that swaps."""
    snug = plan(pipeline(9.0, 9.0), activations_gb=1.0,
                hardware=Hardware(device="cuda", accelerator_gb=12.0, host_gb=19.0))
    assert snug.placement is Placement.INFEASIBLE, "19 GB free is not 19 GB usable"

    roomy = plan(pipeline(9.0, 9.0), activations_gb=1.0,
                 hardware=Hardware(device="cuda", accelerator_gb=12.0, host_gb=32.0))
    assert roomy.placement is Placement.MODEL_OFFLOAD


# ------------------------------------------------------------------ pinning
def test_something_that_cannot_move_is_charged_in_every_placement() -> None:
    """A decode target is written into directly; it cannot be swapped out
    while the operator is using it."""
    made = plan(
        [Component("transformer", 6.0), Component("canvas", 9.0, pinned=True)],
        activations_gb=1.0,
        hardware=Hardware(device="cuda", accelerator_gb=12.0, host_gb=64.0))

    # The component-at-a-time peak is 9 + 6 + 1 = 16 GB, so it cannot fit on
    # this 12 GB card and must fall back to layer-at-a-time placement.
    assert made.placement is Placement.SEQUENTIAL_OFFLOAD
    assert made.peak_accelerator_gb == 11.0

    roomier = plan(
        [Component("transformer", 6.0), Component("encoder", 4.0),
         Component("canvas", 9.0, pinned=True)],
        activations_gb=1.0,
        hardware=Hardware(device="cuda", accelerator_gb=16.0, host_gb=64.0))
    assert roomier.placement is Placement.MODEL_OFFLOAD
    assert roomier.peak_accelerator_gb == 16.0


# ------------------------------------------------------- shape independence
def test_the_planner_does_not_know_what_kind_of_model_it_is() -> None:
    """Dense blocks, a diffusion pipeline and a set of routed experts are the
    same question here: parts with sizes. Nothing branches on the family."""
    dense = plan([Component(f"block-{i}", 1.0) for i in range(16)],
                 activations_gb=2.0,
                 hardware=Hardware(device="cuda", accelerator_gb=12.0, host_gb=32.0))
    diffusion = plan(
        [Component("encoder", 8.0, role="encoder"),
         Component("transformer", 6.0, role="transformer"),
         Component("vae", 2.0, role="decoder")],
        activations_gb=2.0,
        hardware=Hardware(device="cuda", accelerator_gb=12.0, host_gb=32.0))
    experts = plan(
        [Component("shared", 2.0)] + [Component(f"e{i}", 0.5) for i in range(28)],
        activations_gb=2.0,
        hardware=Hardware(device="cuda", accelerator_gb=12.0, host_gb=32.0))

    # Same 16 GB total in all three, so they take the same path — but the peak
    # is set by each shape's largest part, which is the whole reason the
    # planner asks for parts rather than a number.
    assert dense.placement is Placement.MODEL_OFFLOAD
    assert diffusion.placement is Placement.MODEL_OFFLOAD
    assert experts.placement is Placement.MODEL_OFFLOAD

    assert dense.peak_accelerator_gb == 3.0, "sixteen small blocks"
    assert diffusion.peak_accelerator_gb == 10.0, "one fat text encoder"
    assert experts.peak_accelerator_gb == 4.0, "shared weights, small experts"


def test_nothing_described_is_refused_rather_than_assumed_to_fit() -> None:
    made = plan([], activations_gb=1.0,
                hardware=Hardware(device="cuda", accelerator_gb=24.0, host_gb=32.0))
    assert made.placement is Placement.INFEASIBLE


def test_a_plan_serialises_for_an_interface() -> None:
    made = plan(pipeline(6.0, 6.0, 4.0), activations_gb=2.0,
                hardware=Hardware(device="cuda", accelerator_gb=12.0, host_gb=32.0))
    row = made.to_dict()

    assert row["placement"] == "model_offload"
    assert row["feasible"] is True and row["degraded"] is True
    assert row["peak_accelerator_gb"] == 8.0
