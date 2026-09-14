"""Reading what a weights file says about itself, without loading it.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Both formats that matter put a self-description at the front of the file:
GGUF a key-value table, safetensors a JSON header naming every tensor and its
shape. Reading those is kilobytes, and it is the difference between knowing
what a file is and guessing from what somebody named it. Filenames lie — this
drive holds a text encoder called flux2-klein-4b-uncensored and an image model
whose name contains no hint of one.

Standard library only, and bounded everywhere a hostile or corrupt file could
ask for an unbounded read: a length field is a number somebody else wrote.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path

#: A safetensors header over this is not a header; it is a malformed file, or a
#: file that is not safetensors at all and happens to start with a large number.
SAFETENSORS_HEADER_LIMIT = 64 * 1024 * 1024

#: Keys read from a GGUF table before giving up. Keys, not values: a vocabulary
#: array is one key however many tokens it holds.
GGUF_KEY_LIMIT = 160

# GGUF value type ids -> fixed byte width. 8 is string, 9 is array.
_FIXED = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
_UNPACK = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?",
           10: "<Q", 11: "<q", 12: "<d"}
_STRING, _ARRAY = 8, 9


@dataclass
class GgufHeader:
    version: int
    tensor_count: int
    #: Scalar and string fields from the front of the table. Arrays are skipped:
    #: the ones that matter for identification are never arrays.
    fields: dict[str, object] = field(default_factory=dict)

    @property
    def architecture(self) -> str:
        return str(self.fields.get("general.architecture") or "").strip().lower()

    @property
    def name(self) -> str:
        return str(self.fields.get("general.name") or "").strip()


def read_gguf(path: Path) -> GgufHeader | None:
    """The front of a GGUF key-value table, or None if this is not a GGUF file."""
    try:
        with path.open("rb") as f:
            if f.read(4) != b"GGUF":
                return None
            version = struct.unpack("<I", f.read(4))[0]
            tensors = struct.unpack("<Q", f.read(8))[0]
            count = struct.unpack("<Q", f.read(8))[0]

            def text() -> str:
                n = struct.unpack("<Q", f.read(8))[0]
                if n > 1 << 20:
                    raise ValueError("implausible string length")
                return f.read(n).decode("utf-8", "replace")

            def skip(kind: int) -> None:
                if kind in _FIXED:
                    f.seek(_FIXED[kind], 1)
                elif kind == _STRING:
                    f.seek(struct.unpack("<Q", f.read(8))[0], 1)
                elif kind == _ARRAY:
                    element = struct.unpack("<I", f.read(4))[0]
                    length = struct.unpack("<Q", f.read(8))[0]
                    if element in _FIXED:
                        f.seek(_FIXED[element] * length, 1)
                    else:
                        for _ in range(length):
                            skip(element)
                else:
                    raise ValueError(f"unknown GGUF value type {kind}")

            header = GgufHeader(version=version, tensor_count=tensors)
            for _ in range(min(count, GGUF_KEY_LIMIT)):
                key = text()
                kind = struct.unpack("<I", f.read(4))[0]
                # Not stopping at the vocabulary: some writers put general.file_type
                # after it. Skipping a vocabulary is a seek per string, which
                # measured 34 ms on a 150k-token Qwen3 — cheap for the truth.
                if kind == _STRING:
                    header.fields[key] = text()
                elif kind in _UNPACK:
                    header.fields[key] = struct.unpack(_UNPACK[kind], f.read(_FIXED[kind]))[0]
                else:
                    skip(kind)
            return header
    except (OSError, ValueError, struct.error):
        return None


@dataclass
class SafetensorsHeader:
    #: The `__metadata__` block, where a trainer or converter left one.
    metadata: dict[str, str]
    #: Tensor name -> shape. Dtype and offsets are not needed to identify.
    shapes: dict[str, tuple[int, ...]]


def read_safetensors(path: Path) -> SafetensorsHeader | None:
    """Tensor names and shapes from a safetensors file, reading only the header."""
    try:
        with path.open("rb") as f:
            raw = f.read(8)
            if len(raw) != 8:
                return None
            length = struct.unpack("<Q", raw)[0]
            if length == 0 or length > SAFETENSORS_HEADER_LIMIT:
                return None
            body = f.read(length)
        parsed = json.loads(body)
    except (OSError, ValueError, struct.error):
        return None
    if not isinstance(parsed, dict):
        return None
    metadata = parsed.pop("__metadata__", None) or {}
    shapes: dict[str, tuple[int, ...]] = {}
    for name, info in parsed.items():
        if isinstance(info, dict) and isinstance(info.get("shape"), list):
            shapes[name] = tuple(int(d) for d in info["shape"])
    return SafetensorsHeader(
        metadata={str(k): str(v) for k, v in metadata.items()}, shapes=shapes)


def tensor_names(folder: Path) -> list[str]:
    """Every tensor name in a folder's weights: from the shard index if there is
    one (no shard opened), otherwise from each safetensors header."""
    index = folder / "model.safetensors.index.json"
    for candidate in (index, folder / "diffusion_pytorch_model.safetensors.index.json"):
        if candidate.is_file():
            try:
                return sorted(json.loads(candidate.read_text()).get("weight_map", {}))
            except (OSError, ValueError, AttributeError):
                break
    names: list[str] = []
    for weights in sorted(folder.glob("*.safetensors"))[:8]:
        header = read_safetensors(weights)
        if header:
            names.extend(header.shapes)
    return names


def read_json(path: Path) -> dict | None:
    """A JSON object from disk, or None. Model folders are full of these and a
    malformed one must never stop the rest being read."""
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def front_matter(readme: Path) -> dict[str, str]:
    """The YAML front matter of a model card, as flat strings.

    Not a YAML parser — just the `key: value` lines and simple lists that model
    cards actually use. Lists become comma-joined. Anything cleverer is ignored
    rather than half-understood.
    """
    try:
        lines = readme.read_text(errors="replace").splitlines()[:120]
    except OSError:
        return {}
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    current: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith((" ", "\t", "-")) and current:
            item = line.strip().lstrip("-").strip().strip("'\"")
            if item:
                out[current] = f"{out[current]}, {item}" if out.get(current) else item
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            current = key.strip()
            out[current] = value.strip().strip("'\"")
    return out
