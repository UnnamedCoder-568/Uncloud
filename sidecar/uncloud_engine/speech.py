"""Text to voice and voice to voice: Kokoro, Chatterbox and Bark.

The engines themselves are Core's (`core/speech`); this module is where Uncloud
keeps them — which interpreter each one runs on, where the voices a person
saves live, and the clips they make.

Every clip is kept and listed. Speech used to be written to the output folder
under a random name and never mentioned again, so the voices people liked
most were the ones they could not find.

VibeVoice narration stays in `narration_engine`; its finished reads are listed
here as clips too, so there is one place to find everything spoken.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import output_dir_for, settings
from .core.speech import engines as catalogue
from .core.speech import setup
from .core.speech.worker import Pool, WorkerError

_SIDE = Path(__file__).resolve().parent.parent
STATE = Path.home() / ".uncloud"
#: Shared with narration, whose cloned voices already live here.
VOICES_DIR = STATE / "voices"
CLIPS_INDEX = STATE / "voice-clips.json"
UPLOAD_DIR = STATE / "uploads"

#: Engines whose pins conflict with the main engine get an environment of their
#: own. Kokoro and Bark need nothing the main engine does not already carry.
OWN_ENVIRONMENT = {"chatterbox": _SIDE / ".venv-chatterbox"}

#: A spoken reply longer than this is still spoken, but a conversation that
#: waits minutes for one answer has stopped being a conversation.
REPLY_TIMEOUT = 300

AUDIO_SUFFIXES = (".wav", ".mp3", ".flac", ".m4a", ".ogg", ".webm", ".aiff", ".aif")

pool = Pool()
_clips_lock = threading.Lock()


# -------------------------------------------------------------- environments
def interpreter(engine: str) -> Path:
    venv = OWN_ENVIRONMENT.get(engine)
    return setup.interpreter(venv) if venv else Path(sys.executable)


def installed(engine: str) -> bool:
    """Cheap: whether the interpreter exists. The environment's contents are
    checked when it is built, not every time the list is drawn."""
    venv = OWN_ENVIRONMENT.get(engine)
    return venv is None or setup.interpreter(venv).is_file()


def install(engine: str, on_line=None) -> None:
    venv = OWN_ENVIRONMENT.get(engine)
    if venv is None:
        if on_line:
            on_line(f"{catalogue.ENGINES[engine].label} needs no setup.")
        return
    uv = os.environ.get("UNCLOUD_UV") or shutil.which("uv")
    if not uv:
        raise RuntimeError("Uncloud could not find its bundled uv runtime. Reinstall the "
                           "app and try again.")
    setup.build(engine, venv, uv=uv, on_line=on_line)


# -------------------------------------------------------------------- models
def _kokoro_cache() -> Path | None:
    """Kokoro downloads itself into the Hugging Face cache on first use, so the
    copy most people have is not in the models folder at all."""
    root = Path(os.environ.get("HF_HUB_CACHE")
                or Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
                / "hub")
    snapshots = root / "models--hexgrad--Kokoro-82M" / "snapshots"
    if not snapshots.is_dir():
        return None
    found = [s for s in snapshots.iterdir() if catalogue.recognise(s)]
    return max(found, key=lambda s: s.stat().st_mtime) if found else None


def models() -> list[dict]:
    """Every speech model on this machine that an engine here can run."""
    from .library import scan_library_cached

    out: list[dict] = []
    seen: set[str] = set()
    for m in scan_library_cached(settings.models_dir):
        if m.category != "voice-tts" or m.engine not in catalogue.ENGINES or not m.ready:
            continue
        recognised = catalogue.recognise(Path(m.path))
        if recognised is None:
            continue
        seen.add(str(Path(m.path).resolve()))
        out.append({"path": m.path, "name": m.name, **recognised.to_dict()})
    cached = _kokoro_cache()
    if cached and str(cached.resolve()) not in seen:
        recognised = catalogue.recognise(cached)
        out.append({"path": str(cached), "name": "Kokoro 82M", **recognised.to_dict()})
    return out


def model_for(path: str, engine: str) -> dict:
    """The model at `path`, only if it is one `models()` lists.

    These routes are reachable from paired devices. A path taken on trust would
    let one point the worker at any folder of pickles on the disk.
    """
    wanted = str(Path(path).resolve())
    for m in models():
        if str(Path(m["path"]).resolve()) == wanted and m["engine"] == engine:
            return m
    raise ValueError("That is not a speech model Uncloud knows about. Choose one from "
                     "the list.")


def engines() -> list[dict]:
    listed = models()
    return [{**spec.to_dict(), "installed": installed(spec.id),
             "own_environment": spec.id in OWN_ENVIRONMENT,
             "models": [m for m in listed if m["engine"] == spec.id]}
            for spec in catalogue.ENGINES.values()]


def presets(engine: str, model_path: str) -> list[dict]:
    model = model_for(model_path, engine)
    return [p.to_dict() for p in catalogue.presets(engine, Path(model["path"]))]


# --------------------------------------------------------------- recordings
def _confined(path: str | None, *roots: Path) -> str | None:
    """A recording path, only if it lives where Uncloud keeps recordings."""
    if not path:
        return None
    resolved = Path(path).resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
        except (ValueError, OSError):
            continue
        if resolved.is_file() and resolved.suffix.lower() in AUDIO_SUFFIXES:
            return str(resolved)
    raise ValueError("Recordings must be added through Uncloud first.")


def recording(path: str | None) -> str | None:
    return _confined(path, UPLOAD_DIR, VOICES_DIR, settings.output_dir)


# -------------------------------------------------------------- saved voices
@dataclass
class SavedVoice:
    """A voice somebody liked, kept so it can be used again anywhere.

    For a preset engine this is the preset and its settings; for Chatterbox it
    can be a recording to speak in. Older narration voices in the same folder
    carry only a name and a recording, and still list.
    """

    slug: str
    name: str
    engine: str = ""
    model_path: str = ""
    variant: str = ""
    preset: str = ""
    language: str = ""
    controls: dict = field(default_factory=dict)
    notes: str = ""
    reference: str | None = None
    created: float = 0.0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["has_recording"] = bool(self.reference and Path(self.reference).is_file())
        return data


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "voice"
    slug, n = base, 2
    while (VOICES_DIR / slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def saved_voices() -> list[SavedVoice]:
    out: list[SavedVoice] = []
    if not VOICES_DIR.is_dir():
        return out
    for folder in sorted(VOICES_DIR.iterdir()):
        if not folder.is_dir():
            continue
        data: dict = {}
        with contextlib.suppress(OSError, ValueError):
            data = json.loads((folder / "voice.json").read_text(encoding="utf-8"))
        sample = next((p for p in folder.glob("sample.*")
                       if p.suffix.lower() in AUDIO_SUFFIXES), None)
        out.append(SavedVoice(
            slug=folder.name, name=str(data.get("name") or folder.name),
            engine=str(data.get("engine", "")), model_path=str(data.get("model_path", "")),
            variant=str(data.get("variant", "")), preset=str(data.get("preset", "")),
            language=str(data.get("language", "")),
            controls=data.get("controls") if isinstance(data.get("controls"), dict) else {},
            notes=str(data.get("notes", "")),
            reference=str(sample) if sample else None,
            created=float(data.get("created") or folder.stat().st_mtime)))
    return out


def saved_voice(slug: str) -> SavedVoice:
    for voice in saved_voices():
        if voice.slug == slug:
            return voice
    raise ValueError(f"No saved voice called {slug!r}")


def save_voice(*, name: str, engine: str, model_path: str = "", variant: str = "",
               preset: str = "", language: str = "", controls: dict | None = None,
               notes: str = "", recording_path: str | None = None) -> SavedVoice:
    if not name.strip():
        raise ValueError("Give the voice a name")
    if engine not in catalogue.ENGINES:
        raise ValueError(f"No speech engine called {engine!r}")
    if model_path:
        model_for(model_path, engine)
    source = recording(recording_path)
    if source and not catalogue.ENGINES[engine].clones:
        raise ValueError(f"{catalogue.ENGINES[engine].label} cannot speak in a recorded "
                         "voice; choose one of its own voices.")
    slug = _slug(name)
    folder = VOICES_DIR / slug
    folder.mkdir(parents=True)
    if source:
        shutil.copyfile(source, folder / f"sample{Path(source).suffix.lower()}")
    record = {"name": name.strip(), "engine": engine, "model_path": model_path,
              "variant": variant, "preset": preset, "language": language,
              "controls": {k: float(v) for k, v in (controls or {}).items()},
              "notes": notes, "created": time.time()}
    (folder / "voice.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return saved_voice(slug)


def delete_voice(slug: str) -> bool:
    folder = (VOICES_DIR / slug).resolve()
    if folder.parent != VOICES_DIR.resolve() or not folder.is_dir():
        return False
    shutil.rmtree(folder)
    return True


# --------------------------------------------------------------------- clips
@dataclass
class Clip:
    id: str
    name: str
    path: str
    kind: str            # speech | conversion | reply | narration
    engine: str = ""
    voice: str = ""
    text: str = ""
    duration: float = 0.0
    created: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _read_index() -> list[dict]:
    try:
        data = json.loads(CLIPS_INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _write_index(entries: list[dict]) -> None:
    CLIPS_INDEX.parent.mkdir(parents=True, exist_ok=True)
    tmp = CLIPS_INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=1), encoding="utf-8")
    tmp.replace(CLIPS_INDEX)


def clips(kind: str = "") -> list[Clip]:
    """Newest first, forgetting any whose file has gone."""
    with _clips_lock:
        entries = _read_index()
        kept = [e for e in entries if Path(e.get("path", "")).is_file()]
        if len(kept) != len(entries):
            _write_index(kept)
    found = [Clip(**{k: e.get(k) for k in Clip.__dataclass_fields__ if k in e})
             for e in kept]
    if kind:
        found = [c for c in found if c.kind == kind]
    return sorted(found, key=lambda c: c.created, reverse=True)


def add_clip(clip: Clip) -> Clip:
    with _clips_lock:
        entries = _read_index()
        entries.append(clip.to_dict())
        _write_index(entries)
    return clip


def clip(clip_id: str) -> Clip:
    for c in clips():
        if c.id == clip_id:
            return c
    raise ValueError("No such clip")


def _file_name(text: str) -> str:
    words = re.sub(r"[^\w\s-]", "", " ".join(text.split()[:6]), flags=re.UNICODE).strip()
    return f"{time.strftime('%Y-%m-%d %H.%M.%S')} {words[:48]}".strip()


def _unique(path: Path) -> Path:
    candidate, n = path, 2
    while candidate.exists():
        candidate, n = path.with_name(f"{path.stem} ({n}){path.suffix}"), n + 1
    return candidate


def rename_clip(clip_id: str, name: str) -> Clip:
    """Renames the file as well as the entry: a clip saved as "Intro take 2"
    should be called that in Finder too."""
    safe = re.sub(r'[\\/:*?"<>|]+', "", name).strip()
    if not safe:
        raise ValueError("Give the clip a name")
    with _clips_lock:
        entries = _read_index()
        for entry in entries:
            if entry.get("id") == clip_id:
                old = Path(entry["path"])
                new = _unique(old.with_name(f"{safe}{old.suffix}"))
                if old.is_file():
                    old.rename(new)
                entry.update(name=safe, path=str(new))
                _write_index(entries)
                return Clip(**{k: entry.get(k) for k in Clip.__dataclass_fields__})
    raise ValueError("No such clip")


def delete_clip(clip_id: str) -> bool:
    from . import outputs

    target = clip(clip_id)
    # Outside the output folder (moved by hand): forget it, and leave the file.
    with contextlib.suppress(ValueError):
        outputs.delete(target.path)
    with _clips_lock:
        _write_index([e for e in _read_index() if e.get("id") != clip_id])
    return True


def record_narration(path: str, text: str, engine: str, voice: str, duration: float) -> None:
    """Called when a VibeVoice read finishes, so narration lists with the rest."""
    add_clip(Clip(id=uuid.uuid4().hex[:12], name=_file_name(text), path=path,
                  kind="narration", engine=f"vibevoice-{engine}", voice=voice,
                  text=text[:500], duration=duration, created=time.time()))


# ---------------------------------------------------------------------- jobs
@dataclass
class SpeechJob:
    id: str
    kind: str
    status: str = "running"     # running | done | error
    stage: str = "starting"
    done: int = 0
    total: int = 0
    clip: dict | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {**asdict(self), "finished": self.status in ("done", "error")}


jobs: dict[str, SpeechJob] = {}


def _voice_request(engine: str, model_path: str, *, voice: str = "",
                   saved: str = "", recording_path: str | None = None,
                   language: str = "", variant: str = "",
                   controls: dict | None = None) -> tuple[dict, str]:
    """The worker request for a voice, and a label for it.

    A saved voice supplies whatever the request leaves out, so choosing one is
    enough; anything set explicitly still wins.
    """
    label = voice
    request: dict = {"engine": engine, "variant": variant, "voice": voice,
                     "language": language, "controls": dict(controls or {})}
    if saved:
        kept = saved_voice(saved)
        if kept.engine and kept.engine != engine:
            raise ValueError(f"{kept.name} is a {kept.engine} voice")
        request["voice"] = voice or kept.preset
        request["variant"] = variant or kept.variant
        request["language"] = language or kept.language
        request["controls"] = {**kept.controls, **request["controls"]}
        recording_path = recording_path or kept.reference
        model_path = model_path or kept.model_path
        label = kept.name
    model = model_for(model_path, engine)
    request["folder"] = model["path"]
    if label == "default" and engine == "chatterbox":
        label = "built-in voice"
    reference = recording(recording_path)
    if reference:
        if not catalogue.ENGINES[engine].clones:
            raise ValueError(f"{catalogue.ENGINES[engine].label} cannot speak in a "
                             "recorded voice")
        request["reference"] = reference
        label = label or "recorded voice"
    return request, label or model["name"]


def start_speech(*, text: str, engine: str, model_path: str, voice: str = "",
                 saved: str = "", recording_path: str | None = None, language: str = "",
                 variant: str = "", controls: dict | None = None, audio_format: str = "wav",
                 sample_rate: int | None = None, bit_depth: int = 24) -> SpeechJob:
    if not text.strip():
        raise ValueError("There is nothing to say")
    if not installed(engine):
        raise ValueError(f"{catalogue.ENGINES[engine].label} is not set up yet")
    request, label = _voice_request(engine, model_path, voice=voice, saved=saved,
                                    recording_path=recording_path, language=language,
                                    variant=variant, controls=controls)
    fmt = audio_format if audio_format in ("wav", "flac", "aiff") else "wav"
    out = _unique(output_dir_for("voice") / f"{_file_name(text)}.{fmt}")
    request.update(op="speak", text=text, out=str(out), format=fmt,
                   sample_rate=sample_rate, bit_depth=bit_depth)
    job = SpeechJob(id=uuid.uuid4().hex[:12], kind="speech")
    jobs[job.id] = job

    def finished(result: dict) -> Clip:
        return add_clip(Clip(id=job.id, name=out.stem, path=result["path"], kind="speech",
                             engine=engine, voice=label, text=text[:500],
                             duration=float(result.get("duration", 0)),
                             created=time.time()))

    _run(job, engine, request, finished)
    return job


def start_conversion(*, model_path: str, source_path: str, saved: str = "",
                     recording_path: str | None = None) -> SpeechJob:
    """Voice to voice: what a recording says, in another voice."""
    if not installed("chatterbox"):
        raise ValueError("Chatterbox is not set up yet")
    model = model_for(model_path, "chatterbox")
    if not model.get("converts"):
        raise ValueError("These Chatterbox weights cannot convert voices")
    source = recording(source_path)
    if not source:
        raise ValueError("Add the recording to convert")
    label = "built-in voice"
    if saved:
        kept = saved_voice(saved)
        recording_path = recording_path or kept.reference
        label = kept.name
    reference = recording(recording_path)
    out = _unique(output_dir_for("voice") / f"{_file_name('Converted recording')}.wav")
    request = {"op": "convert", "folder": model["path"], "source": source,
               "reference": reference, "out": str(out), "bit_depth": 24}
    job = SpeechJob(id=uuid.uuid4().hex[:12], kind="conversion")
    jobs[job.id] = job

    def finished(result: dict) -> Clip:
        return add_clip(Clip(id=job.id, name=out.stem, path=result["path"],
                             kind="conversion", engine="chatterbox", voice=label,
                             duration=float(result.get("duration", 0)),
                             created=time.time()))

    _run(job, "chatterbox", request, finished)
    return job


def _run(job: SpeechJob, engine: str, request: dict, finished) -> None:
    from .power import keep_awake

    def progress(done: int, total: int) -> None:
        job.done, job.total, job.stage = done, total, "speaking"

    def work() -> None:
        try:
            with keep_awake("speech"):
                job.stage = "loading the voice"
                result = pool.get(interpreter(engine)).request(request, on_progress=progress)
            job.clip = finished(result).to_dict()
            job.status, job.stage = "done", ""
        except (WorkerError, ValueError, OSError) as exc:
            job.status, job.error, job.stage = "error", str(exc), ""

    threading.Thread(target=work, daemon=True, name=f"speech-{job.id}").start()


def speak_reply(text: str, saved: str) -> Clip:
    """A spoken Chat or Chisel reply in a saved voice. Blocking, and kept as a
    clip so a reply worth keeping is not lost with the conversation."""
    kept = saved_voice(saved)
    if not kept.engine:
        raise ValueError(f"{kept.name} has no engine; open it in Voice and save it again")
    if not installed(kept.engine):
        raise ValueError(f"{catalogue.ENGINES[kept.engine].label} is not set up yet")
    request, label = _voice_request(kept.engine, kept.model_path, saved=saved)
    out = _unique(output_dir_for("voice/replies") / f"{_file_name(text)}.wav")
    request.update(op="speak", text=text, out=str(out), format="wav", bit_depth=16)
    result = pool.get(interpreter(kept.engine)).request(request, timeout=REPLY_TIMEOUT)
    return add_clip(Clip(id=uuid.uuid4().hex[:12], name=out.stem, path=result["path"],
                         kind="reply", engine=kept.engine, voice=label, text=text[:500],
                         duration=float(result.get("duration", 0)), created=time.time()))


def record_reply(path: str, text: str, voice: str) -> Clip:
    """A reply Kokoro spoke in-process, listed like every other clip."""
    duration = 0.0
    with contextlib.suppress(Exception):  # a length is nice to show, not worth failing for
        import soundfile as sf

        duration = round(float(sf.info(path).duration), 2)
    return add_clip(Clip(id=uuid.uuid4().hex[:12], name=Path(path).stem, path=path,
                         kind="reply", engine="kokoro", voice=voice, text=text[:500],
                         duration=duration, created=time.time()))


def stop() -> None:
    pool.stop_all()


def resident_count() -> int:
    """Live voice workers. Reading status must never stop them."""
    return pool.resident_count()
