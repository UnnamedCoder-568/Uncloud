"""Models on disk: what they are, and the metadata they need.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

* `headers`  — GGUF and safetensors self-descriptions, read without loading.
* `identify` — task, family, pipeline and quantisation, each with its evidence.
* `metadata` — the missing configuration: looked up, or built, or explained.
* `hub`      — the one online lookup, JSON only, never past a gate.

What a model IS lives here. Whether an application can RUN it is that
application's decision, made with this as its input.
"""

from .identify import MANIFEST, Confidence, Identification, Layout, Task, identify
from .metadata import Step, apply, manifest_path, plan

__all__ = ["MANIFEST", "Confidence", "Identification", "Layout", "Step", "Task", "apply",
           "identify", "manifest_path", "plan"]
