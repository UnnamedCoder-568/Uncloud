"""Resolve model-owned generation settings, then the user's saved overrides."""

from __future__ import annotations

import ast
import importlib.util
import json
from functools import lru_cache
from pathlib import Path

from .config import settings


def validated(values: dict) -> dict:
    if not isinstance(values, dict):
        return {}
    out = {}
    for key, low, high in [
        ("steps", 1, 200),
        ("guidance", 0, 30),
        ("width", 256, 4096),
        ("height", 256, 4096),
    ]:
        value = values.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high:
            out[key] = float(value) if key == "guidance" else int(value)
    return out


@lru_cache(maxsize=32)
def runtime_defaults(cli: str, base: str) -> dict:
    """Read installed runtime declarations without importing MLX or loading weights."""
    from .mflux_runtime import _VARIANTS

    variant = _VARIANTS.get(cli)
    spec = importlib.util.find_spec("mflux")
    if not variant or not spec or not spec.origin:
        return {}
    root = Path(spec.origin).parent
    module, class_name, factory = variant
    out = {}
    folder = root.joinpath(*module.split(".")[1:])
    if folder.is_dir():
        for source in folder.rglob("*.py"):
            try:
                tree = ast.parse(source.read_text())
                for cls in tree.body:
                    if not isinstance(cls, ast.ClassDef) or cls.name != class_name:
                        continue
                    for method in cls.body:
                        if (
                            not isinstance(method, ast.FunctionDef)
                            or method.name != "generate_image"
                        ):
                            continue
                        args = method.args
                        pairs = list(
                            zip(
                                (args.posonlyargs + args.args)[-len(args.defaults) :],
                                args.defaults,
                                strict=False,
                            )
                        ) + list(zip(args.kwonlyargs, args.kw_defaults, strict=True))
                        for arg, value in pairs:
                            key = {"num_inference_steps": "steps", "guidance": "guidance"}.get(
                                arg.arg
                            )
                            if key and isinstance(value, ast.Constant):
                                out[key] = value.value
            except (OSError, SyntaxError):
                continue
    try:
        tree = ast.parse((root / "cli/defaults/defaults.py").read_text())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "MODEL_INFERENCE_STEPS" for t in node.targets
            ):
                table = ast.literal_eval(node.value)
                steps = table.get((base or factory).replace("_", "-"))
                if steps is not None:
                    out["steps"] = steps
    except (OSError, ValueError, SyntaxError):
        pass
    return validated(out)


@lru_cache(maxsize=32)
def pipeline_defaults(class_name: str) -> dict:
    spec = importlib.util.find_spec("diffusers")
    if not class_name or not spec or not spec.origin:
        return {}
    root = Path(spec.origin).parent / "pipelines"
    for source in root.rglob("pipeline_*.py"):
        try:
            content = source.read_text()
            if f"class {class_name}(" not in content:
                continue
            for cls in ast.parse(content).body:
                if not isinstance(cls, ast.ClassDef) or cls.name != class_name:
                    continue
                for method in cls.body:
                    if not isinstance(method, ast.FunctionDef) or method.name != "__call__":
                        continue
                    args = method.args
                    pairs = zip(
                        (args.posonlyargs + args.args)[-len(args.defaults) :],
                        args.defaults,
                        strict=False,
                    )
                    out = {}
                    for arg, value in pairs:
                        key = {"num_inference_steps": "steps", "guidance_scale": "guidance"}.get(
                            arg.arg
                        )
                        if key and isinstance(value, ast.Constant):
                            out[key] = value.value
                    return validated(out)
        except (OSError, SyntaxError):
            continue
    return {}


def resolve(model) -> tuple[dict, str]:
    values = {"steps": 25, "guidance": 3.5, "width": 1024, "height": 768}
    source = "General starting settings — no model recommendation found"
    runtime = runtime_defaults(model.mflux_cli or "", model.mflux_base or "")
    try:
        index = json.loads((Path(model.path) / "model_index.json").read_text())
        if isinstance(index, dict):
            runtime = {**runtime, **pipeline_defaults(index.get("_class_name", ""))}
    except (OSError, ValueError, TypeError):
        pass
    if runtime:
        values.update(runtime)
        source = "Installed runtime recommendations"
    if model.defaults:
        values.update(validated(model.defaults))
        source = "Model recommendations"
    folder = Path(model.path)
    if folder.is_file():
        folder = folder.parent
    for name in ["generation_config.json", "uncloud-model.json", "uncloud-mlx.json"]:
        try:
            data = json.loads((folder / name).read_text())
            if not isinstance(data, dict):
                continue
            data = data.get("defaults", data)
            if not isinstance(data, dict):
                continue
            data = {
                **data,
                **({"steps": data["num_inference_steps"]} if "num_inference_steps" in data else {}),
                **({"guidance": data["guidance_scale"]} if "guidance_scale" in data else {}),
            }
            found = validated(data)
            if found:
                values.update(found)
                source = "Model configuration"
        except (OSError, ValueError, TypeError):
            continue
    custom = settings._data.get("image_defaults", {}).get(model.path, {})
    if custom:
        values.update(validated(custom))
        source = "Your saved defaults for this model"
    return values, source
