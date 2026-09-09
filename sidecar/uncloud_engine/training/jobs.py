"""Running a LoRA fine-tune, and surviving the ways it can go wrong.

Built on the shape `quantize.py` already proved: an id, a status, progress, a
log, and a subprocess doing the actual work. That is not laziness — it is the
one pattern in this codebase that has already handled a long local job people
walk away from, and inventing a second one would mean two things to get right.

Three decisions worth stating.

**Feasibility first, always.** `start` refuses before spawning anything if the
estimate says it will not fit. A run that dies forty minutes in has cost
somebody their afternoon, and the check that would have prevented it takes
milliseconds.

**A subprocess, not an import.** mlx-lm's trainer holds a model for the length
of the run; importing it into the engine would put those gigabytes beside
whatever else is loaded and keep them after the run finished. A child process
exits and the memory is gone — which on a machine where the ceiling is the
whole constraint is the difference between training being usable and not.

**The adapter is the artefact.** Training writes adapter weights, never a new
copy of the model. A fine-tune that produced another eight gigabytes on disk
per experiment would make experimenting the expensive part.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..config import CONFIG_DIR
from . import datasets, feasibility

TRAINING_DIR = CONFIG_DIR / "training"

#: Presets rather than a form. Nobody arriving at this feature knows what a
#: sensible rank is, and the honest answer is that three configurations cover
#: almost everything people actually want.
PRESETS: dict[str, dict] = {
    "light": {
        "label": "Light touch",
        "note": "Nudges tone and formatting. Quick, and hard to make worse.",
        "iterations": 300, "batch_size": 4, "rank": 8, "learning_rate": 1e-5,
    },
    "standard": {
        "label": "Standard",
        "note": "Teaches a consistent behaviour from a few hundred examples.",
        "iterations": 600, "batch_size": 4, "rank": 16, "learning_rate": 1e-5,
    },
    "deep": {
        "label": "Deep",
        "note": "For a substantial dataset and a real change of behaviour. Slow.",
        "iterations": 1200, "batch_size": 2, "rank": 32, "learning_rate": 5e-6,
    },
}

#: mlx-lm prints one of these per validation step. Parsed rather than guessed
#: at, because progress inferred from elapsed time is a lie the moment the
#: machine gets busy.
_ITER = re.compile(r"Iter\s+(\d+):")
_LOSS = re.compile(r"[Tt]rain loss ([\d.]+)")
_VAL = re.compile(r"[Vv]al loss ([\d.]+)")


@dataclass
class TrainingJob:
    id: str
    model_path: str
    dataset_path: str
    preset: str
    output_dir: str
    status: str = "pending"          # pending | preparing | training | done | error | cancelled
    iteration: int = 0
    iterations: int = 0
    train_loss: float | None = None
    val_loss: float | None = None
    error: str = ""
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    log: list[str] = field(default_factory=list)
    estimate: dict = field(default_factory=dict)
    examples: int = 0

    @property
    def percent(self) -> float:
        if not self.iterations:
            return 0.0
        return min(100.0, self.iteration / self.iterations * 100)

    @property
    def running(self) -> bool:
        return self.status in ("pending", "preparing", "training")

    def to_dict(self) -> dict:
        return {
            "id": self.id, "model_path": self.model_path,
            "dataset_path": self.dataset_path, "preset": self.preset,
            "output_dir": self.output_dir, "status": self.status,
            "iteration": self.iteration, "iterations": self.iterations,
            "percent": round(self.percent, 1),
            "train_loss": self.train_loss, "val_loss": self.val_loss,
            "error": self.error, "examples": self.examples,
            "started_at": self.started_at, "ended_at": self.ended_at,
            "estimate": dict(self.estimate),
            # The tail only. A full log of a long run is megabytes, and the
            # last forty lines are what anybody actually reads.
            "log": self.log[-40:],
        }


class Refused(RuntimeError):
    """The run was not started, and why. Raised before anything is spawned."""


_jobs: dict[str, TrainingJob] = {}
_tasks: dict[str, asyncio.Task] = {}


def presets() -> list[dict]:
    return [{"id": key, **value} for key, value in PRESETS.items()]


def get(job_id: str) -> TrainingJob | None:
    return _jobs.get(job_id)


def all_jobs() -> list[TrainingJob]:
    return sorted(_jobs.values(), key=lambda j: j.started_at, reverse=True)


def prepare(model_path: str, dataset_path: str, preset: str = "standard",
            *, batch_size: int | None = None) -> dict:
    """Everything that would happen, without starting it.

    Called by the interface before offering the button, so a run that cannot
    work is explained while the user is still deciding rather than eight
    minutes in.
    """
    if preset not in PRESETS:
        raise Refused(f"{preset!r} is not a preset. Known: {', '.join(PRESETS)}.")
    settings = PRESETS[preset]
    dataset = datasets.read(dataset_path)
    guess = feasibility.estimate(
        model_path, examples=dataset.count,
        batch_size=batch_size or settings["batch_size"],
        iterations=settings["iterations"])
    return {"dataset": dataset.to_dict(), "estimate": guess.to_dict(),
            "preset": {"id": preset, **settings}}


async def start(model_path: str, dataset_path: str, preset: str = "standard",
                *, batch_size: int | None = None,
                name: str = "") -> TrainingJob:
    """Validate, size, and only then spawn.

    Both refusals happen here rather than inside the run: a dataset that cannot
    train and a machine that cannot hold the model are both knowable in
    milliseconds, and discovering either after twenty minutes is the failure
    this whole module is arranged to avoid.
    """
    plan = prepare(model_path, dataset_path, preset, batch_size=batch_size)
    dataset = datasets.read(dataset_path)
    if not dataset.usable:
        fatal = next((p.what for p in dataset.problems if p.fatal),
                     "the dataset has no usable examples")
        raise Refused(f"That dataset cannot be trained on: {fatal}")
    if not plan["estimate"]["feasible"]:
        raise Refused(plan["estimate"]["reason"])

    settings = PRESETS[preset]
    job_id = uuid.uuid4().hex[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", (name or Path(model_path).name).lower()).strip("-")
    output = TRAINING_DIR / "adapters" / f"{slug or 'adapter'}-{job_id}"
    output.mkdir(parents=True, exist_ok=True)

    job = TrainingJob(
        id=job_id, model_path=str(model_path), dataset_path=str(dataset_path),
        preset=preset, output_dir=str(output),
        iterations=settings["iterations"], examples=dataset.count,
        estimate=plan["estimate"])
    _jobs[job_id] = job
    _tasks[job_id] = asyncio.create_task(_run(job, settings, batch_size))
    return job


def cancel(job_id: str) -> bool:
    task = _tasks.get(job_id)
    job = _jobs.get(job_id)
    if not task or not job or not job.running:
        return False
    task.cancel()
    job.status = "cancelled"
    job.ended_at = time.time()
    return True


async def _run(job: TrainingJob, settings: dict, batch_size: int | None) -> None:
    import sys

    try:
        job.status = "preparing"
        workspace = Path(job.output_dir) / "data"
        workspace.mkdir(parents=True, exist_ok=True)

        # mlx-lm wants a directory with train.jsonl and valid.jsonl. The split
        # is deterministic — see `datasets.split` — so two runs of the same set
        # are comparable, which is the only reason to hold anything back.
        dataset = datasets.read(job.dataset_path)
        train, validate = datasets.split(dataset)
        datasets.write(train, workspace / "train.jsonl")
        datasets.write(validate or train[-1:], workspace / "valid.jsonl")

        command = [
            sys.executable, "-m", "mlx_lm", "lora",
            "--model", job.model_path,
            "--train",
            "--data", str(workspace),
            "--adapter-path", job.output_dir,
            "--iters", str(settings["iterations"]),
            "--batch-size", str(batch_size or settings["batch_size"]),
            "--num-layers", str(settings["rank"]),
            "--learning-rate", str(settings["learning_rate"]),
        ]
        job.log.append("$ " + " ".join(command[2:]))
        job.status = "training"

        process = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)

        assert process.stdout is not None
        async for raw in process.stdout:
            line = raw.decode(errors="replace").rstrip()
            if not line:
                continue
            job.log.append(line)
            _absorb(job, line)

        code = await process.wait()
        if code != 0:
            job.status = "error"
            job.error = _why(job.log) or f"training exited with code {code}"
        else:
            job.status = "done"
            _write_card(job)
    except asyncio.CancelledError:
        job.status = "cancelled"
        raise
    except Exception as exc:  # noqa: BLE001 - reported on the job, never raised
        job.status = "error"
        job.error = f"{type(exc).__name__}: {exc}"
    finally:
        job.ended_at = time.time()


def _absorb(job: TrainingJob, line: str) -> None:
    """Read progress out of the trainer's own output.

    Parsed rather than inferred from elapsed time. A progress bar driven by a
    clock is a lie the moment the machine gets busy, and this is exactly the
    kind of job somebody walks away from.
    """
    found = _ITER.search(line)
    if found:
        job.iteration = int(found.group(1))
    loss = _LOSS.search(line)
    if loss:
        job.train_loss = float(loss.group(1))
    val = _VAL.search(line)
    if val:
        job.val_loss = float(val.group(1))


def _why(log: list[str]) -> str:
    """The line a person can act on, out of a wall of traceback."""
    for line in reversed(log[-60:]):
        stripped = line.strip()
        if not stripped or stripped.startswith(("File \"", "^", "Traceback")):
            continue
        if ":" in stripped and stripped.split(":", 1)[0].replace(".", "").isidentifier():
            return stripped[:400]
    return ""


def _write_card(job: TrainingJob) -> None:
    """A record beside the adapter of what made it.

    An adapter with no provenance is unusable six weeks later: nobody can say
    which model it belongs to, what it was trained on, or whether it is the one
    that worked. It travels with the weights rather than living in a database,
    so copying the folder copies the answer.
    """
    card = {
        "adapter": Path(job.output_dir).name,
        "base_model": job.model_path,
        "dataset": job.dataset_path,
        "examples": job.examples,
        "preset": job.preset,
        "iterations": job.iterations,
        "train_loss": job.train_loss,
        "val_loss": job.val_loss,
        "trained_at": time.time(),
        "trained_by": "Uncloud",
        # Said plainly, because it is the thing people get wrong about
        # adapters: it is not a model, and it will not load without the one it
        # was trained against.
        "note": "A LoRA adapter, not a model. It only works with the base model "
                "named above.",
    }
    (Path(job.output_dir) / "uncloud-adapter.json").write_text(
        json.dumps(card, indent=2) + "\n")


def adapters() -> list[dict]:
    """Every adapter this machine has trained, newest first."""
    root = TRAINING_DIR / "adapters"
    if not root.is_dir():
        return []
    out = []
    for directory in sorted(root.iterdir(), reverse=True):
        card = directory / "uncloud-adapter.json"
        if not card.is_file():
            continue
        try:
            data = json.loads(card.read_text())
        except (OSError, ValueError):
            continue
        weights = [p.name for p in directory.glob("*.safetensors")]
        out.append({**data, "path": str(directory), "weights": weights,
                    "ready": bool(weights)})
    return out


def forget(name: str) -> bool:
    """Delete an adapter. Only ever one Uncloud trained."""
    target = (TRAINING_DIR / "adapters" / name).resolve()
    root = (TRAINING_DIR / "adapters").resolve()
    if root not in target.parents or not target.is_dir():
        return False
    shutil.rmtree(target)
    return True
