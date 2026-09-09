"""Whether this machine can do the training being asked for.

Checked BEFORE anything starts, which is the whole point of the module. A run
that begins because a button was pressed and dies forty minutes later out of
memory has cost somebody their afternoon and taught them not to trust the
feature.

The estimates are rough and say so. Being within a couple of gigabytes
separates "this fits" from "this will take the machine down", and precision
beyond that would be false — the real figure depends on sequence length,
gradient checkpointing and whatever else the user has open.

What it will not do is guess in the permissive direction. An unknown is a no
with a reason, never an optimistic yes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: LoRA trains few extra parameters, but the FORWARD pass still holds the whole
#: model. The floor is the model itself, plus optimiser state for the adapter,
#: plus activations — and activations are the part people forget.
ADAPTER_OVERHEAD_GB = 1.5

#: Activations scale with batch size and sequence length. This figure is for
#: the defaults below; a longer sequence moves it, and the estimate says so
#: rather than pretending one number covers every configuration.
ACTIVATION_GB_PER_BATCH = 0.9

#: Roughly what a 4-bit 7-8B LoRA run moves at on Apple Silicon, in examples a
#: second at the default sequence length. Used only to say how long something
#: will take — never to decide whether to allow it.
EXAMPLES_PER_SECOND = 0.55


@dataclass
class Estimate:
    """What a run would cost, and whether to start it."""

    feasible: bool
    reason: str = ""
    memory_gb: float = 0.0
    budget_gb: float = 0.0
    disk_gb: float = 0.0
    seconds: float = 0.0
    #: Settings that would make it fit, when it does not. None when nothing
    #: would — an offer that cannot help is worse than no offer.
    suggestion: dict | None = None

    @property
    def human_time(self) -> str:
        if self.seconds <= 0:
            return "unknown"
        if self.seconds < 90:
            return f"about {self.seconds:.0f} seconds"
        if self.seconds < 5400:
            return f"about {self.seconds / 60:.0f} minutes"
        return f"about {self.seconds / 3600:.1f} hours"

    def to_dict(self) -> dict:
        return {
            "feasible": self.feasible, "reason": self.reason,
            "memory_gb": round(self.memory_gb, 1),
            "budget_gb": round(self.budget_gb, 1),
            "disk_gb": round(self.disk_gb, 2),
            "seconds": round(self.seconds),
            "time": self.human_time,
            "suggestion": self.suggestion,
        }


def model_size_gb(model_path: str | Path) -> float:
    """What the checkpoint weighs, which is close enough to what it will hold."""
    path = Path(model_path)
    if path.is_file():
        return path.stat().st_size / 1e9
    if not path.is_dir():
        return 0.0
    total = 0
    for child in path.rglob("*"):
        if child.is_file() and child.suffix in (".safetensors", ".bin", ".gguf",
                                                ".npz"):
            total += child.stat().st_size
    return total / 1e9


def estimate(model_path: str | Path, *, examples: int = 0, batch_size: int = 4,
             iterations: int = 600, budget_gb: float | None = None) -> Estimate:
    """Whether to start, how much it will hold, and how long it will take."""
    from ..budget import memory_budget

    weights = model_size_gb(model_path)
    if weights <= 0:
        return Estimate(
            feasible=False,
            reason="Could not work out how large that model is, so there is no "
                   "way to say whether training it will fit. An unknown is not "
                   "a yes.")

    if budget_gb is None:
        budget_gb = float(memory_budget().get("budget_gb") or 0.0)

    needed = weights + ADAPTER_OVERHEAD_GB + ACTIVATION_GB_PER_BATCH * batch_size
    seconds = (iterations * batch_size) / EXAMPLES_PER_SECOND
    # The adapter, plus the checkpoints kept along the way.
    disk = 0.4 + 0.12 * max(1, iterations // 200)

    if budget_gb <= 0:
        return Estimate(
            feasible=False, memory_gb=needed, seconds=seconds, disk_gb=disk,
            reason="This machine's memory could not be measured, so a training "
                   "run cannot be sized. It is refused rather than started "
                   "hopefully.")

    if needed <= budget_gb:
        return Estimate(feasible=True, memory_gb=needed, budget_gb=budget_gb,
                        seconds=seconds, disk_gb=disk)

    # Would a smaller batch bring it inside? Offered only when it genuinely
    # would, because a suggestion that cannot help wastes the reader's
    # attention at the moment they are already being told no.
    smaller = None
    for candidate in (batch_size // 2, 1):
        if candidate >= 1:
            trial = weights + ADAPTER_OVERHEAD_GB + ACTIVATION_GB_PER_BATCH * candidate
            if trial <= budget_gb:
                smaller = {"batch_size": candidate}
                break

    return Estimate(
        feasible=False, memory_gb=needed, budget_gb=budget_gb,
        seconds=seconds, disk_gb=disk, suggestion=smaller,
        reason=(f"Training this would hold about {needed:.1f} GB and this "
                f"machine can spare {budget_gb:.1f} GB."
                + (f" A batch size of {smaller['batch_size']} would fit."
                   if smaller else
                   " No batch size small enough would fit — the model itself is "
                   "too large to train here.")))
