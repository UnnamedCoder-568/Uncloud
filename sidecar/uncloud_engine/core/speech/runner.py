"""The speech worker: loads an engine once and keeps saying things with it.

BYTE-IDENTICAL IN BOTH REPOSITORIES.

Run by an engine's own interpreter, which has none of the product installed —
so this file imports its siblings by path and nothing else from Core.

Long-lived rather than one process per sentence, because loading Chatterbox
takes longer than saying most replies, and a conversation that waits ten
seconds before every answer is not a conversation.

The protocol is one JSON object per line. Requests arrive on stdin; replies
leave on stdout, and nothing else may: every library here prints progress
bars and warnings, so stdout is handed to stderr before any of them load.

    {"id": "1", "op": "speak", "engine": "kokoro", "folder": "...", "text": "...",
     "voice": "af_heart", "out": "/path.wav"}
    -> {"id": "1", "progress": [1, 3]}
    -> {"id": "1", "ok": true, "path": "/path.wav", "duration": 12.4}

Watermarks an engine applies (Chatterbox marks its output as synthetic) are
left exactly as the engine applies them.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import chunks  # noqa: E402 - a sibling, by path
import engines as catalogue  # noqa: E402

_PROTOCOL = sys.stdout
sys.stdout = sys.stderr
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
# The worker reads weights from folders the product chose. Nothing here should
# reach for the network behind the user's back.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

#: A pause between pieces of a long script, in seconds.
GAP = 0.2

_loaded: dict = {}


def send(message: dict) -> None:
    _PROTOCOL.write(json.dumps(message) + "\n")
    _PROTOCOL.flush()


def _device(torch, engine: str) -> str:
    if torch.cuda.is_available():
        return "cuda"
    # Kokoro is small enough that the CPU is as fast as the GPU round trip.
    if engine != "kokoro" and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


# ------------------------------------------------------------------ loading
def _load_kokoro(folder: Path, device: str) -> dict:
    from kokoro import KModel

    weights = next(folder.glob("kokoro*.pth"))
    model = KModel(repo_id="hexgrad/Kokoro-82M", config=str(folder / "config.json"),
                   model=str(weights)).to(device).eval()
    return {"model": model, "pipelines": {}, "rate": 24000}


def _load_bark(folder: Path, device: str) -> dict:
    import torch
    from transformers import AutoProcessor, BarkModel

    processor = AutoProcessor.from_pretrained(str(folder))
    # The preset table names the Hub repository it came from; pointed at the
    # folder instead, so a preset loads from disk rather than being fetched.
    if getattr(processor, "speaker_embeddings", None):
        processor.speaker_embeddings["repo_or_path"] = str(folder)
    model = BarkModel.from_pretrained(str(folder), dtype=torch.float32).to(device).eval()
    return {"model": model, "processor": processor,
            "rate": int(model.generation_config.sample_rate)}


def _load_chatterbox(folder: Path, variant: str, device: str) -> dict:
    if variant == "english":
        from chatterbox.tts import ChatterboxTTS

        model = ChatterboxTTS.from_local(folder, device)
    elif variant == "multilingual-v2":
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        model = ChatterboxMultilingualTTS.from_local(folder, device)
    elif variant == "multilingual-v3":
        model = _chatterbox_v3(folder, device)
    else:
        raise ValueError(f"No Chatterbox weights called {variant!r} in this folder")
    return {"model": model, "builtin": model.conds, "reference": None,
            "rate": int(model.sr)}


def _chatterbox_v3(folder: Path, device: str):
    """Multilingual V3, which the released package cannot load by name yet.

    Upstream loads V3 with exactly the V2 procedure and a different T3 file,
    and nothing else; this is that procedure, using the released package's own
    classes.
    """
    import torch
    from chatterbox import mtl_tts as mtl

    location = torch.device("cpu") if device in ("cpu", "mps") else None
    ve = mtl.VoiceEncoder()
    ve.load_state_dict(torch.load(folder / "ve.pt", map_location=location,
                                  weights_only=True))
    ve.to(device).eval()
    t3 = mtl.T3(mtl.T3Config.multilingual())
    state = mtl.load_safetensors(folder / "t3_mtl23ls_v3.safetensors")
    if "model" in state:
        state = state["model"][0]
    t3.load_state_dict(state)
    t3.to(device).eval()
    s3gen = mtl.S3Gen()
    s3gen.load_state_dict(torch.load(folder / "s3gen.pt", map_location=location,
                                     weights_only=True))
    s3gen.to(device).eval()
    tokenizer = mtl.MTLTokenizer(str(folder / "grapheme_mtl_merged_expanded_v1.json"))
    conds = None
    if (folder / "conds.pt").exists():
        conds = mtl.Conditionals.load(folder / "conds.pt", map_location=location).to(device)
    return mtl.ChatterboxMultilingualTTS(t3, s3gen, ve, tokenizer, device, conds=conds)


def _load_converter(folder: Path, device: str) -> dict:
    from chatterbox.vc import ChatterboxVC

    model = ChatterboxVC.from_local(folder, device)
    return {"model": model, "builtin": model.ref_dict, "rate": int(model.sr)}


def _model(engine: str, folder: Path, variant: str, device: str) -> dict:
    """One model at a time. Switching releases the previous one first, because
    two speech models side by side is how a laptop runs out of memory."""
    key = (engine, str(folder), variant, device)
    if _loaded.get("key") == key:
        return _loaded["state"]
    _loaded.clear()
    import gc

    gc.collect()
    if engine == "kokoro":
        state = _load_kokoro(folder, device)
    elif engine == "bark":
        state = _load_bark(folder, device)
    elif engine == "chatterbox":
        state = _load_chatterbox(folder, variant, device)
    elif engine == "chatterbox-convert":
        state = _load_converter(folder, device)
    else:
        raise ValueError(f"No speech engine called {engine!r}")
    _loaded.update(key=key, state=state)
    return state


# ----------------------------------------------------------------- speaking
def _say_kokoro(state: dict, folder: Path, piece: str, request: dict):
    import numpy as np
    from kokoro import KPipeline

    voice = request.get("voice") or "af_heart"
    lang = voice[:1]
    if lang not in catalogue.KOKORO_LANGUAGES:
        raise ValueError(f"Kokoro has no language for the voice {voice!r}")
    pipeline = state["pipelines"].get(lang)
    if pipeline is None:
        pipeline = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M",
                             model=state["model"])
        state["pipelines"][lang] = pipeline
    path = folder / "voices" / f"{voice}.pt"
    if not path.is_file():
        raise ValueError(f"The voice {voice!r} is not in this Kokoro folder")
    speed = float(request.get("controls", {}).get("speed", 1.0))
    parts = [np.asarray(audio, dtype=np.float32)
             for _g, _p, audio in pipeline(piece, voice=str(path), speed=speed)
             if audio is not None]
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


def _say_bark(state: dict, piece: str, request: dict, device: str):
    import numpy as np

    controls = request.get("controls", {})
    temperature = float(controls.get("temperature", 0.7))
    inputs = state["processor"](piece, voice_preset=request.get("voice") or None)
    inputs = {k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()}
    audio = state["model"].generate(**inputs, do_sample=True,
                                    semantic_temperature=temperature,
                                    coarse_temperature=temperature)
    return np.asarray(audio.detach().cpu().float().numpy()).squeeze()


def _say_chatterbox(state: dict, piece: str, request: dict):
    import numpy as np

    model = state["model"]
    controls = request.get("controls", {})
    reference = request.get("reference") or None
    if reference:
        if state["reference"] != reference:
            model.prepare_conditionals(reference, exaggeration=float(
                controls.get("exaggeration", 0.5)))
            state["reference"] = reference
    else:
        # A voice cloned for the last request must not leak into this one.
        model.conds = state["builtin"]
        state["reference"] = None
        if model.conds is None:
            raise ValueError("These Chatterbox weights have no built-in voice; "
                             "choose a recording to speak in.")
    kwargs = {
        "exaggeration": float(controls.get("exaggeration", 0.5)),
        "cfg_weight": float(controls.get("cfg_weight", 0.5)),
        "temperature": float(controls.get("temperature", 0.8)),
    }
    if _loaded["key"][2].startswith("multilingual"):
        kwargs["language_id"] = request.get("language") or "en"
    wav = model.generate(piece, **kwargs)
    return np.asarray(wav.detach().cpu().float().numpy()).squeeze()


def _write(audio, native_rate: int, request: dict) -> float:
    import numpy as np
    import soundfile as sf

    rate = int(request.get("sample_rate") or native_rate)
    if rate != native_rate and len(audio):
        index = np.linspace(0, len(audio) - 1, int(len(audio) * rate / native_rate))
        audio = np.interp(index, np.arange(len(audio)), audio).astype(np.float32)
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak > 0.99:
        audio = audio * (0.99 / peak)
    fmt = (request.get("format") or "wav").lower()
    depth = int(request.get("bit_depth") or 16)
    subtypes = {16: "PCM_16", 24: "PCM_24", 32: "PCM_32" if fmt == "aiff" else "FLOAT"}
    out = Path(request["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), audio, rate, subtype=subtypes.get(depth, "PCM_16"),
             format=fmt.upper())
    return len(audio) / rate if rate else 0.0


def speak(request: dict) -> dict:
    engine = request["engine"]
    spec = catalogue.ENGINES.get(engine)
    if spec is None:
        raise ValueError(f"No speech engine called {engine!r}")
    # Checked before anything heavy is imported: a request that cannot work
    # should say so in milliseconds, not after torch has loaded.
    pieces = chunks.chunks(request.get("text", ""), spec.chunk_chars)
    if not pieces:
        raise ValueError("There is nothing to say")
    folder = Path(request["folder"])
    variant = request.get("variant") or ""
    if engine == "chatterbox" and not variant:
        found = catalogue.chatterbox_variants(folder)
        if not found:
            raise ValueError("No Chatterbox weights that speak text in this folder")
        variant = found[0].id

    import numpy as np
    import torch

    device = request.get("device") or _device(torch, engine)
    state = _model(engine, folder, variant, device)
    rate = state["rate"]
    silence = np.zeros(int(GAP * rate), dtype=np.float32)
    audio_parts = []
    for i, piece in enumerate(pieces):
        if engine == "kokoro":
            part = _say_kokoro(state, folder, piece, request)
        elif engine == "bark":
            part = _say_bark(state, piece, request, device)
        else:
            part = _say_chatterbox(state, piece, request)
        if audio_parts:
            audio_parts.append(silence)
        audio_parts.append(np.asarray(part, dtype=np.float32))
        send({"id": request.get("id"), "progress": [i + 1, len(pieces)]})
    audio = np.concatenate(audio_parts) if audio_parts else np.zeros(0, np.float32)
    if not len(audio):
        raise RuntimeError("The engine produced no audio for this text")
    duration = _write(audio, rate, request)
    return {"path": request["out"], "duration": round(duration, 2), "pieces": len(pieces),
            "device": device}


def convert(request: dict) -> dict:
    """Voice to voice: say what a recording says, in another voice."""
    import numpy as np
    import torch

    folder = Path(request["folder"])
    device = request.get("device") or _device(torch, "chatterbox")
    state = _model("chatterbox-convert", folder, "convert", device)
    model = state["model"]
    reference = request.get("reference") or None
    if reference:
        model.set_target_voice(reference)
    else:
        model.ref_dict = state["builtin"]
        if model.ref_dict is None:
            raise ValueError("Choose a recording of the voice to convert into")
    wav = model.generate(request["source"])
    audio = np.asarray(wav.detach().cpu().float().numpy()).squeeze()
    duration = _write(audio, state["rate"], request)
    return {"path": request["out"], "duration": round(duration, 2), "device": device}


def handle(request: dict) -> dict:
    op = request.get("op")
    if op == "ping":
        import importlib.util

        return {"python": sys.version.split()[0], "engines": [
            e.id for e in catalogue.ENGINES.values()
            if all(importlib.util.find_spec(m) for m in e.modules)]}
    if op == "unload":
        _loaded.clear()
        return {}
    if op not in ("speak", "convert"):
        raise ValueError(f"Unknown request {op!r}")
    try:
        return speak(request) if op == "speak" else convert(request)
    except (RuntimeError, NotImplementedError) as exc:
        # Some operations these models use have no Apple GPU kernel. Retried
        # once on the CPU: slower, and it finishes.
        import torch

        engine = request.get("engine", "chatterbox") if op == "speak" else "chatterbox"
        if request.get("device") or _device(torch, engine) != "mps":
            raise
        traceback.print_exc()
        print(f"[speech] retrying on the CPU after: {exc}", file=sys.stderr)
        _loaded.clear()
        retry = dict(request, device="cpu")
        return speak(retry) if op == "speak" else convert(retry)


def main() -> int:
    send({"ready": True})
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except ValueError:
            send({"error": "Unreadable request"})
            continue
        try:
            result = handle(request)
            send({"id": request.get("id"), "ok": True, **result})
        except Exception as exc:  # noqa: BLE001 - reported, and the worker lives on
            traceback.print_exc()
            send({"id": request.get("id"), "error": f"{exc}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
