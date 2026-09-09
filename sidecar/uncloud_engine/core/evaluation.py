"""Scoring work, so "better" can be argued with rather than asserted.

THIS FILE IS BYTE-IDENTICAL IN BOTH REPOSITORIES. See `capability.py` for the
rules it lives by.

Both products need this and neither had it. Uncloud could tell a blank image
from a real one and nothing else; Studio could record that a person approved
something. Neither could say whether one candidate was better than another, or
whether last month's pipeline still works as well as it did.

The shape is deliberately modality-agnostic. A dimension is a named axis with a
weight and, optionally, a floor. An evaluator produces scores on some of those
axes. Nothing here knows what a candidate IS — a picture, a paragraph, a
spreadsheet — because the arithmetic of weighted scoring does not change and
duplicating it per modality is how two products end up disagreeing about what
0.7 means.

Three rules it holds to:

* **A missing score is not zero.** An evaluator that could not run leaves the
  axis unscored, and the weighted total is computed over what was actually
  measured. Scoring an unmeasured axis as zero would let one absent model make
  everything look bad.
* **A floor is a veto, not a subtraction.** Some things are not tradeable: a
  blank image is not redeemed by a good prompt-adherence score. A dimension
  below its floor fails the whole result whatever the total says.
* **Evidence travels with the score.** A number nobody can check is not a
  measurement. Every score carries a note saying what was looked at.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

EVALUATION_VERSION = 1


class Judge(StrEnum):
    """Who produced a score. Recorded because it changes what it is worth.

    A measured number and a model's opinion are both useful and they are not
    the same evidence, so an interface can show which is which and a regression
    test can insist on the measurable ones.
    """

    #: Arithmetic on the artefact itself: variance, colour distance, size.
    MEASURED = "measured"
    #: A model was asked. Cheap to produce, expensive to trust.
    MODEL = "model"
    #: A person said so. Outranks everything, and is the only one that can
    #: settle a question of taste.
    HUMAN = "human"


@dataclass(frozen=True)
class Dimension:
    """One axis a candidate is scored on."""

    id: str
    label: str
    #: Relative importance within a rubric. Not normalised here; `Rubric` does
    #: that, so a dimension can be reused at different weights.
    weight: float = 1.0
    #: Below this the whole result fails, whatever the total is. None means the
    #: axis is tradeable against the others.
    floor: float | None = None
    description: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "weight": self.weight,
                "floor": self.floor, "description": self.description}


@dataclass(frozen=True)
class Score:
    """One measurement on one axis.

    `value` is 0..1 throughout, so dimensions from different evaluators can be
    weighed against each other without every caller remembering a scale.
    """

    dimension: str
    value: float
    #: What was looked at, in a sentence. A number nobody can check is not a
    #: measurement.
    note: str = ""
    judge: Judge = Judge.MEASURED
    #: Anything the interface can show: a path, a distance, a quotation.
    evidence: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", max(0.0, min(1.0, float(self.value))))

    def to_dict(self) -> dict:
        return {"dimension": self.dimension, "value": round(self.value, 4),
                "note": self.note, "judge": self.judge.value,
                "evidence": dict(self.evidence)}


@dataclass
class Rubric:
    """What matters for a kind of work, and how much.

    A rubric is data. Studio's poster rubric and its product-shot rubric differ
    in weights, not in code, which is what lets a user's own preferences become
    a rubric later without anything being rewritten.
    """

    id: str
    label: str
    dimensions: tuple[Dimension, ...] = ()
    #: The weighted total a result must reach. None means the floors are the
    #: only requirement.
    threshold: float | None = None
    #: How much of the rubric must actually have been measured for a result to
    #: count as passing.
    #:
    #: Without this, a candidate scored on one axis out of six can outrank one
    #: scored on all six, because a high average over a thin measurement is
    #: still a high average. That is exactly backwards for a retry loop: a
    #: candidate that could not be checked would win by not being checked. Zero
    #: keeps the old behaviour for rubrics that do not care.
    min_coverage: float = 0.0

    def dimension(self, dimension_id: str) -> Dimension | None:
        return next((d for d in self.dimensions if d.id == dimension_id), None)

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "threshold": self.threshold,
                "min_coverage": self.min_coverage,
                "dimensions": [d.to_dict() for d in self.dimensions]}


@dataclass
class Result:
    """What one candidate scored, and whether that is good enough."""

    candidate: str
    rubric: str
    scores: tuple[Score, ...] = ()
    at: float = field(default_factory=time.time)
    #: Anything the caller wants carried alongside: a job id, a seed, a path.
    meta: dict = field(default_factory=dict)
    #: Evaluators that were asked and could not answer, with the reason. Kept
    #: because "not measured" and "measured badly" are different, and a result
    #: that hides which is which cannot be acted on.
    skipped: tuple[tuple[str, str], ...] = ()

    def score_for(self, dimension_id: str) -> Score | None:
        return next((s for s in self.scores if s.dimension == dimension_id), None)

    def total(self, rubric: Rubric) -> float:
        """The weighted mean over the axes that were actually measured.

        A missing score is not zero. An evaluator that could not run — no vision
        model loaded, no reference to compare against — must not drag a
        candidate down as though it had been measured and failed.
        """
        pairs = [(rubric.dimension(s.dimension), s) for s in self.scores]
        weighed = [(d.weight, s.value) for d, s in pairs if d is not None]
        if not weighed:
            return 0.0
        weight = sum(w for w, _ in weighed)
        return sum(w * v for w, v in weighed) / weight if weight else 0.0

    def failures(self, rubric: Rubric) -> list[tuple[Dimension, Score]]:
        """Axes that fell below their own floor.

        A floor is a veto rather than a subtraction: a blank image is not
        redeemed by a good adherence score.
        """
        out = []
        for score in self.scores:
            dimension = rubric.dimension(score.dimension)
            if dimension and dimension.floor is not None \
                    and score.value < dimension.floor:
                out.append((dimension, score))
        return out

    def passed(self, rubric: Rubric) -> bool:
        if self.failures(rubric):
            return False
        if rubric.min_coverage and self.coverage(rubric) < rubric.min_coverage:
            # Not measured is not the same as good. A result too thin to judge
            # does not pass, however well the parts that were measured scored.
            return False
        if rubric.threshold is None:
            return True
        return self.total(rubric) >= rubric.threshold

    def coverage(self, rubric: Rubric) -> float:
        """How much of the rubric was actually measured, by weight.

        A result scoring 0.9 on one axis out of six is not a 0.9. Reporting
        coverage next to the total is what stops a thin measurement being read
        as a confident one.
        """
        total = sum(d.weight for d in rubric.dimensions)
        if not total:
            return 0.0
        measured = sum(d.weight for d in rubric.dimensions
                       if self.score_for(d.id) is not None)
        return measured / total

    def explain(self, rubric: Rubric) -> str:
        """Why this scored what it did, for a person.

        Leads with what failed, because that is what a person acts on, and
        names the dimension in the rubric's own words rather than its id.
        """
        if not self.scores:
            return "Nothing could be measured."
        lines = []
        if rubric.min_coverage and self.coverage(rubric) < rubric.min_coverage:
            lines.append(
                f"Only {self.coverage(rubric) * 100:.0f}% of this could be "
                f"measured, against the {rubric.min_coverage * 100:.0f}% needed "
                f"to judge it.")
        for dimension, score in self.failures(rubric):
            lines.append(f"{dimension.label}: {score.value:.2f} — below the "
                         f"{dimension.floor:.2f} it has to clear. {score.note}".strip())
        if not lines:
            lines.append(f"Scored {self.total(rubric):.2f}"
                         + (f" against a {rubric.threshold:.2f} threshold."
                            if rubric.threshold else "."))
        if self.skipped:
            lines.append("Not measured: " + "; ".join(
                f"{name} ({why})" for name, why in self.skipped))
        return " ".join(lines)

    def to_dict(self, rubric: Rubric | None = None) -> dict:
        out = {
            "candidate": self.candidate, "rubric": self.rubric, "at": self.at,
            "scores": [s.to_dict() for s in self.scores],
            "meta": dict(self.meta),
            "skipped": [{"evaluator": n, "reason": r} for n, r in self.skipped],
        }
        if rubric is not None:
            out.update({
                "total": round(self.total(rubric), 4),
                "passed": self.passed(rubric),
                "coverage": round(self.coverage(rubric), 3),
                "failures": [d.id for d, _ in self.failures(rubric)],
                "explanation": self.explain(rubric),
            })
        return out


class Evaluator:
    """Something that can score a candidate on one or more dimensions.

    A protocol rather than a base class with behaviour: an evaluator is
    whatever has these two things, so a product can supply one without
    inheriting from a shared package it would then have to keep in step.
    """

    id: str = ""
    dimensions: tuple[Dimension, ...] = ()

    def evaluate(self, candidate, context: dict) -> Sequence[Score]:  # pragma: no cover
        raise NotImplementedError


class Unmeasurable(Exception):
    """This evaluator cannot answer for this candidate, and why.

    Distinct from scoring zero. "No vision model is loaded" and "the image does
    not match its reference" are different facts, and collapsing them makes
    every result on a machine without a vision model look like a failure.
    """


def evaluate(candidate, evaluators: Iterable[Evaluator], rubric: Rubric, *,
             context: dict | None = None, candidate_id: str = "",
             meta: dict | None = None) -> Result:
    """Run every evaluator over one candidate and collect the scores.

    Never raises for a failing evaluator. One that cannot run is recorded in
    `skipped` and the rest carry on — a scoring pass that aborts because a
    single optional check was unavailable is worse than a partial score that
    says it is partial.
    """
    context = context or {}
    scores: list[Score] = []
    skipped: list[tuple[str, str]] = []

    for evaluator in evaluators:
        try:
            produced = evaluator.evaluate(candidate, context) or ()
        except Unmeasurable as exc:
            skipped.append((evaluator.id, str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001 - an evaluator is never fatal
            skipped.append((evaluator.id, f"{type(exc).__name__}: {exc}"))
            continue
        for score in produced:
            if rubric.dimension(score.dimension) is None:
                # An axis this rubric does not weigh. Kept — it may be useful to
                # look at — but it contributes nothing to the total.
                pass
            scores.append(score)

    return Result(candidate=candidate_id or str(candidate), rubric=rubric.id,
                  scores=tuple(scores), meta=dict(meta or {}),
                  skipped=tuple(skipped))


def compare(results: Sequence[Result], rubric: Rubric) -> list[Result]:
    """Rank candidates, best first.

    Passing beats not passing before any total is considered: a candidate that
    cleared every floor at 0.71 is a better answer than one that failed a floor
    at 0.93, because the floors are the things that were not up for trade.

    Coverage breaks ties, and a rubric that cares about thin measurements
    should set `min_coverage` rather than relying on that — a tiebreak only
    helps when the totals are equal, and the case worth guarding is a thinly
    measured candidate scoring HIGHER.
    """
    return sorted(
        results,
        key=lambda r: (r.passed(rubric), round(r.total(rubric), 4),
                       round(r.coverage(rubric), 3)),
        reverse=True)


def best(results: Sequence[Result], rubric: Rubric) -> Result | None:
    ranked = compare(results, rubric)
    return ranked[0] if ranked else None


@dataclass
class Regression:
    """Whether a change made things better or worse.

    The question the whole framework exists to answer. A self-improving
    pipeline that cannot be shown to improve anything is just a more
    complicated pipeline.
    """

    rubric: Rubric
    baseline: Sequence[Result]
    candidate: Sequence[Result]

    @staticmethod
    def _mean(results: Sequence[Result], rubric: Rubric) -> float:
        return (sum(r.total(rubric) for r in results) / len(results)
                if results else 0.0)

    @property
    def before(self) -> float:
        return self._mean(self.baseline, self.rubric)

    @property
    def after(self) -> float:
        return self._mean(self.candidate, self.rubric)

    @property
    def delta(self) -> float:
        return self.after - self.before

    @property
    def pass_rate_before(self) -> float:
        return (sum(1 for r in self.baseline if r.passed(self.rubric))
                / len(self.baseline)) if self.baseline else 0.0

    @property
    def pass_rate_after(self) -> float:
        return (sum(1 for r in self.candidate if r.passed(self.rubric))
                / len(self.candidate)) if self.candidate else 0.0

    def regressed(self, *, tolerance: float = 0.02) -> bool:
        """Whether this is worse by more than noise.

        A tolerance rather than a strict comparison because generation is
        stochastic: two runs of an unchanged pipeline differ, and a test that
        fails on that teaches people to ignore it.
        """
        return self.delta < -tolerance

    def to_dict(self) -> dict:
        return {
            "rubric": self.rubric.id,
            "before": round(self.before, 4), "after": round(self.after, 4),
            "delta": round(self.delta, 4),
            "pass_rate_before": round(self.pass_rate_before, 3),
            "pass_rate_after": round(self.pass_rate_after, 3),
            "regressed": self.regressed(),
            "samples": {"baseline": len(self.baseline),
                        "candidate": len(self.candidate)},
        }


# ------------------------------------------------------------ common axes
#
# Dimensions both products use. Defined once so a score named "adherence" means
# the same thing in Uncloud and in Studio, which is the whole reason evaluation
# lives in the foundation rather than in either.
NOT_BLANK = Dimension(
    id="not_blank", label="Produced something", weight=1.0, floor=0.5,
    description="Whether the output is real work rather than a flat fill, an "
                "empty file or a failed decode.")

ADHERENCE = Dimension(
    id="adherence", label="Followed the instruction", weight=3.0,
    description="Whether the result is what was actually asked for.")

CONSISTENCY = Dimension(
    id="consistency", label="Matches its references", weight=3.0,
    description="Whether the product, character or brand is recognisably the "
                "same as the material it was given.")

DEFECTS = Dimension(
    id="defects", label="Free of defects", weight=2.0, floor=0.3,
    description="Artefacts, garbled lettering, malformed subjects.")

COMPOSITION = Dimension(
    id="composition", label="Composition", weight=1.0,
    description="Framing, balance, and room left for anything to be placed later.")
