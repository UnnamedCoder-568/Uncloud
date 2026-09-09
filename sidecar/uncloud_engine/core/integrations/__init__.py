"""Connecting Uncloud to things outside it, without giving anything away.

Four rules hold this together, and each is a way this kind of feature normally
goes wrong. They are stated once in `contract`, made structural by `registry`,
and the credential half is `credentials`:

* a connection is not a permission — the gate decides, every time;
* a skill inherits nothing from an integration it names;
* credentials never enter model context, because nothing here returns one;
* a write is previewed, and the preview is what a person approves.
"""

from .contract import (
    Action,
    Change,
    Integration,
    IntegrationError,
    Sensitivity,
)
from .registry import (
    all_integrations,
    describe,
    find_action,
    get,
    may_send_to_remote_model,
    perform,
    preview,
)

__all__ = [
    "Action", "Change", "Integration", "IntegrationError", "Sensitivity",
    "all_integrations", "describe", "find_action", "get",
    "may_send_to_remote_model", "perform", "preview",
]
