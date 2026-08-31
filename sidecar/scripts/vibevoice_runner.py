"""One-shot VibeVoice narration, run by the isolated .venv-vibevoice interpreter.

VibeVoice pins huggingface-hub<1.0, which the main engine can't satisfy, so it lives in
its own environment. Config arrives as JSON on argv (narration scripts are long and full
of punctuation that would be miserable to quote); the output path is printed at the end.

Modelled on microsoft/VibeVoice demo/realtime_model_inference_from_file.py — notably a
"voice" here is a pre-computed .pt prefilled KV cache, not a raw audio file.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

NATIVE_SR = 24000  # the model's own output rate


def main() -> int:
    cfg = json.loads(sys.argv[1])

    import numpy as np
    import soundfile as sf
    import torch
    from transformers.cache_utils import DynamicCache
    from transformers.modeling_outputs import BaseModelOutputWithPast
    from vibevoice.modular.modeling_vibevoice_streaming_inference import (
        VibeVoiceStreamingForConditionalGenerationInference as Model,
    )
    from vibevoice.processor.vibevoice_streaming_processor import (
        VibeVoiceStreamingProcessor as Processor,
    )

    model_dir = cfg["model_dir"]
    text = cfg["text"]
    out_path = Path(cfg["out_path"])
    sample_rate = int(cfg.get("sample_rate", 44100))
    bit_depth = int(cfg.get("bit_depth", 24))
    cfg_scale = float(cfg.get("cfg_scale", 1.3))
    voice_path = cfg.get("voice_path")
    audio_format = cfg.get("audio_format", "wav")

    device = "mps" if torch.backends.mps.is_available() else (
        "cuda" if torch.cuda.is_available() else "cpu"
    )

    processor = Processor.from_pretrained(model_dir)
    model = Model.from_pretrained(
        model_dir, torch_dtype=torch.float32, attn_implementation="sdpa",
    ).to(device).eval()
    model.set_ddpm_inference_steps(num_steps=int(cfg.get("ddpm_steps", 5)))

    # A voice is a prefilled KV cache saved as .pt, produced from a reference
    # recording. Without one the model has no speaker to condition on.
    prefilled = None
    if voice_path and Path(voice_path).exists():
        # These caches contain BaseModelOutputWithPast objects, which the safe
        # unpickler refuses (it can only SETITEMS on plain dicts). Try the safe path
        # first and only fall back to a full unpickle — which permits arbitrary code
        # execution — so the risk is scoped to voice files the user has installed.
        try:
            with torch.serialization.safe_globals([BaseModelOutputWithPast, DynamicCache]):
                prefilled = torch.load(voice_path, map_location=device, weights_only=True)
        except Exception:  # noqa: BLE001
            prefilled = torch.load(voice_path, map_location=device, weights_only=False)

    inputs = processor.process_input_with_cached_prompt(
        text=text,
        cached_prompt=prefilled,
        padding=True,
        return_tensors="pt",
        return_attention_mask=True,
    )
    for k, v in inputs.items():
        if torch.is_tensor(v):
            inputs[k] = v.to(device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=None,
            cfg_scale=cfg_scale,
            tokenizer=processor.tokenizer,
            generation_config={"do_sample": False},
            verbose=False,
            all_prefilled_outputs=copy.deepcopy(prefilled) if prefilled is not None else None,
        )

    speech = getattr(outputs, "speech_outputs", None)
    if not speech or speech[0] is None:
        print("[runner] model returned no audio", file=sys.stderr)
        return 1

    audio = speech[0]
    if hasattr(audio, "detach"):
        audio = audio.detach().to(torch.float32).cpu().numpy()
    audio = np.asarray(audio).squeeze()

    if sample_rate != NATIVE_SR:
        idx = np.linspace(0, len(audio) - 1, int(len(audio) * sample_rate / NATIVE_SR))
        audio = np.interp(idx, np.arange(len(audio)), audio)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # AIFF has no float subtype in libsndfile.
    if audio_format == "aiff":
        subtype = {16: "PCM_16", 24: "PCM_24", 32: "PCM_32"}[bit_depth]
    else:
        subtype = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}[bit_depth]
    sf.write(str(out_path), audio, sample_rate, subtype=subtype,
             format=audio_format.upper())

    print(f"DURATION::{len(audio) / sample_rate:.2f}")
    print(f"OUTPUT::{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
