"""Where a model's parts live, and whether it can run at all.

The question this answers is not "does it fit". It is "does it fit, and if not,
is there an arrangement under which it still runs". Those are different
questions, and conflating them is how a machine gets told a model is
unsupported when the only problem was that all of it could not be resident at
once.

That conflation was real here. `video_capability` decided runnability from the
accelerator budget alone — on CUDA, free VRAM — while the video loader already
called `enable_model_cpu_offload` for exactly the case where the accelerator is
too small. The gate refused jobs the loader would have run.

**Three placements, in order of cost.**

`RESIDENT` is everything on the accelerator, and it is the only fast one. A
model that fits must never be given anything else: offloading a model that fits
buys nothing and costs a copy of itself.

`MODEL_OFFLOAD` keeps one component on the accelerator at a time and the rest
in host memory. The peak becomes the largest single component rather than the
sum, which is what brings a 16 GB pipeline onto a 12 GB card.

`SEQUENTIAL_OFFLOAD` goes further, moving submodules rather than components. It
fits far smaller accelerators and is far slower, so it is a last resort before
refusing.

**Unified memory gets none of them.** On Apple Silicon the CPU and GPU share one
pool, so moving a tensor "to the CPU" frees nothing and costs a real copy —
measured at about 3.4 GB/s on the machine this was written for. There, a model
either fits or it does not, and offering an offload would be offering a slower
way to fail. This module encodes that rather than leaving each caller to
remember it.

Nothing here knows what a model IS. It takes a list of parts with sizes, which
is as true of a dense transformer as of a diffusion pipeline or a set of
routed experts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

#: What a sequential offload still needs on the accelerator beyond activations:
#: one submodule in flight plus the allocator's working room. Deliberately a
#: floor rather than a fraction — the submodules are small and roughly uniform,
#: and a fraction of a large model would claim a saving that does not exist.
SEQUENTIAL_HEADROOM_GB = 1.0

#: Host memory is never entirely available to one process. What is reported
#: free is shared with the operating system's cache and whatever else is
#: running, and a plan sized against all of it is a plan that swaps.
HOST_MARGIN = 0.85


class Placement(StrEnum):
    """How the parts are arranged. Ordered from fastest to slowest."""

    RESIDENT = "resident"
    MODEL_OFFLOAD = "model_offload"
    SEQUENTIAL_OFFLOAD = "sequential_offload"
    INFEASIBLE = "infeasible"


@dataclass(frozen=True)
class Component:
    """One part of a model that can be placed independently.

    `role` is free text and carries no logic — it exists so an interface can
    say "text encoder" rather than "component 2". A transformer block, a VAE, a
    temporal module and a routed expert are all just parts with a size here,
    which is what keeps this from being a diffusion-shaped module.
    """

    name: str
    gb: float
    role: str = ""
    #: Parts that cannot be moved once execution starts — a decode target, or
    #: anything an operator writes into directly. They count against the
    #: accelerator in every placement.
    pinned: bool = False


@dataclass(frozen=True)
class Hardware:
    """What can be allocated right now, not what the machine has.

    The distinction matters: a discrete card is already holding a desktop and a
    compositor, and Metal will not hand out its whole pool.
    """

    device: str                 # mps | cuda | cpu
    accelerator_gb: float
    host_gb: float
    unified: bool = False
    disk_gb: float = 0.0


@dataclass(frozen=True)
class Plan:
    """The arrangement, what it will cost, and why it was chosen."""

    placement: Placement
    peak_accelerator_gb: float = 0.0
    peak_host_gb: float = 0.0
    reason: str = ""
    #: Which resource decided it, when the answer was no. One of
    #: accelerator | host | "" — named so an interface can say what to change.
    limited_by: str = ""
    #: What could not be placed, for a caller that wants to explain itself.
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def feasible(self) -> bool:
        return self.placement is not Placement.INFEASIBLE

    @property
    def degraded(self) -> bool:
        """Whether this will be slower than having the memory for it.

        Reported rather than hidden. A user who is told a model is compatible
        and then waits six minutes for what takes ninety seconds elsewhere has
        been misled, even though nothing failed.
        """
        return self.placement in (Placement.MODEL_OFFLOAD,
                                  Placement.SEQUENTIAL_OFFLOAD)

    def to_dict(self) -> dict:
        return {
            "placement": self.placement.value,
            "feasible": self.feasible,
            "degraded": self.degraded,
            "peak_accelerator_gb": round(self.peak_accelerator_gb, 1),
            "peak_host_gb": round(self.peak_host_gb, 1),
            "reason": self.reason,
            "limited_by": self.limited_by,
            "notes": list(self.notes),
        }


def plan(components: list[Component], activations_gb: float,
         hardware: Hardware) -> Plan:
    """Choose the cheapest arrangement that runs, or say why none does.

    `activations_gb` is the transient working set at the job's worst moment —
    the sequence being denoised, the frame being decoded. It is charged to the
    accelerator under every placement, because it is what the operators are
    actually reading and writing.
    """
    if not components:
        return Plan(Placement.INFEASIBLE, reason="No components were described.")

    total = sum(c.gb for c in components)
    pinned = sum(c.gb for c in components if c.pinned)
    largest = max(c.gb for c in components)
    resident_peak = total + activations_gb
    host_room = hardware.host_gb * HOST_MARGIN

    # ---------------------------------------------------------- fits outright
    if hardware.accelerator_gb and resident_peak <= hardware.accelerator_gb:
        return Plan(Placement.RESIDENT,
                    peak_accelerator_gb=resident_peak,
                    reason="Everything fits at once, so nothing is moved.")

    # ------------------------------------------------------- unified memory
    if hardware.unified:
        # One pool. Moving a part "to the CPU" frees nothing and buys a copy,
        # so there is no arrangement below resident — only a slower failure.
        return Plan(
            Placement.INFEASIBLE,
            peak_accelerator_gb=resident_peak,
            limited_by="accelerator",
            reason=(
                f"This needs about {resident_peak:.1f} GB at once and the "
                f"graphics pool can give {hardware.accelerator_gb:.1f} GB. On "
                f"shared-memory machines there is nowhere cheaper to put the "
                f"rest: the processor and graphics use the same memory, so "
                f"moving part of the model aside frees none of it."),
            notes=("unified memory: offloading is not available here",))

    # --------------------------------------------------- component at a time
    # The peak becomes the largest single part rather than their sum. Anything
    # pinned stays put and is charged on top.
    model_peak = max(largest, pinned) + activations_gb
    if hardware.accelerator_gb and model_peak <= hardware.accelerator_gb:
        if total <= host_room:
            return Plan(
                Placement.MODEL_OFFLOAD,
                peak_accelerator_gb=model_peak, peak_host_gb=total,
                reason=(
                    f"Held one part at a time: {model_peak:.1f} GB on the "
                    f"graphics card instead of {resident_peak:.1f} GB, with "
                    f"{total:.1f} GB waiting in system memory."),
                notes=("slower than resident: parts move between memories "
                       "between stages",))
        return Plan(
            Placement.INFEASIBLE,
            peak_accelerator_gb=model_peak, peak_host_gb=total,
            limited_by="host",
            reason=(
                f"The graphics card could hold this a part at a time, but the "
                f"parts need {total:.1f} GB of system memory to wait in and "
                f"only {hardware.host_gb:.1f} GB is free."))

    # ------------------------------------------------- submodule at a time
    sequential_peak = activations_gb + SEQUENTIAL_HEADROOM_GB + pinned
    if hardware.accelerator_gb and sequential_peak <= hardware.accelerator_gb:
        if total <= host_room:
            return Plan(
                Placement.SEQUENTIAL_OFFLOAD,
                peak_accelerator_gb=sequential_peak, peak_host_gb=total,
                reason=(
                    f"Held a layer at a time — about {sequential_peak:.1f} GB "
                    f"on the graphics card. This runs, and it is considerably "
                    f"slower than having the memory for the whole model."),
                notes=("much slower: every layer is moved for every step",))
        return Plan(
            Placement.INFEASIBLE,
            peak_accelerator_gb=sequential_peak, peak_host_gb=total,
            limited_by="host",
            reason=(
                f"Even a layer at a time, the model needs {total:.1f} GB of "
                f"system memory to wait in and only {hardware.host_gb:.1f} GB "
                f"is free."))

    # --------------------------------------------------------------- no path
    return Plan(
        Placement.INFEASIBLE,
        peak_accelerator_gb=sequential_peak, peak_host_gb=total,
        limited_by="accelerator",
        reason=(
            f"The working set alone needs about {sequential_peak:.1f} GB on "
            f"the graphics card and it can give {hardware.accelerator_gb:.1f} "
            f"GB. No arrangement of the model's parts changes that — what has "
            f"to be resident is the data being worked on, not the weights."),
        notes=("reduce the frame size or the clip length to shrink the "
               "working set",))
