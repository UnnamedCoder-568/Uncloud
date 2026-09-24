from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .config import output_dir_for
from .power import keep_awake

# Logic Pro imports either happily; 44.1kHz/24-bit is the usual session default.
SAMPLE_RATES = [44100, 48000, 96000]
BIT_DEPTHS = [16, 24, 32]
# Logic imports WAV and AIFF natively. It does NOT read FLAC, so that isn't offered.
AUDIO_FORMATS = ["wav", "aiff"]

# ACE-Step's turbo model is tuned for 8 steps; more steps trade time for detail.
QUALITY_PRESETS = {"draft": 4, "standard": 8, "high": 16, "max": 32}

# Demucs' four-stem model. Names match what it writes to disk.
STEM_NAMES = ("drums", "bass", "vocals", "other")


@dataclass
class MusicJob:
    id: str
    prompt: str
    status: str = "pending"  # pending | running | separating | done | error
    stage: str = ""
    output_path: str | None = None
    stems: dict[str, str] = field(default_factory=dict)
    duration: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "prompt": self.prompt, "status": self.status,
            "stage": self.stage, "output_path": self.output_path,
            "stems": self.stems, "duration": self.duration,
            "done": self.status in ("done", "error"), "error": self.error,
        }


def _write_audio(audio, sample_rate: int, dest: Path, bit_depth: int, fmt: str = "wav") -> None:
    """Write a float array out at the requested depth. Logic reads all three,
    but 24-bit PCM is the sane default for anything heading into a session."""
    import numpy as np
    import soundfile as sf

    # AIFF has no float subtype in libsndfile, so 32-bit there means PCM_32.
    if fmt == "aiff":
        subtype = {16: "PCM_16", 24: "PCM_24", 32: "PCM_32"}[bit_depth]
    else:
        subtype = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}[bit_depth]
    data = np.asarray(audio)
    if data.ndim == 1:
        data = data[:, None]
    # soundfile wants frames-major; models commonly emit channels-major.
    if data.shape[0] < data.shape[1]:
        data = data.T
    sf.write(str(dest), data, sample_rate, subtype=subtype, format=fmt.upper())


# ACE-Step hard-pins transformers<4.58 and platform-specific CUDA torch builds, which
# can't coexist with the engine's own torch/transformers. It therefore lives in its own
# virtualenv and is driven through its CLI — the same isolation the app already uses for
# llama-server and mflux.
ACESTEP_VENV = Path(__file__).resolve().parent.parent / ".venv-acestep"
ACESTEP_PYTHON = ACESTEP_VENV / (
    "Scripts/python.exe" if os.name == "nt" else "bin/python"
)
ACESTEP_RUNNER = Path(__file__).resolve().parent.parent / "scripts" / "acestep_runner.py"


def acestep_available() -> bool:
    return ACESTEP_PYTHON.is_file() and ACESTEP_RUNNER.is_file()


