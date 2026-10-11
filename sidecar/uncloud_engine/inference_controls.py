"""Cached native capabilities and strict, shared Chat/Chisel request controls.

No tokenizer/model imports, file reads, or inference calls on request assembly.
Capabilities are established at model load; unsupported overrides are errors.
"""

from __future__ import annotations

import contextlib
import importlib.metadata
import json
import math
import re
from pathlib import Path

CORE = {
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "repetition_penalty",
    "presence_penalty",
    "frequency_penalty",
    "seed",
    "stop",
    "max_tokens",
}
ADVANCED = {
    "typical_p",
    "xtc_probability",
    "xtc_threshold",
    "repetition_context_size",
    "presence_context_size",
    "frequency_context_size",
    "logprobs",
    "top_logprobs",
    "dry_multiplier",
    "dry_base",
    "dry_allowed_length",
    "dry_penalty_last_n",
    "mirostat",
    "mirostat_tau",
    "mirostat_eta",
    "grammar",
    "response_format",
}
INTEGERS = {
    "top_k",
    "seed",
    "max_tokens",
    "top_logprobs",
    "repetition_context_size",
    "presence_context_size",
    "frequency_context_size",
    "dry_allowed_length",
    "dry_penalty_last_n",
    "mirostat",
}
PROBABILITIES = {"top_p", "min_p", "typical_p", "xtc_probability", "xtc_threshold"}
NONNEGATIVE = {
    "temperature",
    "top_k",
    "repetition_penalty",
    "dry_multiplier",
    "dry_base",
    "mirostat_tau",
    "mirostat_eta",
    "repetition_context_size",
    "presence_context_size",
    "frequency_context_size",
    "dry_allowed_length",
}


def validate(values: dict) -> dict:
    if not isinstance(values, dict) or len(values) > 40:
        raise ValueError("Inference settings must be an object with supported fields.")
    for key, value in values.items():
        if key not in CORE | ADVANCED | {"reasoning", "system_prompt"}:
            raise ValueError(f"Unsupported inference setting: {key}")
        if key == "reasoning":
            if not isinstance(value, str) or value not in {
                "auto",
                "off",
                "low",
                "medium",
                "high",
                "max",
            }:
                raise ValueError("Unknown thinking level")
        elif key in {"system_prompt", "grammar"}:
            if not isinstance(value, str) or len(value) > 32000:
                raise ValueError(f"{key} must be text (at most 32,000 characters).")
        elif key == "response_format":
            if (
                not isinstance(value, dict)
                or value.get("type") not in {"text", "json_object", "json_schema"}
                or len(json.dumps(value)) > 32000
            ):
                raise ValueError("Invalid response format")
        elif key == "stop":
            stops = [value] if isinstance(value, str) else value
            if (
                not isinstance(stops, list)
                or len(stops) > 16
                or any(not isinstance(s, str) or not s or len(s) > 256 for s in stops)
            ):
                raise ValueError("Stop sequences must be up to 16 nonempty strings.")
        elif key == "logprobs":
            if not isinstance(value, bool):
                raise ValueError("Log probabilities must be on or off.")
        else:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"{key} must be a finite number.")
            if key in INTEGERS and not isinstance(value, int):
                raise ValueError(f"{key} must be a whole number.")
            if key in PROBABILITIES and not 0 <= value <= 1:
                raise ValueError(f"{key} must be between 0 and 1.")
            if key in NONNEGATIVE and value < 0:
                raise ValueError(f"{key} cannot be negative.")
            if key == "max_tokens" and value < 1:
                raise ValueError("Reply budget must be positive.")
            if key == "top_logprobs" and not -1 <= value <= 11:
                raise ValueError("Top log probabilities must be -1 through 11.")
            if key == "mirostat" and value not in {0, 1, 2}:
                raise ValueError("Mirostat must be 0, 1 or 2.")
    if values.get("grammar") and values.get("response_format"):
        raise ValueError("Choose a grammar or a response format, rather than both.")
    return dict(values)


