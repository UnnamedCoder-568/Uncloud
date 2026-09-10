from __future__ import annotations

import uuid
from typing import Any

from .config import output_dir_for

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
    """The speech pipeline, preferring what is already on this machine.

    Kokoro resolves its weights by Hugging Face repo id, and huggingface_hub
    contacts the hub even when every file is already cached. On a machine with
    no connection that check fails and speech fails with it — for a 313MB model
    sitting on the disk, in an application whose whole promise is that it does
    not need the internet.

    So: cache first, and only reach out if something is genuinely missing. That
    keeps the first run downloading as it must, and every later run working on
    an aeroplane.
    """
    if "pipeline" in _kokoro:
        return _kokoro["pipeline"]

    import huggingface_hub.constants as hub
    from kokoro import KPipeline

    was_offline = hub.HF_HUB_OFFLINE
    hub.HF_HUB_OFFLINE = True
    try:
        _kokoro["pipeline"] = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    except Exception:  # noqa: BLE001 - not cached yet; fetch it properly
        hub.HF_HUB_OFFLINE = was_offline
        _kokoro["pipeline"] = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    finally:
        hub.HF_HUB_OFFLINE = was_offline
    return _kokoro["pipeline"]


def speak(text: str, voice: str = "af_heart", speed: float = 1.0) -> str:
    import numpy as np
    import soundfile as sf

    pipeline = _get_kokoro_pipeline()
    chunks = [audio for _graphemes, _phonemes, audio in pipeline(text, voice=voice, speed=speed)]
    if not chunks:
        raise RuntimeError("Kokoro produced no audio for this text")
    full = np.concatenate([c if isinstance(c, np.ndarray) else c.numpy() for c in chunks])

    out_path = output_dir_for() / f"{uuid.uuid4().hex[:12]}.wav"
    sf.write(str(out_path), full, 24000)
    return str(out_path)
