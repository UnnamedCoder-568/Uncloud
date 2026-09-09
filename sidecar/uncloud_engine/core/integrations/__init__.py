"""Connecting Uncloud to things outside it, without giving anything away.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

An integration exposes CAPABILITIES; a capability is implemented by an ACTION;
an action is governed by the permission gate and, where it changes something,
previewed before it runs. The orchestrator plans in capabilities — `email.send`
— and the registry answers with whatever is connected and able, which is what
keeps provider names out of planning code.

Five rules hold this together, each a way this kind of feature normally goes
wrong:

* a connection is not a permission — the gate decides, every time;
* a skill inherits nothing from an integration it names;
* credentials never enter model context, because nothing here returns one;
* a write is previewed, and the preview is what a person approves;
* risk is derived from the capability, so two providers doing the same thing
  cannot end up under different policies.
"""

from . import documents, ooxml
from .capabilities import (
    Capability,
    Requirement,
    describe_capability,
    risk_of,
    writes,
)
from .contract import (
    Action,
    Change,
    Integration,
    IntegrationError,
    Sensitivity,
)
from .registry import (
    Ungoverned,
    all_integrations,
    capability_map,
    describe,
    find_action,
    get,
    install_approver,
    may_send_to_remote_model,
    perform,
    perform_capability,
    preview,
    providers_for,
)

__all__ = [
    "Action", "Capability", "Change", "Integration", "IntegrationError",
    "Requirement", "Sensitivity", "Ungoverned", "all_integrations",
    "capability_map", "describe", "describe_capability", "find_action", "get",
    "documents", "install_approver", "may_send_to_remote_model", "ooxml",
    "perform",
    "perform_capability", "preview", "providers_for", "risk_of", "writes",
]
