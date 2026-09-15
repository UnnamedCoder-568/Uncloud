"""One-shot VibeVoice narration using the full (non-streaming) 1.5B model.

Run by the .venv-vibevoice-hq interpreter, which carries the community fork
(vibevoice-community/VibeVoice) — Microsoft's own repo no longer ships the
non-streaming inference path, only the Realtime/streaming one.

The tradeoff versus the streaming model: this keeps the semantic tokenizer, so it
sounds fuller and less compressed, but it has no realtime path and is slower.

Voices here are raw audio references, not prefilled .pt caches.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

NATIVE_SR = 24000

#: The model stops at this multiple of its input length. The library default
#: of 2 is below what English narration needs (about 2.3 speech tokens per
#: text token), so a long read with no voice sample ended mid-sentence. The
#: context window still bounds it.
MAX_LENGTH_TIMES = 4

_SPEAKER = re.compile(r"^\s*Speaker\s+(\d+)\s*:", re.IGNORECASE)


def as_script(text: str) -> str:
    """Label every line with a speaker, which is the only form this model reads.

    Its processor silently drops any line that does not start "Speaker N:".
    Only the first line used to be labelled, so a script with a title or
    paragraph breaks narrated its first line and nothing else — about five
    seconds. A line without a label continues whoever spoke last.
    """
    speaker = "1"
    lines = []
    for line in text.splitlines():
        if not line.strip():
            continue
        match = _SPEAKER.match(line)
        if match:
            speaker = match.group(1)
            lines.append(line.strip())
        else:
            lines.append(f"Speaker {speaker}: {line.strip()}")
    return "\n".join(lines)


def main() -> int:
    cfg = json.loads(sys.argv[1])

    import numpy as np
    import soundfile as sf
    import torch
    from vibevoice.modular.modeling_vibevoice_inference import (
        VibeVoiceForConditionalGenerationInference as Model,
    )
    from vibevoice.processor.vibevoice_processor import VibeVoiceProcessor as Processor

    out_path = Path(cfg["out_path"])
    sample_rate = int(cfg.get("sample_rate", 44100))
    bit_depth = int(cfg.get("bit_depth", 24))
    audio_format = cfg.get("audio_format", "wav")
    cfg_scale = float(cfg.get("cfg_scale", 1.3))
    voice_path = cfg.get("voice_path")

    device = "mps" if torch.backends.mps.is_available() else (
        "cuda" if torch.cuda.is_available() else "cpu"
    )

    processor = Processor.from_pretrained(cfg["model_dir"])
    model = Model.from_pretrained(
        cfg["model_dir"], torch_dtype=torch.float32, attn_implementation="sdpa",
    ).to(device).eval()
    model.set_ddpm_inference_steps(num_steps=int(cfg.get("ddpm_steps", 20)))

    # This model is built for multi-speaker scripts; a single narrator is Speaker 1.
    text = as_script(cfg["text"])

    inputs = processor(
        text=[text],
        voice_samples=[[voice_path]] if voice_path else None,
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
            max_length_times=MAX_LENGTH_TIMES,
        )

    speech = getattr(outputs, "speech_outputs", None)
    if not speech or speech[0] is None:
        print("[hq-runner] model returned no audio", file=sys.stderr)
        return 1

    audio = speech[0]
    if hasattr(audio, "detach"):
        audio = audio.detach().to(torch.float32).cpu().numpy()
    audio = np.asarray(audio).squeeze()

    if sample_rate != NATIVE_SR:
        idx = np.linspace(0, len(audio) - 1, int(len(audio) * sample_rate / NATIVE_SR))
        audio = np.interp(idx, np.arange(len(audio)), audio)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if audio_format == "aiff":
        subtype = {16: "PCM_16", 24: "PCM_24", 32: "PCM_32"}[bit_depth]
    else:
        subtype = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}[bit_depth]
    sf.write(str(out_path), audio, sample_rate, subtype=subtype, format=audio_format.upper())

    print(f"DURATION::{len(audio) / sample_rate:.2f}")
    print(f"OUTPUT::{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
