"""Terms a person has to agree to, and the record that they did.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

The whole module rests on one separation, and it is the separation the brief
was emphatic about:

    Accepting terms is not granting a permission.

They look similar — both are a person saying yes, both are stored, both are
shown in Settings — and collapsing them is the mistake that would let "I agreed
to the terms on first launch" turn into "the agent may run shell commands".
So this package does not import the permission gate, the gate does not import
this, and a test holds them apart. Terms describe the relationship between a
person and the software. Permissions describe what a running agent may do in
the next thirty seconds. Neither implies the other.

Three further decisions.

**Versions are integers, and not every version voids consent.** Fixing a typo
in a heading should not throw a modal at everybody who already agreed. A
material change should. The document says which it was, rather than a diff
guessing, because only a person can know whether a wording change altered an
obligation.

**Acceptance is recorded, never assumed.** There is no "presumed accepted
because the app is running". A missing record means not accepted, which is the
safe direction and the only honest one.

**Nothing here blocks work a person has already done.** The same rule the
product licensing already follows: whatever the state of an agreement, a user
can open and export their own files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

#: Where the shared documents live, beside this module. Byte-identical in both
#: products: the core agreement is the same agreement.
DOCUMENTS = Path(__file__).parent / "documents"

#: What this particular application adds. Not shared, and not drift-checked —
#: Studio's supplement is about activation and advertising, Uncloud's is about
#: an agent that can run shell commands, and neither belongs in the other.
PRODUCT = Path(__file__).parent / "product"

#: Frontmatter is a handful of `key: value` lines between `---` fences. Small
#: enough not to want a YAML dependency in a package that is deliberately
#: standard-library only.
_FENCE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class Malformed(ValueError):
    """A document that cannot be trusted to display. Raised loudly at load.

    A terms document that silently loaded with an empty body would show a
    person a blank agreement and record that they accepted it, which is worse
    than not starting.
    """


@dataclass(frozen=True)
class Document:
    """One agreement, at one version."""

    id: str
    title: str
    #: Monotonic. Compared, never parsed for meaning.
    version: int
    #: ISO date the version took effect. Displayed, not enforced — a clock
    #: that has drifted must not lock somebody out of their own software.
    effective: str
    body: str
    #: The earliest still-valid acceptance. Equal to `version` when the change
    #: was material; lower when it was editorial and old consent still stands.
    accepted_from: int = 1
    #: What changed, in a sentence, for the person being asked again.
    changes: str = ""
    #: Which product this belongs to. Empty means the shared core, which
    #: applies to every application.
    product: str = ""
    #: Whether this must be agreed to before the application can be used at
    #: all. A privacy notice is required reading; it is not a contract, and
    #: putting a checkbox on it teaches people to click through the ones that
    #: matter.
    requires_agreement: bool = True

    @property
    def material(self) -> bool:
        """Whether this version voided earlier consent."""
        return self.accepted_from >= self.version

    def satisfied_by(self, accepted_version: int | None) -> bool:
        """Whether an acceptance at that version still counts."""
        if accepted_version is None:
            return False
        return accepted_version >= self.accepted_from

    def to_dict(self, *, body: bool = False) -> dict:
        out = {
            "id": self.id, "title": self.title, "version": self.version,
            "effective": self.effective, "accepted_from": self.accepted_from,
            "material": self.material, "changes": self.changes,
            "product": self.product,
            "requires_agreement": self.requires_agreement,
        }
        if body:
            out["body"] = self.body
        return out


@dataclass(frozen=True)
class Acceptance:
    """That a person agreed, to what, and when.

    Deliberately thin. It records the fact of agreement and nothing about the
    person beyond what the application already knows about itself — no name, no
    email, no address. A consent record that quietly became a contact database
    would be its own privacy problem.
    """

    document_id: str
    version: int
    accepted_at: str
    #: The build that asked. Useful when somebody reports they were never
    #: shown something.
    app_version: str = ""

    def to_dict(self) -> dict:
        return {"document_id": self.document_id, "version": self.version,
                "accepted_at": self.accepted_at, "app_version": self.app_version}


@dataclass
class Outstanding:
    """A document that still needs agreeing to, and why it is being asked."""

    document: Document
    #: "new" — never seen; "changed" — accepted, then materially revised.
    because: str
    previously: int | None = None

    def to_dict(self) -> dict:
        return {**self.document.to_dict(), "because": self.because,
                "previously": self.previously}


def parse(text: str, *, source: str = "") -> Document:
    """Read one document from its markdown, frontmatter first."""
    found = _FENCE.match(text)
    if found is None:
        raise Malformed(f"{source or 'document'} has no frontmatter")

    meta: dict[str, str] = {}
    for line in found.group(1).splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()

    body = text[found.end():].strip()
    if not body:
        raise Malformed(f"{source or 'document'} has no body")

    try:
        version = int(meta.get("version", ""))
    except ValueError as exc:
        raise Malformed(
            f"{source or 'document'} has no usable version") from exc

    accepted_from = meta.get("accepted_from", "")
    return Document(
        id=meta.get("id", "").strip(),
        title=meta.get("title", "").strip(),
        version=version,
        effective=meta.get("effective", "").strip(),
        body=body,
        accepted_from=int(accepted_from) if accepted_from.isdigit() else version,
        changes=meta.get("changes", "").strip(),
        product=meta.get("product", "").strip(),
        requires_agreement=meta.get("requires_agreement", "true").lower() != "false",
    )


def load(directory: Path | str = DOCUMENTS) -> list[Document]:
    """Every document in a directory, ordered for display.

    The core comes before a product's own supplement, because that is the order
    they are read in: the general agreement, then what this application adds
    to it.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    out: list[Document] = []
    for path in sorted(directory.glob("*.md")):
        document = parse(path.read_text(encoding="utf-8"), source=path.name)
        if not document.id:
            raise Malformed(f"{path.name} has no id")
        out.append(document)
    return sorted(out, key=_order)