def install_acestep(on_line=None) -> None:
    """Install ACE-Step into its isolated environment with the bundled uv."""
    uv = os.environ.get("UNCLOUD_UV") or shutil.which("uv")
    if not uv:
        raise RuntimeError("Uncloud could not find its bundled installer. Reinstall the app.")

    def say(line: str) -> None:
        if on_line:
            on_line(line)

    steps = [
        [uv, "venv", str(ACESTEP_VENV), "--python", "3.12", "--allow-existing"],
        [uv, "pip", "install", "--python", str(ACESTEP_VENV),
         "ace-step @ git+https://github.com/ace-step/ACE-Step-1.5"],
    ]
    for step in steps:
        process = subprocess.Popen(
            step, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        for line in process.stdout or []:
            say(line.rstrip())
        if process.wait() != 0:
            raise RuntimeError("ACE-Step setup failed. The installation log explains why.")
    if not acestep_available():
        raise RuntimeError("ACE-Step finished installing but its runtime was not found.")


class MusicEngine:
    """ACE-Step 1.5 for generation, Demucs for stems."""

    def __init__(self) -> None:
        self.jobs: dict[str, MusicJob] = {}
        self._tasks: set[asyncio.Task] = set()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._process_lock = threading.Lock()

    def list_jobs(self) -> list[dict]:
        return [j.to_dict() for j in self.jobs.values()]

    def active_count(self) -> int:
        return sum(1 for job in self.jobs.values() if not job.to_dict()["done"])

    def cancel_all(self) -> bool:
        """Stop active composers/separators and mark their jobs truthfully."""
        active = [job for job in self.jobs.values() if not job.to_dict()["done"]]
        with self._process_lock:
            processes = list(self._processes.values())
        for process in processes:
            try:
                process.terminate()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                with contextlib.suppress(OSError):
                    process.kill()
        for task in list(self._tasks):
            task.cancel()
        for job in active:
            job.status, job.stage, job.error = "error", "", "Stopped"
        return bool(active or processes)

    def start(
        self, model_dir: str, prompt: str, *, lyrics: str = "", instrumental: bool = False,
        duration: float = 180.0, bpm: int | None = None, keyscale: str = "",
        steps: int = 8, guidance: float = 7.0, seed: int | None = None,
        sample_rate: int = 44100, bit_depth: int = 24, separate_stems: bool = False,
        audio_format: str = "wav",
    ) -> MusicJob:
        job = MusicJob(id=uuid.uuid4().hex[:12], prompt=prompt, duration=duration)
        self.jobs[job.id] = job
        task = asyncio.create_task(self._run(
            job, model_dir, prompt, lyrics, instrumental, duration, bpm, keyscale,
            steps, guidance, seed, sample_rate, bit_depth, separate_stems, audio_format,
        ))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run(
        self, job: MusicJob, model_dir: str, prompt: str, lyrics: str, instrumental: bool,
        duration: float, bpm: int | None, keyscale: str, steps: int, guidance: float,
        seed: int | None, sample_rate: int, bit_depth: int, separate_stems: bool,
        audio_format: str,
    ) -> None:
        job.status = "running"
        job.stage = "loading model"
        try:
            # Generation runs for minutes; don't let the machine nap through it.
            with keep_awake("music"):
                # Diffusion models are multi-GB; free the chat model first, same as images.
                from .engines import engine_manager

                if engine_manager.active:
                    engine_manager.stop()

                out = await asyncio.to_thread(
                    self._generate, job, model_dir, prompt, lyrics, instrumental, duration,
                    bpm, keyscale, steps, guidance, seed, sample_rate, bit_depth, audio_format,
                )
                job.output_path = out

                if separate_stems:
                    job.status = "separating"
                    job.stage = "splitting stems"
                    job.stems = await asyncio.to_thread(
                        self._separate, job, out, sample_rate, bit_depth, audio_format)

                job.status = "done"
                job.stage = ""
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            job.status = "error"
            job.error = str(exc)

    def _generate(
        self, job: MusicJob, model_dir: str, prompt: str, lyrics: str, instrumental: bool,
        duration: float, bpm: int | None, keyscale: str, steps: int, guidance: float,
        seed: int | None, sample_rate: int, bit_depth: int, audio_format: str = "wav",
    ) -> str:
        import json

        if not acestep_available():
            raise RuntimeError(
                "ACE-Step is not installed. Set it up with:\n"
                f"  uv pip install --python {ACESTEP_VENV} "
                '"ace-step @ git+https://github.com/ace-step/ACE-Step-1.5"'
            )

        job.stage = "composing"
        work_dir = output_dir_for("music") / job.id
        work_dir.mkdir(parents=True, exist_ok=True)

        cfg = {
            "model_dir": model_dir,
            "save_dir": str(work_dir),
            "prompt": prompt,
            "lyrics": lyrics,
            "instrumental": instrumental,
            "duration": float(duration),
            "bpm": bpm,
            "keyscale": keyscale,
            "steps": steps,
            "guidance": guidance,
            "seed": seed if seed is not None else int(time.time()) % (2**31),
        }
        proc = subprocess.Popen(
            [str(ACESTEP_PYTHON), str(ACESTEP_RUNNER), json.dumps(cfg)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        with self._process_lock:
            self._processes[job.id] = proc
        try:
            stdout, stderr = proc.communicate()
        finally:
            with self._process_lock:
                self._processes.pop(job.id, None)
        if proc.returncode != 0:
            tail = (stderr or stdout or "")[-1500:]
            raise RuntimeError(f"ACE-Step exited {proc.returncode}:\n{tail}")

        # The runner prints OUTPUT::<path>; fall back to scanning if that's missing.
        produced = None
        for line in reversed((stdout or "").splitlines()):
            if line.startswith("OUTPUT::"):
                candidate = Path(line.split("OUTPUT::", 1)[1].strip())
                if candidate.exists():
                    produced = candidate
                break
        if produced is None:
            produced = self._locate_audio(work_dir)
        job.stage = f"writing {audio_format}"
        dest = output_dir_for("music") / f"{job.id}.{audio_format}"
        self._transcode(produced, dest, sample_rate, bit_depth, audio_format)
        return str(dest)

    @staticmethod
    def _locate_audio(work_dir: Path) -> Path:
        candidates = [p for ext in ("*.wav", "*.flac", "*.mp3") for p in work_dir.rglob(ext)]
        if not candidates:
            raise RuntimeError("ACE-Step produced no audio file")
        return max(candidates, key=lambda p: p.stat().st_mtime)

    @staticmethod
    def _transcode(src: Path, dest: Path, sample_rate: int, bit_depth: int,
                   fmt: str = "wav") -> None:
        import numpy as np
        import soundfile as sf

        audio, sr = sf.read(str(src), always_2d=True)
        if sr != sample_rate:
            # Linear resample keeps this dependency-free; ACE-Step already emits
            # 44.1k so this is only exercised when the user picks something else.
            ratio = sample_rate / sr
            idx = np.linspace(0, len(audio) - 1, int(len(audio) * ratio))
            audio = np.stack([np.interp(idx, np.arange(len(audio)), audio[:, c])
                              for c in range(audio.shape[1])], axis=1)
        _write_audio(audio, sample_rate, dest, bit_depth, fmt)

    def _separate(self, job: MusicJob, wav_path: str, sample_rate: int,
                  bit_depth: int, fmt: str = "wav") -> dict[str, str]:
        """Split into drums/bass/vocals/other so the result is actually mixable
        in Logic rather than a single frozen stereo file."""
        import sys

        src = Path(wav_path)
        out_root = src.parent / f"{src.stem}_stems"
        out_root.mkdir(parents=True, exist_ok=True)

        proc = subprocess.Popen(
            [sys.executable, "-m", "demucs", "-n", "htdemucs",
             "-o", str(out_root), "--filename", "{stem}.{ext}", str(src)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        with self._process_lock:
            self._processes[job.id] = proc
        try:
            stdout, stderr = proc.communicate()
        finally:
            with self._process_lock:
                self._processes.pop(job.id, None)
        if proc.returncode != 0:
            raise RuntimeError(f"Stem separation failed: {(stderr or stdout or '')[-800:]}")

        stems: dict[str, str] = {}
        for name in STEM_NAMES:
            found = next(out_root.rglob(f"{name}.*"), None)
            if not found:
                continue
            final = out_root / f"{name}.{fmt}"
            if found.suffix.lower() != f".{fmt}" or found != final:
                MusicEngine._transcode(found, final, sample_rate, bit_depth, fmt)
            stems[name] = str(final)
        return stems


music_engine = MusicEngine()
