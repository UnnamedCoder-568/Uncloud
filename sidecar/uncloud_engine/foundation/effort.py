"""One control for how hard to think, translated per model.

THIS FILE IS BYTE-IDENTICAL IN BOTH REPOSITORIES. See `capability.py` for the
rules it lives by.

The user picks Fast, Balanced, Deep or Maximum. What that buys depends entirely
on what is loaded, and the whole difficulty is that **most local models expose
no reasoning parameter at all**. Of everything in either catalogue, one family
takes a reasoning control; the rest take a token budget and nothing else.

So effort is not a knob that gets forwarded. It is a budget spent on whatever
the model in front of us can actually be sold:

    native reasoning     where the chat template accepts one
    output budget        everywhere
    orchestration passes re-planning after a failure
    reviewer pass        a second look before answering
    tool iterations      how long a loop may keep working
    candidates           generate several, compare, keep the best

A model with no reasoning control still gets more from Maximum than from Fast —
it gets more passes, a reviewer and more room to answer in. That is the point of
translating rather than forwarding.

**Nothing degrades silently.** Where a level asks for something a model cannot
do, the plan says so in `degraded`, and the interface is expected to show it. A
setting that appears to work and does nothing is worse than one that says it is
unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .capability import ModelProfile, ReasoningSupport, RuntimeProfile, runtime_profile


class Effort(StrEnum):
    """How much to spend. The only thing a user chooses."""

    FAST = "fast"
    BALANCED = "balanced"
    DEEP = "deep"
    MAXIMUM = "maximum"


ORDER: tuple[Effort, ...] = (Effort.FAST, Effort.BALANCED, Effort.DEEP, Effort.MAXIMUM)

LABELS: dict[Effort, str] = {
    Effort.FAST: "Fast",
    Effort.BALANCED: "Balanced",
    Effort.DEEP: "Deep",
    Effort.MAXIMUM: "Maximum",
}

BLURBS: dict[Effort, str] = {
    Effort.FAST: "One pass. Answers quickly and does not check its work.",
    Effort.BALANCED: "Re-plans when a step fails. The sensible default.",
    Effort.DEEP: "Thinks first where the model can, and reviews before answering.",
    Effort.MAXIMUM: "Tries several approaches and compares them. Slow on purpose.",
}


@dataclass(frozen=True)
class Budget:
    """What one effort level buys, before a model is taken into account."""

    #: Extra room to answer in, as a multiple of the model's normal ceiling.
    output_scale: float
    #: How many times the orchestrator may re-plan after a failure.
    passes: int
    #: Whether a second model call looks at the answer before it is returned.
    reviewer: bool
    #: How many tool calls one turn may make before it must answer.
    tool_iterations: int
    #: How many attempts to generate and compare. 1 means no comparison.
    candidates: int
    #: Fraction of the model's context to spend on private reasoning, where the
    #: model bills for it separately.
    reasoning_share: float


#: Chosen to be felt rather than measured — the difference between levels has to
#: be visible in the result or the control is decoration. Fast is genuinely one
#: pass; Maximum is expected to take minutes.
BUDGETS: dict[Effort, Budget] = {
    Effort.FAST: Budget(output_scale=1.0, passes=1, reviewer=False,
                        tool_iterations=3, candidates=1, reasoning_share=0.0),
    Effort.BALANCED: Budget(output_scale=1.0, passes=2, reviewer=False,
                            tool_iterations=6, candidates=1, reasoning_share=0.0),
    Effort.DEEP: Budget(output_scale=1.5, passes=3, reviewer=True,
                        tool_iterations=12, candidates=1, reasoning_share=0.25),
    Effort.MAXIMUM: Budget(output_scale=2.0, passes=4, reviewer=True,
                           tool_iterations=20, candidates=3, reasoning_share=0.4),
}

#: What a model is given to answer in when nothing else says. Deliberately
#: generous: a reply cut off mid-sentence reads as a broken application, and the
#: cost of an unused ceiling is nothing.
BASE_OUTPUT_TOKENS = 2048


@dataclass(frozen=True)
class Plan:
    """What this effort level means for this model, concretely.

    Everything a caller needs to build a request and to explain the result. The
    two lists at the end are the honesty: `applied` is what the level actually
    bought, `degraded` is what it could not.
    """

    effort: Effort
    #: Parameters to merge into the model request. Only ever things the runtime
    #: and template are known to accept.
    parameters: dict = field(default_factory=dict)
    max_output_tokens: int = BASE_OUTPUT_TOKENS
    passes: int = 1
    reviewer: bool = False
    tool_iterations: int = 3
    candidates: int = 1
    applied: tuple[str, ...] = ()
    #: What was asked for and could not be given, in the user's terms.
    degraded: tuple[str, ...] = ()

    @property
    def thinks(self) -> bool:
        """Whether the model itself will reason, as opposed to being asked
        more times."""
        return "reasoning" in self.applied

    def to_dict(self) -> dict:
        return {
            "effort": self.effort.value,
            "label": LABELS[self.effort],
            "parameters": dict(self.parameters),
            "max_output_tokens": self.max_output_tokens,
            "passes": self.passes,
            "reviewer": self.reviewer,
            "tool_iterations": self.tool_iterations,
            "candidates": self.candidates,
            "applied": list(self.applied),
            "degraded": list(self.degraded),
            "thinks": self.thinks,
        }


def parse(value: str | Effort | None, *, default: Effort = Effort.BALANCED) -> Effort:
    """Read an effort level from anywhere, falling back rather than raising.

    Effort is a preference, and an unreadable preference should not be able to
    fail a job. The fallback is Balanced, which is the level a user who has
    never touched the control would want.
    """
    if isinstance(value, Effort):
        return value
    try:
        return Effort(str(value or "").strip().lower())
    except ValueError:
        return default


def translate(effort: Effort | str, model: ModelProfile | None = None, *,
              runtime: RuntimeProfile | None = None,
              base_output_tokens: int = BASE_OUTPUT_TOKENS) -> Plan:
    """Turn one chosen level into a concrete plan for one model.

    `model` may be None — nothing is loaded yet, or the caller only wants the
    orchestration side. The plan is still valid; it simply buys no native
    reasoning, which is the same answer most models give anyway.
    """
    effort = parse(effort)
    budget = BUDGETS[effort]
    runtime = runtime or (model.runtime_profile if model else runtime_profile(""))

    parameters: dict = {}
    applied: list[str] = []
    degraded: list[str] = []

    # ------------------------------------------------------------- output
    ceiling = int(base_output_tokens * budget.output_scale)
    if model and model.max_output_tokens:
        ceiling = min(ceiling, model.max_output_tokens)
    if runtime.accepts_max_tokens:
        parameters["max_tokens"] = ceiling
        if budget.output_scale > 1.0:
            applied.append("output budget")
    elif budget.output_scale > 1.0:
        degraded.append(
            f"{runtime.label or 'This runtime'} takes no output limit, so a "
            f"larger answer budget has no effect here")

    # ---------------------------------------------------------- reasoning
    support = model.reasoning if model else ReasoningSupport.NONE
    wants_reasoning = budget.reasoning_share > 0
    if wants_reasoning:
        if support is ReasoningSupport.THINKING_TOGGLE:
            # Measured, not assumed: a 1.7B asked to think spent its whole
            # budget on an unterminated block and produced no answer. So
            # thinking is switched ON only at the levels that also raised the
            # ceiling enough to survive it.
            parameters["enable_thinking"] = True
            applied.append("reasoning")
        elif support is ReasoningSupport.BUDGET_TOKENS and model:
            share = int((model.context_tokens or 8192) * budget.reasoning_share)
            parameters["reasoning_max_tokens"] = share
            applied.append("reasoning")
        elif support is ReasoningSupport.EFFORT_LEVEL:
            parameters["reasoning_effort"] = effort.value
            applied.append("reasoning")
        else:
            degraded.append(
                f"{model.name if model else 'This model'} has no reasoning "
                f"control, so {LABELS[effort]} buys more attempts and a review "
                f"pass instead of deeper thinking")
    elif support is ReasoningSupport.THINKING_TOGGLE:
        # Off explicitly rather than by omission. Left to itself Qwen3 thinks by
        # default, which at Fast is exactly what the user asked not to happen.
        parameters["enable_thinking"] = False
        applied.append("thinking off")

    # ---------------------------------------------------- orchestration
    if budget.passes > 1:
        applied.append(f"{budget.passes} passes")
    if budget.reviewer:
        applied.append("review pass")
    if budget.candidates > 1:
        applied.append(f"{budget.candidates} candidates")

    return Plan(
        effort=effort,
        parameters=parameters,
        max_output_tokens=ceiling,
        passes=budget.passes,
        reviewer=budget.reviewer,
        tool_iterations=budget.tool_iterations,
        candidates=budget.candidates,
        applied=tuple(applied),
        degraded=tuple(degraded),
    )


def describe(model: ModelProfile | None = None) -> list[dict]:
    """Every level and what it would mean for this model.

    So the interface can show the choice honestly — including which levels buy
    nothing extra here — rather than offering four options that behave the same.
    """
    out = []
    for effort in ORDER:
        plan = translate(effort, model)
        out.append({
            "id": effort.value,
            "label": LABELS[effort],
            "blurb": BLURBS[effort],
            "applied": list(plan.applied),
            "degraded": list(plan.degraded),
            "thinks": plan.thinks,
        })
    return out
