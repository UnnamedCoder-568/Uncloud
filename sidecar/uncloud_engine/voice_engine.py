from __future__ import annotations

import time
import uuid
from pathlib import Path
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


_transformers_whisper: dict[str, Any] = {}


def _get_transformers_whisper(model_path: str):
    """A Whisper checkpoint in the transformers format, on the Apple GPU when
    there is one. Held once loaded: dictation and conversation call this every
    turn, and reloading a model per sentence is most of the wait."""
    if _transformers_whisper.get("path") != model_path:
        import torch
        from transformers import pipeline

        _transformers_whisper.clear()
        device = ("mps" if torch.backends.mps.is_available()
                  else 0 if torch.cuda.is_available() else "cpu")
        _transformers_whisper["pipe"] = pipeline(
            "automatic-speech-recognition", model=model_path, device=device,
            dtype=torch.float16 if device != "cpu" else torch.float32)
        _transformers_whisper["path"] = model_path
    return _transformers_whisper["pipe"]


def transcribe(model_path: str, audio_path: str) -> str:
    folder = Path(model_path)
    if not (folder / "model.bin").is_file() and (folder / "config.json").is_file():
        # Decoded by PyAV, which faster-whisper already brings: the transformers
        # pipeline would otherwise want an ffmpeg binary to read a browser's webm.
        from faster_whisper import decode_audio

        audio = decode_audio(audio_path, sampling_rate=16000)
        if not len(audio):
            return ""
        # Whisper hears thirty seconds at a time. Past that it must be told to
        # work through the recording, or it transcribes the first half-minute.
        longer = len(audio) > 30 * 16000
        result = _get_transformers_whisper(model_path)(
            {"raw": audio, "sampling_rate": 16000},
            **({"chunk_length_s": 30, "return_timestamps": True} if longer else {}))
        return str(result.get("text", "")).strip()
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

    words = "".join(ch for ch in " ".join(text.split()[:6]) if ch.isalnum() or ch in " -")
    out_path = output_dir_for("voice/replies") / (
        f"{time.strftime('%Y-%m-%d %H.%M.%S')} {words[:48].strip()} {uuid.uuid4().hex[:4]}.wav")
    sf.write(str(out_path), full, 24000)
    return str(out_path)
