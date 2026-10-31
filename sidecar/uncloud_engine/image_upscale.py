"""Optional, pixel-only 2x enlargement. Generation models and prompts are untouched.

Uses the upstream Real-ESRGAN x2plus weights (BSD-3-Clause). Architecture:
https://github.com/XPixelGroup/BasicSR/blob/master/basicsr/archs/rrdbnet_arch.py
Attribution and licenses: third_party/README.md. No face-restoration model.
"""

from __future__ import annotations

import gc
import hashlib
import math
import os
import uuid
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageOps

from .cancellation import Cancelled

MODEL_NAME = "RealESRGAN_x2plus.pth"
MODEL_URL = (
    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/" + MODEL_NAME
)
MODEL_BYTES = 67_061_725
MODEL_SHA256 = "49fafd45f8fd7aa8d31ab2a22d14d91b536c34494a5cfe31eb5d89c2fa266abb"
MAX_OUTPUT_PIXELS = 4096 * 4096
FORMATS = {"PNG", "JPEG", "WEBP"}


def model_path() -> Path:
    from .config import settings

    return settings.models_dir / "upscalers" / MODEL_NAME


def _valid_model(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size != MODEL_BYTES:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == MODEL_SHA256


def model_info() -> dict:
    return {"name": "Real-ESRGAN 2×", "ready": _valid_model(model_path()),
            "size_bytes": MODEL_BYTES, "scale": 2, "source": MODEL_URL}


def validate_source(source: str | Path, root: Path) -> Path:
    path = Path(source).resolve(strict=True)
    if root.resolve() not in path.parents or not path.is_file():
        raise ValueError("Choose an image from Outputs to enhance")
    with Image.open(path) as im:
        if im.format not in FORMATS or getattr(im, "is_animated", False):
            raise ValueError("Enhancement supports still PNG, JPEG and WebP images")
        if im.mode not in {"RGB", "RGBA", "L", "LA", "P", "CMYK"}:
            raise ValueError("Enhancement currently supports 8-bit images")
        if im.width * im.height * 4 > MAX_OUTPUT_PIXELS:
            raise ValueError("The enhanced image must fit within 16 megapixels")
    return path


def ensure_model(*, download: bool, check: Callable[[], None],
                 progress: Callable[[str], None]) -> Path:
    path = model_path()
    check()
    if _valid_model(path):
        return path
    if not download:
        raise ValueError("Download the 64 MB enhancement model first")
    import httpx

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{MODEL_NAME}.{uuid.uuid4().hex}.part")
    try:
        digest, received = hashlib.sha256(), 0
        with httpx.stream("GET", MODEL_URL, follow_redirects=True, timeout=30) as response:
            response.raise_for_status()
            with temporary.open("xb") as stream:
                for chunk in response.iter_bytes(1024 * 256):
                    check()
                    received += len(chunk)
                    if received > MODEL_BYTES:
                        raise ValueError("Enhancement model download has an unexpected size")
                    stream.write(chunk)
                    digest.update(chunk)
                    progress(f"Downloading enhancement model · {received / 1024**2:.1f} / 64 MB")
        if received != MODEL_BYTES or digest.hexdigest() != MODEL_SHA256:
            raise ValueError("Enhancement model failed its integrity check; please retry")
        check()
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


class _Network:
    """RRDBNet x2, evaluated with the released weights and no extra modules."""

    def __init__(self, path: Path):
        import torch

        self.torch = torch
        self.device = ("cuda" if torch.cuda.is_available() else
                       "mps" if torch.backends.mps.is_available() else "cpu")
        # The fixed digest is checked before loading. Never load arbitrary pickle files.
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        state = checkpoint.get("params_ema", checkpoint.get("params", {}))
        if len(state) != 702:
            raise ValueError("Unexpected enhancement model architecture")
        self.weights = {}
        try:
            for key, value in state.items():
                self.weights[key] = value.to(device=self.device, dtype=torch.float32)
        except Exception:
            self.close()
            raise

    def conv(self, x, key):
        from torch.nn import functional as f

        return f.conv2d(x, self.weights[key + ".weight"],
                        self.weights[key + ".bias"], padding=1)

    def dense(self, x, prefix):
        from torch.nn import functional as f

        features = [x]
        for n in range(1, 6):
            out = self.conv(self.torch.cat(features, dim=1), f"{prefix}.conv{n}")
            if n < 5:
                features.append(f.leaky_relu(out, negative_slope=0.2))
        return x + 0.2 * out

    def __call__(self, x):
        from torch.nn import functional as f

        first = self.conv(f.pixel_unshuffle(x, 2), "conv_first")
        h = first
        for block in range(23):
            residual = h
            for dense in range(1, 4):
                h = self.dense(h, f"body.{block}.rdb{dense}")
            h = residual + 0.2 * h
        h = first + self.conv(h, "conv_body")
        for key in ["conv_up1", "conv_up2"]:
            h = f.leaky_relu(self.conv(f.interpolate(h, scale_factor=2, mode="nearest"),
                                       key), negative_slope=0.2)
        return self.conv(f.leaky_relu(self.conv(h, "conv_hr"), negative_slope=0.2),
                         "conv_last")

    def close(self):
        self.weights.clear()
        gc.collect()
        if self.device == "mps":
            self.torch.mps.empty_cache()
        elif self.device == "cuda":
            self.torch.cuda.empty_cache()


def _render(network, source: Path, dest: Path, *, check: Callable[[], None],
            progress: Callable[[int, int], None], tile: int = 192, pad: int = 64) -> None:
    import numpy as np

    torch = network.torch
    with Image.open(source) as opened:
        im = ImageOps.exif_transpose(opened)
        alpha = im.convert("RGBA").getchannel("A") if (
            "A" in im.getbands() or "transparency" in im.info) else None
        icc = im.info.get("icc_profile")
        a = np.asarray(im.convert("RGB"))
    h, w = a.shape[:2]
    # x2 uses pixel-unshuffle, which requires even dimensions and tile origins.
    a = np.pad(a, ((0, h % 2), (0, w % 2), (0, 0)), mode="edge")
    ph, pw = a.shape[:2]
    result = np.empty((ph * 2, pw * 2, 3), dtype=np.uint8)
    total, index = math.ceil(ph / tile) * math.ceil(pw / tile), 0
    with torch.inference_mode():
        for y in range(0, ph, tile):
            for x in range(0, pw, tile):
                check()
                y2, x2 = min(y + tile, ph), min(x + tile, pw)
                top, left = max(0, y - pad), max(0, x - pad)
                bottom, right = min(ph, y2 + pad), min(pw, x2 + pad)
                patch = (torch.from_numpy(a[top:bottom, left:right].copy())
                         .permute(2, 0, 1).unsqueeze(0).to(
                             device=network.device, dtype=torch.float32) / 255)
                output = network(patch)[0, :, (y-top)*2:(y2-top)*2, (x-left)*2:(x2-left)*2]
                pixels = (output.clamp(0, 1).permute(1, 2, 0).mul(255).round()
                          .to(dtype=torch.uint8).cpu().numpy())
                result[y*2:y2*2, x*2:x2*2] = pixels
                del output, patch, pixels
                index += 1
                progress(index, total)
    check()
    enhanced = Image.fromarray(result[:h*2, :w*2])
    if alpha is not None:
        enhanced.putalpha(alpha.resize(enhanced.size, Image.Resampling.LANCZOS))
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.part")
    try:
        enhanced.save(temporary, format="PNG", icc_profile=icc)
        check()
        os.replace(temporary, dest)
    finally:
        temporary.unlink(missing_ok=True)


def enhance(source: Path, dest: Path, *, download: bool,
            cancelled: Callable[[], bool], phase: Callable[[str], None],
            progress: Callable[[int, int], None]) -> dict:
    if source.resolve() == dest.resolve() or dest.exists():
        raise ValueError("Enhancement must save a new image")

    def check():
        if cancelled():
            raise Cancelled("Enhancement stopped")

    path = ensure_model(download=download, check=check, progress=phase)
    check()
    phase("Loading enhancement model")
    network = _Network(path)
    try:
        phase(f"Enhancing 2× · {network.device.upper()}")
        _render(network, source, dest, check=check, progress=progress)
        return {"device": network.device, "scale": 2}
    finally:
        network.close()
