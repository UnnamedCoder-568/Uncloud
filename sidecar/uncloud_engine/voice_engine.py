from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

OUTPUT_DIR = Path.home() / ".uncloud" / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

_whisper: dict[str, Any] = {}
_kokoro: dict[str, Any] = {}

KOKORO_VOICES = [
    "af_heart", "af_bella", "af_nicole", "af_sarah",
    "am_adam", "am_michael", "bf_emma", "bm_george",
]


def _get_whisper_model(model_path: str):
    from faster_whisper import WhisperModel

    if _whisper.get("path") != model_path:
        _whisper.clear()
        _whisper["model"] = WhisperModel(model_path, device="cpu", compute_type="int8")
        _whisper["path"] = model_path
    return _whisper["model"]


def transcribe(model_path: str, audio_path: str) -> str:
    model = _get_whisper_model(model_path)
    segments, _info = model.transcribe(audio_path)
    return " ".join(seg.text.strip() for seg in segments).strip()


def _get_kokoro_pipeline():
    if "pipeline" not in _kokoro:
        from kokoro import KPipeline

        _kokoro["pipeline"] = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    return _kokoro["pipeline"]


def speak(text: str, voice: str = "af_heart", speed: float = 1.0) -> str:
    import numpy as np
    import soundfile as sf

    pipeline = _get_kokoro_pipeline()
    chunks = [audio for _graphemes, _phonemes, audio in pipeline(text, voice=voice, speed=speed)]
    if not chunks:
        raise RuntimeError("Kokoro produced no audio for this text")
    full = np.concatenate([c if isinstance(c, np.ndarray) else c.numpy() for c in chunks])

    out_path = OUTPUT_DIR / f"{uuid.uuid4().hex[:12]}.wav"
    sf.write(str(out_path), full, 24000)
    return str(out_path)
