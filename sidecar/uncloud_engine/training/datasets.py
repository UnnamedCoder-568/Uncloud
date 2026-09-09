"""Bringing a dataset in, and refusing to train on one that will not work.

Validation before training is not politeness. A fine-tune on a malformed set
does not fail — it succeeds, slowly, and produces an adapter that makes the
model worse in ways nobody can attribute. On the machines this targets that is
twenty minutes to an hour of somebody's afternoon, and the only signal is a
model that feels off.

So everything here is about catching that first. What it checks is what
actually goes wrong with hand-assembled data: the wrong shape, empty turns, one
example repeated three hundred times, examples longer than the model's context,
and a set too small to teach anything.

Two formats are accepted, because these are the two people arrive with:

    {"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}
    {"prompt": "...", "completion": "..."}

Both are read into the same shape. Anything else is reported WITH ITS LINE
NUMBER rather than skipped, because a file where a third of the lines were
silently dropped trains on a third of what its author intended, and the only
symptom is an adapter that underperforms for no visible reason.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

#: Below this a run cannot teach a behaviour, only the examples themselves. Not
#: a refusal — somebody testing the pipeline with ten examples is doing
#: something reasonable — but it is the first thing said about the set.
USEFUL_MINIMUM = 50

#: A fine-tune on a set this repetitive learns the repetition. Measured as
#: distinct examples over total.
MIN_VARIETY = 0.7

#: Long enough that most models truncate, which silently trains on half an
#: example. Counted per example rather than averaged, because an average hides
#: the twelve that will be cut.
LONG_EXAMPLE_CHARS = 8000


@dataclass
class Example:
    """One training example, whatever shape it arrived in."""

    messages: list[dict]

    @property
    def characters(self) -> int:
        return sum(len(str(m.get("content", ""))) for m in self.messages)

    @property
    def signature(self) -> str:
        return "".join(
            f"{m.get('role')}:{str(m.get('content', ''))[:400]}"
            for m in self.messages)


@dataclass
class Problem:
    """Something wrong with the dataset, and where.

    `line` is 1-based and matches what an editor shows, because the point of
    reporting a problem is that somebody can go and look at it.
    """

    line: int
    what: str
    fatal: bool = False

    def to_dict(self) -> dict:
        return {"line": self.line, "what": self.what, "fatal": self.fatal}


@dataclass
class Dataset:
    path: Path
    examples: list[Example] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.examples)

    @property
    def characters(self) -> int:
        return sum(e.characters for e in self.examples)

    @property
    def variety(self) -> float:
        """Distinct examples over total. One example repeated is not a dataset."""
        if not self.examples:
            return 0.0
        return len({e.signature for e in self.examples}) / len(self.examples)

    @property
    def usable(self) -> bool:
        return bool(self.examples) and not any(p.fatal for p in self.problems)

    @property
    def warnings(self) -> list[str]:
        """What a person should know before spending an hour on this.

        Warnings rather than refusals, deliberately. A small or repetitive set
        is somebody's decision to make; what is not acceptable is making it
        without being told.
        """
        out: list[str] = []
        if 0 < self.count < USEFUL_MINIMUM:
            out.append(
                f"{self.count} examples is very few. Below about "
                f"{USEFUL_MINIMUM} a run usually learns the examples rather "
                f"than the behaviour.")
        if self.examples and self.variety < MIN_VARIETY:
            out.append(
                f"Only {self.variety * 100:.0f}% of the examples are distinct. "
                f"A fine-tune on a repetitive set learns the repetition.")
        long = sum(1 for e in self.examples if e.characters > LONG_EXAMPLE_CHARS)
        if long:
            out.append(
                f"{long} example(s) are over {LONG_EXAMPLE_CHARS} characters "
                f"and will probably be truncated, training on part of them.")
        return out

    def to_dict(self) -> dict:
        return {
            "path": str(self.path), "count": self.count,
            "characters": self.characters,
            "variety": round(self.variety, 3),
            "usable": self.usable,
            "warnings": self.warnings,
            "problems": [p.to_dict() for p in self.problems[:50]],
            "problem_count": len(self.problems),
        }


def _as_messages(record: dict, line: int) -> tuple[list[dict] | None, Problem | None]:
    if isinstance(record.get("messages"), list):
        messages = record["messages"]
    elif "prompt" in record and "completion" in record:
        messages = [{"role": "user", "content": record["prompt"]},
                    {"role": "assistant", "content": record["completion"]}]
    elif "text" in record:
        # A plain completion set. Legitimate, and it trains differently — kept
        # rather than rejected, since a model can be fine-tuned on raw text.
        messages = [{"role": "assistant", "content": record["text"]}]
    else:
        return None, Problem(
            line, "no 'messages', no 'prompt'/'completion' pair and no 'text'")

    if not messages:
        return None, Problem(line, "the example has no turns")
    for message in messages:
        if not isinstance(message, dict):
            return None, Problem(line, "a turn is not an object")
        if not str(message.get("content", "")).strip():
            role = message.get("role", "?")
            return None, Problem(line, f"the {role} turn is empty")
    return messages, None


def read(path: str | Path) -> Dataset:
    """Read a JSONL dataset, reporting every line it could not use."""
    path = Path(path)
    dataset = Dataset(path=path)
    if not path.exists():
        dataset.problems.append(
            Problem(0, f"there is no file at {path}", fatal=True))
        return dataset
    if path.stat().st_size == 0:
        dataset.problems.append(Problem(0, "the file is empty", fatal=True))
        return dataset

    for line_number, raw in enumerate(_lines(path), start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            dataset.problems.append(
                Problem(line_number, f"not valid JSON: {exc.msg}"))
            continue
        if not isinstance(record, dict):
            dataset.problems.append(Problem(line_number, "not a JSON object"))
            continue
        messages, problem = _as_messages(record, line_number)
        if problem is not None:
            dataset.problems.append(problem)
            continue
        dataset.examples.append(Example(messages=messages))  # type: ignore[arg-type]

    if not dataset.examples:
        dataset.problems.append(
            Problem(0, "no usable examples were found in the file", fatal=True))
    return dataset


def _lines(path: Path) -> Iterator[str]:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        yield from handle


def split(dataset: Dataset, *, holdout: float = 0.1,
          minimum: int = 5) -> tuple[list[Example], list[Example]]:
    """Hold examples back, so a run can be judged on what it did not see.

    Taken from the END rather than at random, and that is a deliberate trade:
    reproducibility beats statistical purity here, because a validation set
    that changes between runs makes two runs incomparable — which is the whole
    reason to have one.
    """
    if len(dataset.examples) < minimum * 2:
        return dataset.examples, []
    keep = max(minimum, int(len(dataset.examples) * holdout))
    return dataset.examples[:-keep], dataset.examples[-keep:]


def write(examples: list[Example], path: str | Path) -> Path:
    """Write examples out in the shape mlx-lm expects."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for example in examples:
            record = json.dumps({"messages": example.messages}, ensure_ascii=False)
            handle.write(record)
            handle.write("\n")
    return path
