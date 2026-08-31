from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

OUTPUT_DIR = Path.home() / ".uncloud" / "outputs" / "narration"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

VOICES_DIR = Path.home() / ".uncloud" / "voices"
VOICES_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_RATES = [24000, 44100, 48000]
BIT_DEPTHS = [16, 24, 32]
AUDIO_FORMATS = ["wav", "aiff"]  # Logic reads both natively; it cannot read FLAC.

# Diffusion steps for the acoustic decoder. Microsoft's demo uses 5, which is tuned
# for realtime latency rather than fidelity — higher values sound less compressed.
QUALITY_PRESETS = {"fast": 5, "balanced": 20, "high": 40, "max": 64}

# VibeVoice pins huggingface-hub<1.0, which the main engine can't satisfy, so it runs
# in its own environment — the same isolation used for ACE-Step.
_SIDE = Path(__file__).resolve().parent.parent

# Two engines, because the two checkpoints need incompatible package versions.
#   realtime — Microsoft's current package, streaming 0.5B. Fast, slightly compressed.
#   quality  — community fork, full 1.5B with the semantic tokenizer. Fuller, slower.
ENGINES = {
    "realtime": {
        "label": "Realtime (0.5B)",
        "python": _SIDE / ".venv-vibevoice" / "bin" / "python",
        "runner": _SIDE / "scripts" / "vibevoice_runner.py",
        "voice_kind": "cache",   # prefilled .pt
        "note": "Faster than real time. Slightly compressed sound.",
    },
    "quality": {
        "label": "Quality (1.5B)",
        "python": _SIDE / ".venv-vibevoice-hq" / "bin" / "python",
        "runner": _SIDE / "scripts" / "vibevoice_hq_runner.py",
        "voice_kind": "audio",   # raw reference recording
        "note": "Fuller, more natural. Noticeably slower.",
    },
}

VIBEVOICE_VENV = ENGINES["realtime"]["python"].parent.parent


from .power import keep_awake


def engine_available(name: str) -> bool:
    e = ENGINES.get(name)
    return bool(e and Path(e["python"]).is_file() and Path(e["runner"]).is_file())


def vibevoice_available() -> bool:
    return any(engine_available(n) for n in ENGINES)


def available_engines() -> list[dict]:
    return [
        {"id": n, "label": e["label"], "note": e["note"],
         "voice_kind": e["voice_kind"], "installed": engine_available(n)}
        for n, e in ENGINES.items()
    ]


@dataclass
class NarrationJob:
    id: str
    status: str = "pending"  # pending | running | done | error
    stage: str = ""
    chars: int = 0
    output_path: str | None = None
    duration_s: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "status": self.status, "stage": self.stage,
            "chars": self.chars, "output_path": self.output_path,
            "duration_s": round(self.duration_s, 1),
            "done": self.status in ("done", "error"), "error": self.error,
        }


@dataclass
class Voice:
    """A reusable narrator. Either a bundled preset or a user-supplied sample
    that the model conditions on (zero-shot cloning)."""

    slug: str
    name: str
    kind: str = "cloned"  # preset | cloned
    sample_path: str | None = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "slug": self.slug, "name": self.name, "kind": self.kind,
            "has_sample": bool(self.sample_path and Path(self.sample_path).exists()),
            "notes": self.notes,
        }


_LANG_NAMES = {
    "en": "English", "de": "German", "fr": "French", "it": "Italian",
    "jp": "Japanese", "kr": "Korean", "nl": "Dutch", "pl": "Polish",
    "pt": "Portuguese", "sp": "Spanish", "in": "Indian English",
}


def _preset_dir(voice_kind: str) -> Path:
    """Voice presets live under the models folder, split by what each engine needs:
    the streaming model wants prefilled .pt caches, the full model wants raw audio."""
    from .config import settings

    return settings.models_dir / (
        "vibevoice-voices" if voice_kind == "cache" else "vibevoice-voices-audio"
    )


def list_voices(engine: str = "realtime") -> list[Voice]:
    """Bundled presets plus anything the user has saved, filtered to what the
    chosen engine can actually consume.

    The streaming model takes a prefilled KV cache (.pt) — the speaker is baked in.
    The full model takes a raw reference recording and conditions on it directly.
    """
    voice_kind = ENGINES.get(engine, ENGINES["realtime"])["voice_kind"]
    pattern = "*.pt" if voice_kind == "cache" else "*.wav"
    out: list[Voice] = []

    root = _preset_dir(voice_kind)
    if root.is_dir():
        for f in sorted(root.glob(pattern)):
            stem = f.stem                       # e.g. "en-Carter_man"
            lang, _, rest = stem.partition("-")
            person, _, gender = rest.partition("_")
            label = person.replace("_", " ") or stem
            language = _LANG_NAMES.get(lang, lang.upper())
            notes = f"{language}{f' · {gender}' if gender else ''}"
            out.append(Voice(slug=stem, name=label, kind="preset",
                             sample_path=str(f), notes=notes))

    for child in sorted(VOICES_DIR.iterdir()) if VOICES_DIR.exists() else []:
        if not child.is_dir():
            continue
        cache = next(child.glob(pattern), None)
        meta = child / "voice.json"
        name, notes = child.name, ""
        if meta.exists():
            import json

            try:
                data = json.loads(meta.read_text())
                name = data.get("name", name)
                notes = data.get("notes", "")
            except (OSError, ValueError):
                pass
        out.append(Voice(slug=child.name, name=name, kind="cloned",
                         sample_path=str(cache) if cache else None, notes=notes))

    return out


