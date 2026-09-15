"""Text to voice and voice to voice.

Core's speech package decides what a folder of weights is and how to talk to
a worker; `speech` is where Uncloud keeps voices and clips. Nothing here loads
a model: the worker is exercised with requests that need no engine, and the
real engines were measured by hand (see the commit that added this).
"""

from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

import pytest
from test_models import safetensors  # same folder

from uncloud_engine.core.speech import chunks, engines
from uncloud_engine.core.speech.worker import Worker, WorkerError


def touch(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def wav(path: Path, seconds: float = 0.5) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\0\0" * int(8000 * seconds))
    return path


# ------------------------------------------------------------------ chunks
def test_long_text_is_cut_between_sentences_never_inside_one() -> None:
    text = "One two three. Four five six! Seven eight nine? Ten."
    pieces = chunks.chunks(text, 30)
    assert pieces == ["One two three. Four five six!", "Seven eight nine? Ten."]
    assert " ".join(pieces) == text


def test_a_sentence_longer_than_the_limit_is_cut_at_a_comma() -> None:
    sentence = "This clause runs on for a while, and this one keeps going further still."
    pieces = chunks.chunks(sentence, 40)
    assert pieces[0].endswith(",") and all(len(p) <= 40 for p in pieces)


def test_no_limit_means_one_piece() -> None:
    assert chunks.chunks("A. B. C.", 0) == ["A. B. C."]


def test_line_breaks_separate_pieces_of_a_script() -> None:
    assert chunks.sentences("Title\n\nFirst line.\nSecond") == ["Title", "First line.", "Second"]


# ----------------------------------------------------------------- engines
def test_chatterbox_variants_are_read_from_the_files(tmp_path: Path) -> None:
    folder = tmp_path / "anything"
    for name in ("ve.pt", "s3gen.pt", "grapheme_mtl_merged_expanded_v1.json",
                 "t3_mtl23ls_v2.safetensors", "t3_mtl23ls_v3.safetensors", "conds.pt",
                 "s3gen.safetensors"):
        touch(folder / name)
    found = engines.recognise(folder)
    assert found.engine == "chatterbox" and found.converts
    assert [v.id for v in found.variants] == ["multilingual-v3", "multilingual-v2"]
    languages = found.to_dict()["variants"][0]["languages"]
    assert {"id": "en", "name": "English"} in languages


def test_a_folder_is_bark_by_its_architecture_not_its_name(tmp_path: Path) -> None:
    folder = tmp_path / "chatterbox-tts"
    touch(folder / "config.json", json.dumps({"architectures": ["BarkModel"]}).encode())
    touch(folder / "speaker_embeddings_path.json", json.dumps({
        "repo_or_path": "suno/bark-small",
        "en_speaker_1": {}, "v2/en_speaker_1": {}, "announcer": {},
    }).encode())
    assert engines.recognise(folder).engine == "bark"
    presets = engines.presets("bark", folder)
    # The v2 prompt supersedes the original rather than listing twice.
    assert [p.id for p in presets] == ["announcer", "v2/en_speaker_1"]
    assert presets[1].language == "English"


def test_kokoro_voices_are_what_is_on_disk(tmp_path: Path) -> None:
    folder = tmp_path / "kokoro"
    touch(folder / "kokoro-v1_0.pth")
    touch(folder / "config.json", b"{}")
    for voice in ("af_heart", "bm_george", "jf_alpha"):
        touch(folder / "voices" / f"{voice}.pt")
    assert engines.recognise(folder).engine == "kokoro"
    ids = [p.id for p in engines.presets("kokoro", folder)]
    # Japanese needs language packages the engine does not install.
    assert ids == ["af_heart", "bm_george"]


def test_weights_nothing_recognises_are_not_guessed(tmp_path: Path) -> None:
    touch(tmp_path / "x" / "model.safetensors")
    assert engines.recognise(tmp_path / "x") is None


def test_chatterbox_setup_includes_what_its_watermarker_imports() -> None:
    # Without setuptools the watermarker import is swallowed and every model
    # fails to construct — found on a real install.
    assert any(r.startswith("setuptools") for r in engines.ENGINES["chatterbox"].requirements)


# ------------------------------------------------------------------ worker
def test_the_worker_answers_and_survives_a_bad_request() -> None:
    worker = Worker(sys.executable, idle_seconds=0)
    try:
        assert "python" in worker.request({"op": "ping"}, timeout=60)
        with pytest.raises(WorkerError, match="Unknown request"):
            worker.request({"op": "dance"}, timeout=60)
        assert worker.alive
        with pytest.raises(WorkerError, match="nothing to say"):
            worker.request({"op": "speak", "engine": "kokoro", "folder": ".", "text": " ",
                            "out": "x.wav"}, timeout=60)
        assert worker.alive
    finally:
        worker.stop()
    assert not worker.alive


# ----------------------------------------------------------------- service
@pytest.fixture
def speech(tmp_path: Path, monkeypatch):
    """Voices, clips, uploads and the output folder, all in a scratch folder."""
    from uncloud_engine import library
    from uncloud_engine import speech as module
    from uncloud_engine.config import settings

    models = tmp_path / "models"
    for name in ("ve.pt", "s3gen.pt", "grapheme_mtl_merged_expanded_v1.json", "conds.pt"):
        touch(models / "Chatterbox" / name)
    # Real headers: the library reads them to decide what the folder is.
    for name in ("t3_mtl23ls_v3", "s3gen"):
        safetensors(models / "Chatterbox" / f"{name}.safetensors", {"w": [1]})
    monkeypatch.setattr(settings, "_data", {"models_dir": str(models),
                                            "output_dir": str(tmp_path / "out")})
    monkeypatch.setattr(settings, "_save", lambda: None)
    monkeypatch.setattr(module, "VOICES_DIR", tmp_path / "voices")
    monkeypatch.setattr(module, "CLIPS_INDEX", tmp_path / "clips.json")
    monkeypatch.setattr(module, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(module, "_kokoro_cache", lambda: None)
    library.invalidate_library_cache()
    yield module, models
    library.invalidate_library_cache()


def test_only_listed_models_can_be_spoken_with(speech, tmp_path: Path) -> None:
    module, models = speech
    [chatterbox] = [e for e in module.engines() if e["id"] == "chatterbox"]
    assert [m["name"] for m in chatterbox["models"]] == ["Chatterbox"]
    assert module.model_for(str(models / "Chatterbox"), "chatterbox")["converts"]
    # A paired phone must not be able to aim the worker at any folder of pickles.
    with pytest.raises(ValueError):
        module.model_for(str(tmp_path), "chatterbox")


def test_recordings_must_be_ones_uncloud_stored(speech, tmp_path: Path) -> None:
    module, _ = speech
    inside = wav(tmp_path / "uploads" / "rec.wav")
    assert module.recording(str(inside)) == str(inside.resolve())
    with pytest.raises(ValueError):
        module.recording(str(wav(tmp_path / "elsewhere" / "rec.wav")))


def test_a_saved_voice_keeps_its_recording_and_settings(speech, tmp_path: Path) -> None:
    module, models = speech
    kept = module.save_voice(name="Narrator", engine="chatterbox",
                             model_path=str(models / "Chatterbox"), language="fr",
                             controls={"exaggeration": 0.7},
                             recording_path=str(wav(tmp_path / "uploads" / "me.wav")))
    again = module.saved_voice(kept.slug)
    assert again.to_dict()["has_recording"]
    assert again.language == "fr" and again.controls == {"exaggeration": 0.7}
    # A second voice with the same name does not overwrite the first.
    assert module.save_voice(name="Narrator", engine="kokoro", preset="af_heart").slug != kept.slug
    assert module.delete_voice(kept.slug) and not (tmp_path / "voices" / kept.slug).exists()


def test_a_preset_engine_refuses_a_recording(speech, tmp_path: Path) -> None:
    module, _ = speech
    with pytest.raises(ValueError, match="cannot speak in a recorded voice"):
        module.save_voice(name="Nope", engine="kokoro",
                          recording_path=str(wav(tmp_path / "uploads" / "x.wav")))


def test_clips_are_kept_renamed_and_forgotten_when_their_file_goes(speech, tmp_path: Path) -> None:
    module, _ = speech
    first = wav(tmp_path / "out" / "voice" / "one.wav")
    module.add_clip(module.Clip(id="a", name="one", path=str(first), kind="speech", created=1))
    module.add_clip(module.Clip(id="b", name="two", path=str(wav(tmp_path / "out" / "two.wav")),
                                kind="reply", created=2))
    assert [c.id for c in module.clips()] == ["b", "a"]
    assert [c.id for c in module.clips("reply")] == ["b"]

    renamed = module.rename_clip("a", "Intro: take 2")
    assert Path(renamed.path).name == "Intro take 2.wav" and Path(renamed.path).is_file()

    Path(renamed.path).unlink()
    assert [c.id for c in module.clips()] == ["b"]
    module.delete_clip("b")
    assert module.clips() == []


def test_hq_narration_labels_every_line_through_core() -> None:
    assert chunks.speaker_script("Title\nBody") == "Speaker 1: Title\nSpeaker 1: Body"


# ------------------------------------------------------------------ routes
@pytest.fixture
def client(speech):
    from fastapi.testclient import TestClient

    from uncloud_engine import main

    http = TestClient(main.app)
    http.headers.update({"Authorization": f"Bearer {main.settings.token}"})
    yield speech[0], speech[1], http


def test_speaking_with_an_unlisted_model_is_a_400_with_the_reason(client, tmp_path: Path) -> None:
    module, _, http = client
    module_installed = module.installed
    try:
        module.installed = lambda engine: True
        response = http.post("/api/speech/speak", json={
            "text": "Hello", "engine": "chatterbox", "model_path": str(tmp_path)})
    finally:
        module.installed = module_installed
    assert response.status_code == 400
    assert "not a speech model" in response.json()["detail"]


def test_installing_an_engine_is_for_the_desktop_only(client) -> None:
    _, _, http = client
    response = http.post("/api/speech/engines/chatterbox/install",
                         headers={"Authorization": ""})
    assert response.status_code in (401, 403)


def test_a_reply_in_an_unknown_saved_voice_says_so(client) -> None:
    _, _, http = client
    response = http.post("/api/voice/speak", json={"text": "Hi", "saved_voice": "ghost"})
    assert response.status_code == 400 and "ghost" in response.json()["detail"]


def test_a_browser_recording_is_stored_as_wav(client, tmp_path: Path) -> None:
    # Decoded by PyAV through faster-whisper, which the source-test job does
    # not install; the packaged engine does.
    pytest.importorskip("faster_whisper")
    _, _, http = client
    source = wav(tmp_path / "phone.wav", seconds=1.0)
    response = http.post("/api/speech/recordings",
                         files={"file": ("phone.wav", source.read_bytes(), "audio/wav")})
    assert response.status_code == 200, response.text
    stored = Path(response.json()["path"])
    assert stored.suffix == ".wav" and stored.is_file()
    assert response.json()["seconds"] == pytest.approx(1.0, abs=0.1)


def test_espeak_data_is_kept_within_the_limit_it_reads() -> None:
    """espeak-ng holds its data path in a fixed buffer and ignores a longer
    one, then exits on the path compiled into the library. Found with an
    environment 182 characters deep, on the first word Kokoro's dictionary did
    not have."""
    runner = _runner_module()
    assert runner.ESPEAK_PATH_LIMIT <= 160


def _runner_module():
    import importlib.util

    path = (Path(__file__).resolve().parent.parent / "uncloud_engine" / "core"
            / "speech" / "runner.py")
    spec = importlib.util.spec_from_file_location("speech_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
