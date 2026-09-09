"""Third-party notices: who else's work is in here, and under what terms.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Most open-source licences the applications depend on — MIT, BSD, Apache-2.0 —
require the copyright notice and licence text to travel with any distribution.
That obligation is on us, it is easy to satisfy, and shipping without it is the
kind of quiet non-compliance that only surfaces when somebody is doing due
diligence on a purchase.

Two things this deliberately does not do.

**It does not generate the list by scanning site-packages at runtime.** That
produces a different answer on every machine, includes things the build does
not ship, and misses the ones vendored in. The list is a file somebody
maintains, generated at build time and checked in, so that what a user reads is
what was actually shipped.

**It does not classify anything.** A notice is a quotation. Where a licence
text was not captured, it says so rather than substituting a summary — an
approximated licence is worse than an absent one, because it reads as
authoritative.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: Beside the documents, generated at build time.
NOTICES = Path(__file__).parent / "documents" / "third-party.json"


@dataclass(frozen=True)
class Notice:
    """One dependency, as it will be displayed."""

    name: str
    version: str = ""
    licence: str = ""
    url: str = ""
    #: The licence text itself, where the build captured it. Empty is honest
    #: and is rendered as "not captured", never as "none required".
    text: str = ""
    #: python | node | rust | model | asset — so the list can be grouped by
    #: what a reader is actually looking for.
    kind: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.licence)

    def to_dict(self, *, text: bool = False) -> dict:
        out = {"name": self.name, "version": self.version,
               "licence": self.licence or "not recorded", "url": self.url,
               "kind": self.kind, "complete": self.complete,
               "has_text": bool(self.text)}
        if text:
            out["text"] = self.text
        return out


def load(path: Path | str = NOTICES) -> list[Notice]:
    """Read the shipped notice file. An absent file is an empty list.

    Absent rather than an error: a developer checkout that has not run the
    build step should still start. What must not happen is a *release* shipping
    without it, and that is a packaging test's job, not this function's.
    """
    path = Path(path)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = raw.get("notices", raw) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return []
    out = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        out.append(Notice(
            name=str(entry["name"]), version=str(entry.get("version", "")),
            licence=str(entry.get("licence", "")), url=str(entry.get("url", "")),
            text=str(entry.get("text", "")), kind=str(entry.get("kind", ""))))
    return sorted(out, key=lambda n: (n.kind, n.name.lower()))


def summarise(entries: list[Notice]) -> dict:
    """Counts by licence and by kind, plus what is missing.

    `incomplete` is surfaced rather than buried: it is the number somebody
    needs before a release, and a list that quietly omitted its own gaps would
    read as finished when it was not.
    """
    by_licence: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for notice in entries:
        by_licence[notice.licence or "not recorded"] = \
            by_licence.get(notice.licence or "not recorded", 0) + 1
        by_kind[notice.kind or "other"] = by_kind.get(notice.kind or "other", 0) + 1
    return {
        "total": len(entries),
        "incomplete": sum(1 for n in entries if not n.complete),
        "by_licence": dict(sorted(by_licence.items())),
        "by_kind": dict(sorted(by_kind.items())),
    }
