"""Knowing that a new version exists, without letting anyone else run code here.

Two products ship as installed desktop applications, so the only way to tell
somebody about a fix is to fetch something and read it. That is a dangerous
shape unless it is built carefully, because "the application does what the
server says" is one bad server away from being a remote execution hole.

So the rule this module is arranged around: **the manifest is data, never
instructions.** Nothing fetched is executed, no URL fetched is opened
automatically, no download starts on its own. What arrives is a description of
something that exists elsewhere, and every field is validated before an
interface is allowed to draw it. An item that does not parse is dropped; a
manifest that does not parse leaves the application exactly as it was.

**An announcement is not an update.** Three different things get confused
constantly and the confusion is the reason a major version silently replaces
the one somebody chose:

* an APPLICATION update replaces the installed app;
* a RUNTIME or MODEL update changes what the app downloads and runs, and needs
  no new app at all — which is what lets a production bug be fixed without a
  release;
* an ANNOUNCEMENT tells somebody something, and a MAJOR one tells them another
  product exists. It never migrates them. They stay where they are until they
  decide otherwise, which for a paid application is not a courtesy, it is the
  difference between an upgrade and a seizure.

**Failing is quiet.** No network, a bad certificate, a truncated body, a
server returning HTML — all of it means the application carries on with
nothing to report. An update checker that can break the thing it is checking
is worse than no update checker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

#: Only https. A manifest fetched over a plaintext connection can be rewritten
#: in transit by anyone on the path, and what it describes is where to get
#: software.
ALLOWED_SCHEME = "https://"

#: Release pages and download links are shown to a person, never opened by the
#: application. Restricting the host anyway means a compromised manifest cannot
#: point somebody at an arbitrary site wearing our interface's clothes.
TRUSTED_HOSTS = ("github.com", "www.github.com", "uncloud.com", "www.uncloud.com")


class Kind(StrEnum):
    """What is being announced. Drives what the interface may offer."""

    PATCH = "patch"
    MINOR = "minor"
    #: Another product line exists. Never an update — see the module docstring.
    MAJOR_ANNOUNCEMENT = "major_announcement"
    RUNTIME = "runtime"
    MODEL = "model"
    HOTFIX = "hotfix"
    ANNOUNCEMENT = "announcement"


#: Kinds that describe replacing the installed application. Everything else is
#: either a component the app manages itself or something to read.
APPLICATION_KINDS = frozenset({Kind.PATCH, Kind.MINOR, Kind.HOTFIX})


class Severity(StrEnum):
    OPTIONAL = "optional"
    RECOMMENDED = "recommended"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Version:
    """A version that can be compared without pretending to be strict semver.

    Both products ship pre-release suffixes — `0.3.0-test.2`, `0.2.0rc2` — and
    a parser that rejected those would refuse to tell somebody about the very
    builds they are running. Numeric parts order numerically; a build with a
    suffix sorts BELOW the same numbers without one, which is what makes
    0.3.0-test.2 older than 0.3.0.
    """

    parts: tuple[int, ...]
    suffix: str = ""
    raw: str = ""

    @classmethod
    def parse(cls, text: str) -> Version | None:
        if not isinstance(text, str):
            return None
        found = re.match(r"^\s*v?(\d+(?:\.\d+)*)(?:[-.+]?([0-9A-Za-z.\-]+))?\s*$",
                         text)
        if not found:
            return None
        numbers = tuple(int(p) for p in found.group(1).split("."))
        return cls(parts=numbers, suffix=(found.group(2) or "").lower(),
                   raw=text.strip())

    def _key(self) -> tuple:
        padded = self.parts + (0,) * (4 - len(self.parts))
        # A release outranks any pre-release of the same numbers.
        return (padded[:4], 1 if not self.suffix else 0, self.suffix)

    def __lt__(self, other: Version) -> bool:
        return self._key() < other._key()

    def __le__(self, other: Version) -> bool:
        return self._key() <= other._key()

    @property
    def major(self) -> int:
        return self.parts[0] if self.parts else 0


@dataclass(frozen=True)
class Item:
    """One thing worth telling somebody. Inert: no field is ever executed."""

    id: str
    kind: Kind
    title: str
    body: str = ""
    severity: Severity = Severity.OPTIONAL
    version: Version | None = None
    url: str = ""
    #: After this date it stops being shown, so a fixed problem stops being
    #: announced without anyone having to remember to withdraw it.
    expires: date | None = None
    dismissible: bool = True

    @property
    def is_application_update(self) -> bool:
        return self.kind in APPLICATION_KINDS

    @property
    def replaces_installation(self) -> bool:
        """Whether acting on this changes the application in place.

        False for a major announcement even though it names a version — the
        whole point is that Studio 1 does not become Studio 2 by being told
        Studio 2 exists.
        """
        return self.is_application_update

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind.value, "title": self.title,
            "body": self.body, "severity": self.severity.value,
            "version": self.version.raw if self.version else "",
            "url": self.url,
            "expires": self.expires.isoformat() if self.expires else "",
            "dismissible": self.dismissible,
            "is_application_update": self.is_application_update,
            "replaces_installation": self.replaces_installation,
        }


@dataclass
class Report:
    """What this machine should be told, and nothing it should not."""

    items: tuple[Item, ...] = ()
    #: Set when the running build is below the manifest's floor. Carried
    #: separately because it is a statement about THIS install rather than an
    #: item in a list.
    unsupported: bool = False
    #: Why there is nothing to say, when there is nothing to say. Never shown
    #: as an error: a checker that cannot reach its server has not found a
    #: problem with the application.
    note: str = ""

    @property
    def critical(self) -> tuple[Item, ...]:
        return tuple(i for i in self.items if i.severity is Severity.CRITICAL)

    def to_dict(self) -> dict:
        return {"items": [i.to_dict() for i in self.items],
                "unsupported": self.unsupported, "note": self.note,
                "critical": [i.to_dict() for i in self.critical]}


def _trusted(url: str) -> bool:
    if not isinstance(url, str) or not url.startswith(ALLOWED_SCHEME):
        return False
    host = url[len(ALLOWED_SCHEME):].split("/", 1)[0].split(":", 1)[0].lower()
    return host in TRUSTED_HOSTS


def _item(raw: dict, *, current: Version) -> Item | None:
    """One entry, validated. Returns None rather than raising.

    A single malformed item must not cost the user the rest of the manifest,
    and a manifest is written by hand often enough that one will be malformed.
    """
    if not isinstance(raw, dict):
        return None
    try:
        kind = Kind(str(raw.get("kind", "")).strip().lower())
    except ValueError:
        return None

    identifier = str(raw.get("id") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not identifier or not title:
        return None

    try:
        severity = Severity(str(raw.get("severity", "optional")).strip().lower())
    except ValueError:
        severity = Severity.OPTIONAL

    version = Version.parse(raw.get("version", "")) if raw.get("version") else None

    # Anything describing a version of THIS product must be newer than what is
    # running. Without this a rolled-back or replayed manifest walks somebody
    # backwards, which is the downgrade attack in its simplest form.
    if version is not None and kind in APPLICATION_KINDS and version <= current:
        return None

    url = str(raw.get("url") or "").strip()
    if url and not _trusted(url):
        url = ""

    expires = None
    if raw.get("expires"):
        try:
            expires = date.fromisoformat(str(raw["expires"]).strip())
        except (TypeError, ValueError):
            return None
        if expires < date.today():
            return None

    return Item(
        id=identifier, kind=kind, title=title,
        body=str(raw.get("body") or "").strip(),
        severity=severity, version=version, url=url, expires=expires,
        # A critical item is not dismissible unless the manifest says so
        # explicitly, and an announcement always is.
        dismissible=bool(raw.get("dismissible",
                                 severity is not Severity.CRITICAL)))


def read(payload: object, *, product: str, current_version: str,
         dismissed: set[str] | None = None) -> Report:
    """Turn a fetched manifest into what this install should be told.

    Everything is filtered here rather than by the caller: which product, which
    version range, what has already been dismissed, what has expired. An
    interface that receives this can draw all of it without deciding anything.
    """
    current = Version.parse(current_version)
    if current is None:
        return Report(note=f"{current_version!r} is not a version this can read.")
    if not isinstance(payload, dict):
        return Report(note="The update manifest was not in a readable shape.")

    if str(payload.get("product", "")).strip().lower() != product.lower():
        return Report(note="The manifest is for a different product.")

    unsupported = False
    floor = Version.parse(str(payload.get("minimumSupportedVersion", "")))
    if floor is not None and current < floor:
        unsupported = True

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return Report(unsupported=unsupported,
                      note="The manifest listed nothing to report.")

    dismissed = dismissed or set()
    items = []
    for entry in raw_items[:50]:
        found = _item(entry, current=current)
        if found is None:
            continue
        if not _applies(entry, current):
            continue
        # A dismissal is honoured unless the item cannot be dismissed. Critical
        # items come back, which is the only reason that flag exists.
        if found.id in dismissed and found.dismissible:
            continue
        items.append(found)

    items.sort(key=lambda i: (i.severity is not Severity.CRITICAL,
                              not i.is_application_update, i.title))
    return Report(items=tuple(items), unsupported=unsupported)


def _applies(raw: dict, current: Version) -> bool:
    """Whether an item targets the running build.

    Ranges are inclusive and either end may be omitted, so "everyone below
    1.4" and "only 2.x" are both expressible without a query language — which
    is deliberate. A manifest that needs evaluating is a manifest that can run
    something.
    """
    low = Version.parse(str(raw.get("appliesFrom", "")))
    high = Version.parse(str(raw.get("appliesTo", "")))
    if low is not None and current < low:
        return False
    return not (high is not None and high < current)