def _order(document: Document) -> tuple:
    """Reading order: the core agreement, then this product's supplement to it,
    then anything that is required reading rather than an agreement."""
    return (not document.requires_agreement, bool(document.product), document.id)


def load_all() -> list[Document]:
    """Everything this application asks somebody to read.

    Two directories rather than one, because the core terms are shared verbatim
    between the products and the supplement is not. Loaded together so that
    nothing downstream has to know there were two.
    """
    return sorted(load(DOCUMENTS) + load(PRODUCT), key=_order)


class Store:
    """Where acceptances live. Implemented by each application.

    An interface rather than a table, because the two products already have
    their own databases and their own migration numbering, and a shared package
    that opened its own SQLite file would be a third place for state to be.
    """

    def record(self, acceptance: Acceptance) -> None:  # pragma: no cover
        raise NotImplementedError

    def accepted(self, document_id: str) -> Acceptance | None:  # pragma: no cover
        raise NotImplementedError

    def all(self) -> list[Acceptance]:  # pragma: no cover
        raise NotImplementedError


class Memory(Store):
    """An in-process store. Used by tests, and by nothing else."""

    def __init__(self) -> None:
        self._by_id: dict[str, Acceptance] = {}

    def record(self, acceptance: Acceptance) -> None:
        existing = self._by_id.get(acceptance.document_id)
        # Keep the highest version accepted. Re-accepting an older version —
        # possible if somebody downgrades the app — must not withdraw consent
        # already given to a newer one.
        if existing is None or acceptance.version >= existing.version:
            self._by_id[acceptance.document_id] = acceptance

    def accepted(self, document_id: str) -> Acceptance | None:
        return self._by_id.get(document_id)

    def all(self) -> list[Acceptance]:
        return sorted(self._by_id.values(), key=lambda a: a.document_id)


@dataclass
class Register:
    """The documents this application has, and what is still outstanding."""

    documents: list[Document] = field(default_factory=list)
    store: Store = field(default_factory=Memory)
    app_version: str = ""

    def get(self, document_id: str) -> Document | None:
        return next((d for d in self.documents if d.id == document_id), None)

    def outstanding(self) -> list[Outstanding]:
        """Everything that must be agreed to before the application is usable.

        Documents that are required reading rather than agreements are not
        listed. Asking somebody to tick a box on a privacy notice is how you
        teach them that ticking boxes is meaningless.
        """
        out: list[Outstanding] = []
        for document in self.documents:
            if not document.requires_agreement:
                continue
            accepted = self.store.accepted(document.id)
            version = accepted.version if accepted else None
            if document.satisfied_by(version):
                continue
            out.append(Outstanding(
                document=document,
                because="changed" if accepted else "new",
                previously=version))
        return out

    @property
    def settled(self) -> bool:
        return not self.outstanding()

    def accept(self, document_id: str, version: int) -> Acceptance:
        """Record agreement to a specific version.

        The version is passed in rather than taken from the register, so that
        a person can only accept what they were actually shown. An interface
        that displayed version 3 while the engine recorded version 4 would
        produce a consent record that is not true.
        """
        document = self.get(document_id)
        if document is None:
            raise KeyError(f"no document {document_id!r}")
        if version != document.version:
            raise ValueError(
                f"{document_id} is at version {document.version}; refusing to "
                f"record agreement to version {version}, which is not what "
                f"would have been displayed.")
        acceptance = Acceptance(
            document_id=document_id, version=version,
            accepted_at=datetime.now(UTC).isoformat(timespec="seconds"),
            app_version=self.app_version)
        self.store.record(acceptance)
        return acceptance

    def state(self) -> dict:
        """Everything an interface needs to decide what to show."""
        accepted = {a.document_id: a for a in self.store.all()}
        return {
            "settled": self.settled,
            "outstanding": [o.to_dict() for o in self.outstanding()],
            "documents": [
                {**d.to_dict(),
                 "accepted": accepted[d.id].to_dict() if d.id in accepted else None}
                for d in self.documents
            ],
        }
