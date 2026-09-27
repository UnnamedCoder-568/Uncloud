"""Read inference recommendations once at model load, never on a chat turn.

Missing values are deliberately omitted: the native backend owns its defaults.
An optional uncloud-inference.json beside the weights supplies explicit local
overrides; request overrides always win. No filename-based sampling guesses.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .core import ModelProfile, reasoning_support
from .core.models.headers import read_gguf

SAMPLING_FIELDS = {
    "temperature", "top_p", "top_k", "min_p", "typical_p",
    "repetition_penalty", "presence_penalty", "frequency_penalty", "seed",
}


def clean(values: dict) -> dict:
    result = {}
    for key in SAMPLING_FIELDS:
        value = values.get(key)
        if not isinstance(value, (float, int)) or isinstance(value, bool):
            continue
        if not math.isfinite(value):
            continue
        if key in {"top_p", "min_p", "typical_p"} and not 0 <= value <= 1:
            continue
        if key in {"temperature", "top_k", "repetition_penalty"} and value < 0:
            continue
        result[key] = int(value) if key in {"top_k", "seed"} else value
    return result


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def load(model_path: str, engine: str) -> tuple[ModelProfile, dict]:
    path = Path(model_path)
    defaults: dict = {}
    sources: dict = {}
    config = {}
    output_limit = None
    if path.is_dir():
        config = _json(path / "config.json")
        generation = _json(path / "generation_config.json")
        output_limit = generation.get("max_new_tokens")
        defaults.update(clean(generation))
        if generation.get("do_sample") is False:
            defaults["temperature"] = 0
        sources.update(dict.fromkeys(defaults, "generation_config.json"))
        custom_path = path / "uncloud-inference.json"
    else:
        header = read_gguf(path) if path.is_file() else None
        if header:
            for key in SAMPLING_FIELDS:
                metadata_key = "repeat_penalty" if key == "repetition_penalty" else key
                values = clean({key: header.fields.get(f"general.sampling.{metadata_key}")})
                defaults.update(values)
                sources.update(dict.fromkeys(values, "GGUF sampling metadata"))
        custom_path = path.with_suffix(".inference.json")
    custom_data = _json(custom_path)
    output_limit = custom_data.get("max_new_tokens", output_limit)
    if not isinstance(output_limit, int) or isinstance(output_limit, bool) or output_limit <= 0:
        output_limit = None
    custom = clean(custom_data)
    defaults.update(custom)
    sources.update(dict.fromkeys(custom, custom_path.name))
    family = str(config.get("model_type", ""))
    profile = ModelProfile(id=path.name, name=path.name, family=family, runtime=engine,
                           reasoning=reasoning_support(path.name, family))
    return profile, {"parameters": defaults, "sources": sources,
                     "max_output_tokens": output_limit,
                     "fallback": "Native backend defaults for unspecified parameters",
                     "template": "Native model chat template"}


def for_backend(defaults: dict, overrides: dict, engine: str) -> dict:
    values = {**defaults, **clean(overrides)}
    if engine == "gguf" and "repetition_penalty" in values:
        values["repeat_penalty"] = values.pop("repetition_penalty")
    if engine in {"mlx", "mlx-vlm"}:
        values.pop("typical_p", None)  # Not implemented by these server APIs.
    return values
