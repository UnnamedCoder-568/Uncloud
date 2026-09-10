"""What is still a blank in the documents this software ships with.

Every legal document here carries `[[PLACEHOLDER]]` tokens where a fact
belongs that only the publisher can supply: the legal entity, the registered
address, the governing jurisdiction, the refund policy. They are deliberate.
Inventing a company name or a jurisdiction would produce an agreement that
looks binding and is not, which is worse than an obvious gap.

Being deliberate is not the same as being safe to forget, and a placeholder is
exactly the kind of thing that survives to release because everyone assumed
somebody else had filled it in. So this makes them countable: an interface can
show them, a release check can fail on them, and nobody has to remember.

**Detection, not policy.** This says what is unfilled; it does not decide
whether that blocks anything. Core has no view on when a product is ready to
sell — that belongs to the application, and to the person who owns the company.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: `[[LEGAL_ENTITY_NAME]]` and friends. Upper case with underscores, so a
#: passage that happens to mention brackets is not mistaken for a blank.
TOKEN = re.compile(r"\[\[([A-Z][A-Z0-9_]{2,})\]\]")


def placeholders(text: str) -> list[str]:
    """Every distinct placeholder in one piece of text, in the order it reads."""
    seen: list[str] = []
    for match in TOKEN.finditer(text or ""):
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen


@dataclass(frozen=True)
class Unfilled:
    """One document, and the facts it is still waiting for."""

    document: str
    title: str
    #: Whether somebody has to agree to this before using the software. An
    #: unfilled blank in a contract people sign is a different problem from one
    #: in a notice they read.
    binding: bool
    missing: tuple[str, ...]

    def to_dict(self) -> dict:
        return {"document": self.document, "title": self.title,
                "binding": self.binding, "missing": list(self.missing)}


def outstanding(documents) -> list[Unfilled]:
    """Which documents still have blanks, worst first.

    `documents` is whatever `terms.load_all()` returned, so this stays a
    function of the text rather than of where the text came from — a test can
    hand it three strings.
    """
    found = [
        Unfilled(document=d.id, title=d.title,
                 binding=bool(getattr(d, "requires_agreement", False)),
                 missing=tuple(placeholders(d.body)))
        for d in documents
    ]
    return sorted((f for f in found if f.missing),
                  key=lambda f: (not f.binding, f.document))


def summary(documents) -> dict:
    """A whole answer for an interface or a release check.

    `ready` is the narrow claim it sounds like: every blank in every document
    has been filled. It says nothing about whether the wording is right, which
    no program can check.
    """
    unfilled = outstanding(documents)
    every = sorted({name for f in unfilled for name in f.missing})
    return {
        "ready": not unfilled,
        "documents": [f.to_dict() for f in unfilled],
        "missing": every,
        "count": len(every),
        "note": ("Every document is filled in."
                 if not unfilled else
                 f"{len(every)} fact(s) have not been supplied yet. They are "
                 f"placeholders on purpose — inventing them would produce an "
                 f"agreement that looks binding and is not."),
    }
