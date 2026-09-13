"""Storing a component in the precision it is actually used in.

Measured on the LTX pipeline: its T5 text encoder ships as 19 GB of float32
and every load converts it to bfloat16 before using it. The external drive
here reads at 1.0 GB/s, so that is nineteen seconds of reading to produce
nine and a half gigabytes — the other nine and a half are read, converted and
thrown away, on every cold start, for ever.

This is not quantisation and it costs nothing. bfloat16 is the precision the
weights are already used at; the float32 on disk is a packaging accident of how
the model was published. Recasting is the rare optimisation with no trade to
weigh: half the read, half the disk, identical arithmetic.

**Never in place.** A model is somebody's download, often measured in tens of
gigabytes over a slow connection. The recast is written beside the original and
verified before anything is said to have worked; removing the original is a
separate decision for whoever owns the disk.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

#: Precisions worth rewriting away from, and what to. Only widening formats
#: appear here: a component already at bfloat16 or below is left alone, and
#: nothing is ever recast to something narrower, which would be quantisation
#: wearing this function's clothes.
WIDE = {"float32", "fp32", "float64"}
TARGET = "bfloat16"

#: Below this, the rewrite costs more attention than the saving is worth. A
#: 200 MB component recast saves 100 MB and a fraction of a second, which is
#: not worth a progress bar or the risk of touching somebody's model.
WORTH_RECASTING_GB = 1.0


@dataclass
class Recast:
    """What a recast would cost and save, or what it did."""

    component: str
    source: Path
    before_gb: float = 0.0
    after_gb: float = 0.0
    dtype_before: str = ""
    written: Path | None = None
    skipped: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def saved_gb(self) -> float:
        """Rounded, because this is read by a person rather than computed with."""
        return round(max(0.0, self.before_gb - self.after_gb), 2)

    @property
    def worthwhile(self) -> bool:
        return not self.skipped and self.before_gb > WORTH_RECASTING_GB

    def to_dict(self) -> dict:
        return {
            "component": self.component, "source": str(self.source),
            "before_gb": round(self.before_gb, 2),
            "after_gb": round(self.after_gb, 2), "saved_gb": self.saved_gb,
            "dtype_before": self.dtype_before,
            "written": str(self.written) if self.written else "",
            "skipped": self.skipped, "problems": list(self.problems),
            "worthwhile": self.worthwhile,
        }


def _folder_gb(folder: Path) -> float:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) / 1e9


def inspect(model_path: str | Path, component: str = "text_encoder") -> Recast:
    """What recasting this component would save, without doing it.

    Called before offering the operation, so a model that would gain nothing
    is never proposed — the commonest case, since most components already ship
    at the precision they are used in.
    """
    root = Path(model_path)
    folder = root / component
    found = Recast(component=component, source=folder)

    if not folder.is_dir():
        found.skipped = f"{component} is not a folder in this model"
        return found

    found.before_gb = _folder_gb(folder)
    config = folder / "config.json"
    if not config.is_file():
        found.skipped = "no config.json, so the stored precision is unknown"
        return found
    try:
        found.dtype_before = str(json.loads(config.read_text()).get("torch_dtype") or "")
    except (OSError, ValueError):
        found.skipped = "config.json could not be read"
        return found

    if found.dtype_before.lower() not in WIDE:
        found.skipped = (f"already stored as {found.dtype_before or 'an unstated '
                                              'precision'}")
        return found

    # float32 to bfloat16 is exactly half the bytes; nothing else in the folder
    # changes size.
    # Kept precise. Rounding lives in `to_dict`, which is where a figure
    # becomes something a person reads — rounding it here made a real saving
    # on a small component disappear into 0.0.
    weights = sum(f.stat().st_size for f in folder.rglob("*.safetensors")) / 1e9
    found.after_gb = found.before_gb - weights / 2
    return found


def recast(model_path: str | Path, component: str = "text_encoder", *,
           into: str | Path | None = None, replace: bool = False,
           on_progress=None) -> Recast:
    """Write a bfloat16 copy of one component beside the original.

    Verified before it is called done: every tensor the original declared has
    to be present afterwards, at the new precision, with its shape intact. A
    half-written component that looks finished is worse than no recast, because
    it fails at load time on somebody's machine rather than here.

    `replace` swaps the original out afterwards, and is only right immediately
    after a download: nobody has invested anything in those bytes but the
    bandwidth, and keeping the float32 beside its own bfloat16 copy doubles
    what the install costs on disk for no benefit. Everywhere else the original
    stays, because it is somebody's forty-minute download.
    """
    import torch
    from safetensors.torch import load_file, save_file

    found = inspect(model_path, component)
    if found.skipped:
        return found

    root = Path(model_path)
    folder = root / component
    destination = Path(into) if into else root / f"{component}-{TARGET}"
    staging = destination.with_name(f".{destination.name}.writing")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    try:
        shards = sorted(folder.glob("*.safetensors"))
        for n, shard in enumerate(shards, 1):
            if on_progress:
                on_progress(n, len(shards), shard.name)
            tensors = load_file(str(shard))
            narrowed = {k: (v.to(torch.bfloat16)
                            if v.is_floating_point() else v)
                        for k, v in tensors.items()}
            save_file(narrowed, str(staging / shard.name),
                      metadata={"format": "pt"})

            # Checked per shard rather than at the end: a mismatch found now
            # names the file, and one found later names nothing.
            written = load_file(str(staging / shard.name))
            if set(written) != set(tensors):
                found.problems.append(f"{shard.name}: tensors went missing")
            elif any(written[k].shape != tensors[k].shape for k in tensors):
                found.problems.append(f"{shard.name}: a shape changed")
            del tensors, narrowed, written

        # Everything that is not weights travels unchanged — the tokenizer
        # files, the index, the config, whose dtype is then corrected.
        for extra in folder.iterdir():
            if extra.suffix == ".safetensors" or extra.is_dir():
                continue
            shutil.copy2(extra, staging / extra.name)

        config_path = staging / "config.json"
        if config_path.is_file():
            config = json.loads(config_path.read_text())
            config["torch_dtype"] = TARGET
            config_path.write_text(json.dumps(config, indent=2) + "\n")

        if found.problems:
            shutil.rmtree(staging, ignore_errors=True)
            return found

        shutil.rmtree(destination, ignore_errors=True)
        shutil.move(str(staging), str(destination))
        found.written = destination
        found.after_gb = _folder_gb(destination)

        if replace:
            # Swap rather than delete-then-move: for the moment between them
            # there is always one complete copy on disk, so an interruption
            # leaves a working model rather than a folder with no encoder.
            retired = folder.with_name(f".{folder.name}.replaced")
            shutil.rmtree(retired, ignore_errors=True)
            shutil.move(str(folder), str(retired))
            shutil.move(str(destination), str(folder))
            shutil.rmtree(retired, ignore_errors=True)
            found.written = folder
        return found
    finally:
        shutil.rmtree(staging, ignore_errors=True)
