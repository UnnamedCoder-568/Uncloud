"""Building the environment a speech engine runs in.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Standard library only.

Where the environment lives and where `uv` is are the product's to say; what
goes into it comes from the engine's own record in `engines`.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from .engines import ENGINES


def interpreter(venv: Path, *, windows: bool | None = None) -> Path:
    """The Python inside an environment uv created, on either platform."""
    if windows is None:
        windows = os.name == "nt"
    return Path(venv) / ("Scripts/python.exe" if windows else "bin/python")


def satisfies(python: Path | str, engine: str, *, timeout: float = 60) -> bool:
    """Whether an interpreter can already import everything the engine needs.

    Checked by finding the modules, not importing them: importing torch to
    answer a yes-or-no question costs seconds each time the list is shown.
    """
    spec = ENGINES.get(engine)
    if spec is None or not Path(python).is_file():
        return False
    probe = ("import importlib.util, sys; "
             f"sys.exit(0 if all(importlib.util.find_spec(m) for m in {list(spec.modules)!r}) "
             "else 1)")
    try:
        return subprocess.run([str(python), "-c", probe], capture_output=True,
                              timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def build(engine: str, venv: Path, *, uv: str, python_version: str = "3.12",
          on_line: Callable[[str], None] | None = None) -> Path:
    """Create the environment and install the engine into it. Streams the log.

    Returns the interpreter. Raises RuntimeError with the reason when a step
    fails — the log already shown says the rest.
    """
    spec = ENGINES.get(engine)
    if spec is None:
        raise ValueError(f"No speech engine called {engine!r}")
    venv = Path(venv)
    steps = [
        [uv, "venv", str(venv), "--python", python_version, "--allow-existing"],
        [uv, "pip", "install", "--python", str(interpreter(venv)), *spec.requirements],
    ]
    for step in steps:
        if on_line:
            on_line(f"$ {' '.join(step)}")
        process = subprocess.Popen(step, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        for line in process.stdout or []:
            if on_line:
                on_line(line.rstrip())
        if process.wait() != 0:
            raise RuntimeError(f"Setting up {spec.label} failed; the log above says why.")
    python = interpreter(venv)
    if not satisfies(python, engine):
        raise RuntimeError(f"{spec.label} installed, but its environment still cannot "
                           f"load it.")
    return python
