"""Uncloud's side of the shared legal core: where consent is kept.

A thin adapter and nothing more. Which versions still count, whether a revision
was material, and how firmly to present a model's terms are all decisions the
shared `legal` package makes; this only remembers the answers, in the settings
file where the rest of this application's state already lives.

Kept in its own module rather than in `main.py` for the same reason the package
it adapts is kept away from the permission gate: these are two different kinds
of stored yes, and the more places they sit side by side the easier it is for
one to end up standing in for the other.
"""

from __future__ import annotations

from importlib import metadata

from .config import Settings
from .legal import Acceptance, Ledger, Register, Store, load_all
from .legal.disclosure import Acknowledgement


def _app_version() -> str:
    """The build that asked, for the consent record.

    Best effort. A missing version makes the record slightly less useful in a
    support conversation; failing to start over it would be absurd.
    """
    try:
        return metadata.version("astro-engine")
    except Exception:  # noqa: BLE001 - never worth a startup failure
        return ""


class SettingsStore(Store):
    """Acceptances in `settings.json`, beside everything else Uncloud keeps."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def record(self, acceptance: Acceptance) -> None:
        self._settings.record_acceptance(acceptance.to_dict())

    def accepted(self, document_id: str) -> Acceptance | None:
        for raw in self._settings.terms_acceptances:
            if raw.get("document_id") == document_id:
                return Acceptance(
                    document_id=raw["document_id"], version=int(raw["version"]),
                    accepted_at=str(raw.get("accepted_at", "")),
                    app_version=str(raw.get("app_version", "")))
        return None

    def all(self) -> list[Acceptance]:
        out = []
        for raw in self._settings.terms_acceptances:
            found = self.accepted(str(raw.get("document_id", "")))
            if found is not None:
                out.append(found)
        return sorted(out, key=lambda a: a.document_id)


def register(settings: Settings) -> Register:
    """The agreements this build asks for, and what has been accepted.

    Rebuilt per call rather than cached: a cached register is one that can
    disagree with the settings file after an acceptance, and for a consent
    record that is the wrong direction to be wrong in.
    """
    return Register(documents=load_all(), store=SettingsStore(settings),
                    app_version=_app_version())


def ledger(settings: Settings) -> Ledger:
    """Which model licences have been shown and acknowledged."""
    entries = {}
    for model_id, raw in settings.licence_acknowledgements.items():
        entries[model_id] = Acknowledgement(
            model_id=model_id,
            commercial_use=str(raw.get("commercial_use", "")),
            licence_id=str(raw.get("licence_id", "")),
            acknowledged_at=str(raw.get("acknowledged_at", "")))
    return Ledger(entries=entries)
