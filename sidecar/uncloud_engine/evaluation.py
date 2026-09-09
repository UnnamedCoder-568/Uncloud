"""Uncloud's evaluators.

The framework lives in `foundation.evaluation` and is shared with Studio. This
is the thin part: the checks Uncloud already had, expressed as evaluators so
they can be weighed, compared and regression-tested alongside anything added
later.

`output_check` is not replaced. It stays where it is and keeps RAISING at
generation time, because a degenerate render should fail the job rather than be
handed to somebody as a picture with a low score. This is the same measurement
asked a different question: not "should this job fail" but "which of these is
better".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .core import NOT_BLANK, Dimension, Rubric, Score, Unmeasurable

SIZE = Dimension(
    id="size", label="Size", weight=1.0,
    description="Whether the file is large enough to be real work.")


@dataclass
class NotBlank:
    """Whether a generation produced anything usable.

    Diffusion fails quietly — a NaN in the latents, a VAE that never loaded, an
    allocation that failed — and every one of those ends with a file on disk
    and a job that believes it succeeded.
    """

    id = "not_blank"
    dimensions = (NOT_BLANK, SIZE)

    def evaluate(self, candidate, context: dict):
        from .output_check import (
            MAX_SINGLE_COLOUR_SHARE,
            MIN_DISTINCT,
            MIN_STDDEV,
            describe,
        )

        path = Path(candidate)
        if not path.exists():
            return [Score(NOT_BLANK.id, 0.0, "the pipeline wrote no file")]

        size = path.stat().st_size
        if size < 1024:
            return [Score(NOT_BLANK.id, 0.0, f"the file is {size} bytes"),
                    Score(SIZE.id, 0.0, f"{size} bytes")]

        try:
            stats = describe(path)
        except Exception as exc:  # noqa: BLE001 - unreadable is its own answer
            raise Unmeasurable(f"could not read {path.name}: {exc}") from exc

        blank = (stats["stddev"] < MIN_STDDEV
                 or stats["distinct"] < MIN_DISTINCT
                 or stats["top_share"] > MAX_SINGLE_COLOUR_SHARE)
        return [
            Score(NOT_BLANK.id, 0.0 if blank else 1.0,
                  f"variation {stats['stddev']:.1f}, {stats['distinct']} tones, "
                  f"{stats['top_share'] * 100:.1f}% one colour",
                  evidence=stats),
            # Saturating at a megabyte: past that, size says nothing useful
            # about whether a picture is good, only that something happened.
            Score(SIZE.id, min(1.0, size / 1_000_000), f"{size / 1000:.0f} kB"),
        ]


#: What Uncloud scores a generated picture on today. Deliberately short — this
#: is the floor everything else builds on, and a rubric with axes nothing can
#: measure would report low coverage on every candidate.
IMAGE = Rubric(
    id="image", label="Generated image",
    dimensions=(NOT_BLANK, SIZE), threshold=0.5, min_coverage=0.5,
)

EVALUATORS = (NotBlank(),)
