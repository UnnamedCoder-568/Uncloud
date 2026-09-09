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
from .permission import (
    ALWAYS_ASK,
    DEFAULTS,
    POLICY_VERSION,
    ApprovalRequired,
    AuditEntry,
    AuditLog,
    Decision,
    Denied,
    Gate,
    Mode,
    Request,
    Risk,
    clamp,
    dump_policy,
    load_policy,
)

__all__ = [
    "ALWAYS_ASK",
    "DEFAULTS",
    "POLICY_VERSION",
    "RUNTIMES",
    "UNKNOWN_RUNTIME",
    "VOCABULARY_VERSION",
    "ApprovalRequired",
    "AuditEntry",
    "AuditLog",
    "Capability",
    "CommercialUse",
    "Component",
    "Cost",
    "Decision",
    "Denied",
    "Gate",
    "Licence",
    "Modality",
    "Mode",
    "ModelProfile",
    "ReasoningSupport",
    "Request",
    "Risk",
    "RuntimeProfile",
    "clamp",
    "dump_policy",
    "fits",
    "load_policy",
    "reasoning_support",
    "runtime_profile",
    "with_capability",
]