def discover(model_path: str, engine: str, *, native: bool = False) -> dict:
    """One-time discovery. Template variables, never filename guesses, enable thinking."""
    path = Path(model_path)
    template = ""
    family = ""
    if path.is_dir():
        for file in (path / "tokenizer_config.json", path / "config.json"):
            try:
                data = json.loads(file.read_text())
                if file.name == "tokenizer_config.json":
                    raw = data.get("chat_template", "")
                    template = raw if isinstance(raw, str) else json.dumps(raw)
                else:
                    family = str(data.get("model_type", ""))
            except (OSError, ValueError, AttributeError):
                pass
        with contextlib.suppress(OSError):
            template = (path / "chat_template.jinja").read_text()
    elif path.is_file():
        from .core.models.headers import read_gguf

        header = read_gguf(path)
        if header:
            template = str(header.fields.get("tokenizer.chat_template", ""))
            family = str(header.fields.get("general.architecture", ""))
    fields = set(CORE)
    version = "unknown"
    if engine == "mlx":
        try:
            dist = importlib.metadata.distribution("mlx-lm")
            version = dist.version
            source = Path(dist.locate_file("mlx_lm/server.py")).read_text()
            consumed = set(re.findall(r'\bself\.body\.get\("([a-z_]+)"', source))
            fields &= consumed
            fields |= ADVANCED & consumed
            # Some core parameters use a multiline get; keep those only if named in source.
            fields |= {key for key in CORE if f'"{key}"' in source}
        except (importlib.metadata.PackageNotFoundError, OSError):
            fields = set()  # Not installed, no capability claims.
    elif engine == "gguf":
        # llama-cpp-python's API is deliberately narrower than native llama-server.
        if native:
            fields |= {"typical_p", "response_format", "grammar", "logprobs", "top_logprobs"}
        else:
            fields |= {"response_format"}
    else:
        fields = {"temperature", "top_p", "max_tokens", "stop"}
    toggle = engine in {"mlx", "gguf"} and bool(re.search(r"\benable_thinking\b", template))
    native_effort = engine in {"mlx", "gguf"} and bool(re.search(r"\breasoning_effort\b", template))
    levels = ["auto", "off", "high"] if toggle else ["auto"]
    if native_effort:
        levels = ["auto"] + [
            level
            for level in ("low", "medium", "high", "max")
            if re.search(rf"['\"]{level}['\"]", template)
        ]
    return {
        "fields": sorted(fields),
        "reasoning": {
            "mechanism": "template_effort"
            if native_effort
            else ("template_toggle" if toggle else "native_fixed_or_unknown"),
            "levels": levels,
            "explanation": (
                "This native template declares graded reasoning effort."
                if native_effort
                else "This template supports thinking on/off; graded budgets are not verified."
                if toggle
                else "Native behavior is preserved. No adjustable thinking mechanism verified."
            ),
        },
        "family": family,
        "backend_version": version,
        "template_available": bool(template),
        "template": template,
        "optimizations": "Native backend configuration; no speculative flags enabled.",
    }


def apply(active, payload: dict, overrides: dict | None = None) -> dict:
    values = validate(overrides or {})
    capabilities = getattr(active, "inference_profile", {}).get(
        "capabilities", {"fields": sorted(CORE), "reasoning": {"levels": ["auto"]}}
    )
    supported = set(capabilities["fields"])
    level = values.pop("reasoning", "auto")
    values.pop("system_prompt", None)  # Assembled by the caller, never a backend sampler.
    if level not in capabilities["reasoning"]["levels"]:
        raise ValueError("This model/backend does not support that thinking level.")
    if level != "auto":
        payload["chat_template_kwargs"] = (
            {"reasoning_effort": level}
            if capabilities["reasoning"].get("mechanism") == "template_effort"
            else {"enable_thinking": level != "off"}
        )
    unsupported = set(values) - supported
    if unsupported:
        raise ValueError("Unsupported by this backend: " + ", ".join(sorted(unsupported)))
    if "max_tokens" in values and values["max_tokens"] >= getattr(
        active, "context_limit", float("inf")
    ):
        raise ValueError("Reply budget must leave room for input in the effective context window.")
    if active.engine == "gguf" and "repetition_penalty" in values:
        values["repeat_penalty"] = values.pop("repetition_penalty")
    payload.update(values)
    return payload
