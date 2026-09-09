"""The shared legal core: agreements, model-licence disclosure, and notices.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Three separate things live here, and the reason they are one package is that
they are all statements about *terms* — what a person agreed to, what a
publisher permits, whose work is included. None of them is a runtime control.

The boundary that matters, stated once and enforced by a test:

    This package must never import the permission gate, and the gate must
    never import this package.

Agreeing to terms of use is not granting an agent permission to run a shell
command, and one must never be able to satisfy the other. They are both
recorded consent, which is exactly why keeping them apart has to be
structural rather than a matter of remembering.
"""

from .disclosure import (
    Acknowledgement,
    Disclosure,
    Ledger,
    Severity,
    acknowledge,
    describe,
    may_auto_select,
    permits_commercial,
)
from .notices import Notice, summarise
from .notices import load as load_notices
from .terms import (
    Acceptance,
    Document,
    Malformed,
    Memory,
    Outstanding,
    Register,
    Store,
    load_all,
    parse,
)
from .terms import load as load_documents

__all__ = [
    "Acceptance", "Acknowledgement", "Disclosure", "Document", "Ledger",
    "Malformed", "Memory", "Notice", "Outstanding", "Register", "Severity",
    "Store", "acknowledge", "describe", "load_all", "load_documents",
    "load_notices", "may_auto_select", "parse", "permits_commercial",
    "summarise",
]
