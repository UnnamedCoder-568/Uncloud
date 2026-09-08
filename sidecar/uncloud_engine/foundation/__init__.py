"""The shared Uncloud foundation.

BYTE-IDENTICAL IN BOTH REPOSITORIES — see `capability.py` for why, and for the
rules anything added here has to obey. A test in each product compares the
copies and fails when they drift.

Shared by copying rather than by packaging, deliberately and for now. Both
applications ship their engine as source and build it on the customer's machine
with `uv`, so a real dependency would have to be published and credentialed
into both builds. That is the right answer once this layer is large; while it
is two files it would be more machinery than the problem.
"""

from .capability import (
    RUNTIMES,
    UNKNOWN_RUNTIME,
    VOCABULARY_VERSION,
    Capability,
    CommercialUse,
    Component,
    Cost,
    Licence,
    Modality,
    ModelProfile,
    ReasoningSupport,
    RuntimeProfile,
    fits,
    reasoning_support,
    runtime_profile,
    with_capability,
)

__all__ = [
    "RUNTIMES",
    "UNKNOWN_RUNTIME",
    "VOCABULARY_VERSION",
    "Capability",
    "CommercialUse",
    "Component",
    "Cost",
    "Licence",
    "Modality",
    "ModelProfile",
    "ReasoningSupport",
    "RuntimeProfile",
    "fits",
    "reasoning_support",
    "runtime_profile",
    "with_capability",
]