def save_voice(name: str, sample_path: str | None, notes: str = "") -> Voice:
    import json
    import re
    import shutil

    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "voice"
    target = VOICES_DIR / slug
    target.mkdir(parents=True, exist_ok=True)
    (target / "voice.json").write_text(json.dumps({"name": name.strip(), "notes": notes}, indent=2))

    stored: str | None = None
    if sample_path:
        src = Path(sample_path)
        if not src.exists():
            raise FileNotFoundError(f"Voice sample not found: {sample_path}")
        dest = target / f"sample{src.suffix.lower() or '.wav'}"
        shutil.copyfile(src, dest)
        stored = str(dest)
    else:
        existing = next(target.glob("sample.*"), None)
        stored = str(existing) if existing else None

    return Voice(slug=slug, name=name.strip(), kind="cloned", sample_path=stored, notes=notes)


def delete_voice(slug: str) -> bool:
    import shutil

    target = VOICES_DIR / slug
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True


class NarrationEngine:
    """Long-form narration via VibeVoice, which synthesises up to ~90 minutes in a
    single pass rather than stitching 30-second chunks. That matters: chunked TTS
    drifts in timbre and pacing across a long read, and the joins are audible.
    """

    def __init__(self) -> None:
        self.jobs: dict[str, NarrationJob] = {}
        self._model = None
        self._processor = None
        self._model_dir: str | None = None

    def list_jobs(self) -> list[dict]:
        return [j.to_dict() for j in self.jobs.values()]

    def unload(self) -> None:
        self._model = None
        self._processor = None
        self._model_dir = None

    def start(
        self, model_dir: str, text: str, *, voice_slug: str = "",
        sample_rate: int = 44100, bit_depth: int = 24, cfg_scale: float = 1.3,
        ddpm_steps: int = 20, audio_format: str = "wav", engine: str = "realtime",
    ) -> NarrationJob:
        job = NarrationJob(id=uuid.uuid4().hex[:12], chars=len(text))
        self.jobs[job.id] = job
        asyncio.create_task(self._run(job, model_dir, text, voice_slug, sample_rate,
                                      bit_depth, cfg_scale, ddpm_steps, audio_format, engine))
        return job

    async def _run(
        self, job: NarrationJob, model_dir: str, text: str, voice_slug: str,
        sample_rate: int, bit_depth: int, cfg_scale: float, ddpm_steps: int,
        audio_format: str, engine: str,
    ) -> None:
        job.status = "running"
        job.stage = "loading model"
        try:
            # Long reads outlast the display timeout; without this the machine
            # suspends mid-generation and the job is still sitting there later.
            with keep_awake("narration"):
                from .engines import engine_manager

                if engine_manager.active:
                    engine_manager.stop()

                out = await asyncio.to_thread(
                    self._synthesise, job, model_dir, text, voice_slug,
                    sample_rate, bit_depth, cfg_scale, ddpm_steps, audio_format, engine,
                )
                job.output_path = out
                job.status = "done"
                job.stage = ""
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            job.status = "error"
            job.error = str(exc)

    def _synthesise(
        self, job: NarrationJob, model_dir: str, text: str, voice_slug: str,
        sample_rate: int, bit_depth: int, cfg_scale: float, ddpm_steps: int = 20,
        audio_format: str = "wav", engine: str = "realtime",
    ) -> str:
        import json
        import subprocess

        spec = ENGINES.get(engine)
        if spec is None:
            raise ValueError(f"Unknown narration engine: {engine}")
        if not engine_available(engine):
            raise RuntimeError(
                f"The {spec['label']} engine is not installed. "
                f"Expected an interpreter at {spec['python']}."
            )

        job.stage = "narrating"
        voice_sample = None
        if voice_slug:
            voice = next((v for v in list_voices(engine) if v.slug == voice_slug), None)
            if voice and voice.sample_path:
                voice_sample = voice.sample_path

        dest = OUTPUT_DIR / f"{job.id}.{audio_format}"
        cfg = {
            "model_dir": model_dir,
            "text": text,
            "out_path": str(dest),
            "sample_rate": sample_rate,
            "bit_depth": bit_depth,
            "cfg_scale": cfg_scale,
            "ddpm_steps": ddpm_steps,
            "audio_format": audio_format,
            "voice_path": voice_sample,
        }

        started = time.monotonic()
        proc = subprocess.run(
            [str(spec["python"]), str(spec["runner"]), json.dumps(cfg)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-1500:]
            raise RuntimeError(f"{spec['label']} exited {proc.returncode}:\n{tail}")

        for line in (proc.stdout or "").splitlines():
            if line.startswith("DURATION::"):
                try:
                    job.duration_s = float(line.split("DURATION::", 1)[1])
                except ValueError:
                    pass

        if not dest.exists():
            raise RuntimeError(f"VibeVoice produced no audio (ran {time.monotonic() - started:.0f}s)")
        job.stage = "writing wav"
        return str(dest)


narration_engine = NarrationEngine()
