"""Telling a person what a model's licence says, and getting out of the way.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

This module exists to correct a specific mistake. Both applications refused to
download a model whose licence was not verified permissive — which sounds
careful and is not. It conflated three different things:

* **What the publisher forbids.** Their gate, on their servers: an access
  request, a licence click-through, an auth token. We never route around it.
* **What the user may do with the output.** Their decision, about their work,
  which depends on facts we do not have — whether the campaign is commercial,
  whether they hold a separate licence, whether they are a researcher.
* **What we automatically choose for them.** Ours, and the only one of the
  three we should be deciding.

Blocking the download answered the second question on the user's behalf, using
a field that is *unverified* for almost every model somebody installs from
disk. A researcher could not download a research-only model. Somebody who had
bought a commercial licence directly from a publisher could not use it.

So the rule here:

    Disclose before, decide during, never pre-empt.

A licence never blocks a download. It is shown, plainly, and where the terms
are restrictive or unread it is shown as something to acknowledge rather than
a paragraph under a button. What terms *do* still govern is automatic
selection: when the application picks a model on somebody's behalf for work
they have told us is commercial, it will not quietly pick one whose licence
says no. That is not a restriction on the user; it is the software declining
to make an unsafe choice for them silently.

Nothing in this module widens a licence. It cannot make a forbidden model
allowed, and an acknowledgement is a record that somebody was told — not a
grant, not a permission, and never a defence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..foundation.capability import CommercialUse, Licence, ModelProfile


class Severity:
    """How hard to press, in the order an interface should escalate."""

    NONE = "none"
    #: Worth reading, shown inline. Does not interrupt.
    NOTE = "note"
    #: Must be acknowledged once before the model is installed.
    ACKNOWLEDGE = "acknowledge"


#: What each classification means for a person, in their terms rather than the
#: publisher's. Written out rather than generated, because the difference
#: between "you may not" and "nobody has checked" is the entire point and a
#: template would blur it.
_HEADLINE = {
    CommercialUse.ALLOWED:
        "Commercial use permitted",
    CommercialUse.CONDITIONAL:
        "Commercial use permitted, with conditions",
    CommercialUse.FORBIDDEN:
        "Not licensed for commercial use",
    CommercialUse.RESEARCH_ONLY:
        "Licensed for research only",
    CommercialUse.UNVERIFIED:
        "Licence not checked",
}

_EXPLANATION = {
    CommercialUse.ALLOWED:
        "The publisher permits commercial use of what this model produces.",
    CommercialUse.CONDITIONAL:
        "The publisher permits commercial use if certain conditions are met. "
        "They are listed below, and they are the publisher's, not ours.",
    CommercialUse.FORBIDDEN:
        "The publisher does not permit commercial use of what this model "
        "produces. You can still install and use it — for personal work, for "
        "evaluation, or under a separate licence you hold — but this "
        "application will not choose it on your behalf for commercial work.",
    CommercialUse.RESEARCH_ONLY:
        "The publisher licenses this model for research. You can still install "
        "it; this application will not choose it on your behalf for commercial "
        "work.",
    CommercialUse.UNVERIFIED:
        "Nobody has recorded what this model's licence says, so there is "
        "nothing here to rely on in either direction. It is not a yes and it "
        "is not a no. If you know the terms, you can record them.",
}


@dataclass(frozen=True)
class Disclosure:
    """What to show a person about one model's terms, and how firmly."""

    model_id: str
    model_name: str
    headline: str
    explanation: str
    severity: str
    licence: Licence
    conditions: tuple[str, ...] = ()
    #: Set when the parts of a pipeline disagree. An interface must say so
    #: rather than picking one of them to display.
    per_component: tuple[tuple[str, str, str], ...] = ()
    #: Whether the publisher's own gate stands between here and the weights:
    #: an access request, an acceptance on their site, a token. Reported so a
    #: failed download reads as "they need you to agree over there" rather
    #: than as a bug.
    publisher_gate: bool = False

    @property
    def must_acknowledge(self) -> bool:
        return self.severity == Severity.ACKNOWLEDGE

    @property
    def mixed(self) -> bool:
        return len(self.per_component) > 1

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id, "model_name": self.model_name,
            "headline": self.headline, "explanation": self.explanation,
            "severity": self.severity,
            "must_acknowledge": self.must_acknowledge,
            "conditions": list(self.conditions),
            "licence_id": self.licence.id, "licence_name": self.licence.name,
            "url": self.licence.url,
            "commercial_use": self.licence.commercial_use.value,
            "verified": self.licence.verified,
            "verified_by": self.licence.verified_by,
            "verified_on": self.licence.verified_on,
            "redistributable": self.licence.redistributable,
            "per_component": [{"role": r, "name": n, "licence": lic}
                              for r, n, lic in self.per_component],
            "mixed": self.mixed,
            "publisher_gate": self.publisher_gate,
        }


def _severity(licence: Licence) -> str:
    """How firmly to present these terms.

    Permissive and verified is the only combination that passes without
    comment. Everything else is at least a note, and the two cases somebody
    could be genuinely caught out by — restrictive terms, and terms nobody has
    read — are acknowledged once.
    """
    if licence.commercial_use is CommercialUse.ALLOWED and licence.verified:
        return Severity.NONE
    if licence.commercial_use is CommercialUse.ALLOWED:
        # Permissive, but nobody recorded checking. Worth saying and not worth
        # stopping for: the claim is probably right, and it is the reader's to
        # weigh.
        return Severity.NOTE
    # Everything else is acknowledged once. Conditional belongs here rather
    # than with the notes: its conditions are OBLIGATIONS ON THE USER — a
    # revenue cap, an attribution, a field-of-use limit — and somebody who
    # breaches one because it was a grey paragraph under a button has been
    # failed by the interface.
    return Severity.ACKNOWLEDGE


def describe(profile: ModelProfile, *, publisher_gate: bool = False
             ) -> Disclosure:
    """What a person should be told before installing this model."""
    licence = profile.licence
    use = licence.commercial_use

    explanation = _EXPLANATION[use]
    if use is CommercialUse.ALLOWED and not licence.verified:
        # A permissive claim nobody has checked is not the same as a permissive
        # licence, and it should not read like one.
        explanation = (
            "The catalogue records this as permitting commercial use, but "
            "there is no record of who checked or when. Publishers relicense; "
            "the licence itself is the authority.")

    components: list[tuple[str, str, str]] = []
    if profile.mixed_licensing:
        components.append(("model", profile.name,
                           licence.name or licence.id or "unstated"))
        for component in profile.components:
            components.append((
                component.role, component.name,
                component.licence.name or component.licence.id or "unstated"))

    severity = _severity(licence)
    if profile.mixed_licensing:
        # Parts that disagree are always worth stopping for, whatever the
        # headline licence says. This is the case that catches people out:
        # a permissive transformer with a restrictive text encoder.
        severity = Severity.ACKNOWLEDGE

    return Disclosure(
        model_id=profile.id,
        model_name=profile.name,
        headline=_HEADLINE[use],
        explanation=explanation,
        severity=severity,
        licence=licence,
        conditions=licence.conditions,
        per_component=tuple(components),
        publisher_gate=publisher_gate)


def permits_commercial(licence: Licence) -> bool:
    """Whether these terms allow commercial use with no further judgement.

    Conditional is deliberately not a yes. The conditions are the publisher's
    — revenue caps, attribution, field-of-use — and the application cannot
    know whether a given user meets them. Somebody who does meet them can
    record that; guessing on their behalf would be inventing a grant.
    """
    return licence.commercial_use is CommercialUse.ALLOWED


def may_auto_select(licence: Licence, *, commercial: bool) -> tuple[bool, str]:
    """Whether the application may pick this model for somebody, unprompted.

    The one place terms still restrict anything, and the reason is narrow: an
    automatic choice is one nobody looked at. A person deliberately selecting a
    research-only model has made a decision; the software reaching for the same
    model on its own has made it for them.
    """
    if not commercial:
        return True, ""
    if permits_commercial(licence):
        return True, ""
    if licence.commercial_use is CommercialUse.CONDITIONAL:
        return False, ("its licence allows commercial use only under "
                       "conditions that have to be met by you, not by us")
    if licence.commercial_use is CommercialUse.UNVERIFIED:
        return False, ("nobody has recorded what its licence permits, and an "
                       "unknown is not a yes")
    return False, f"its licence does not permit commercial use " \
                  f"({licence.commercial_use.value})"


@dataclass(frozen=True)
class Acknowledgement:
    """A record that somebody was shown terms and said they understood.

    Not a permission and not a grant. It exists so that the same warning is not
    thrown at a person every time they open a screen, and so that a support
    conversation six weeks later can establish what they were actually told.
    """

    model_id: str
    #: The classification at the moment of acknowledgement. Kept because a
    #: publisher who relicenses invalidates it — somebody who acknowledged
    #: "research only" has not acknowledged whatever it became.
    commercial_use: str
    licence_id: str
    acknowledged_at: str

    def stale_against(self, licence: Licence) -> bool:
        return (self.commercial_use != licence.commercial_use.value
                or self.licence_id != licence.id)

    def to_dict(self) -> dict:
        return {"model_id": self.model_id,
                "commercial_use": self.commercial_use,
                "licence_id": self.licence_id,
                "acknowledged_at": self.acknowledged_at}


def acknowledge(profile: ModelProfile) -> Acknowledgement:
    return Acknowledgement(
        model_id=profile.id,
        commercial_use=profile.licence.commercial_use.value,
        licence_id=profile.licence.id,
        acknowledged_at=datetime.now(UTC).isoformat(timespec="seconds"))


#: The one acknowledgement that is about the catalogue rather than about a
#: model. Stored under a reserved id so it travels with the others.
UNVERIFIED_CLASS = "*unverified*"


@dataclass
class Ledger:
    """Acknowledgements this machine has recorded.

    In memory here; each application persists it the way it persists everything
    else. Deliberately not a gate — `needed` answers a question, it does not
    stop anything.
    """

    entries: dict[str, Acknowledgement] = field(default_factory=dict)

    def record(self, acknowledgement: Acknowledgement) -> None:
        self.entries[acknowledgement.model_id] = acknowledgement

    def acknowledge(self, profile: ModelProfile) -> Acknowledgement:
        """Record that these terms were shown, at whichever scope fits.

        The caller does not choose. Which scope an acknowledgement has follows
        from what was actually being said — a specific restriction is about the
        model, "nobody checked" is about the catalogue — and letting two
        applications decide that separately is how they end up disagreeing.
        """
        if profile.licence.commercial_use is CommercialUse.UNVERIFIED:
            return self.acknowledge_unverified()
        made = acknowledge(profile)
        self.record(made)
        return made

    def acknowledge_unverified(self) -> Acknowledgement:
        """Record that the user understands what an unread licence means.

        Once, for the whole catalogue, rather than per model — see `needed`.
        """
        made = Acknowledgement(
            model_id=UNVERIFIED_CLASS,
            commercial_use=CommercialUse.UNVERIFIED.value, licence_id="",
            acknowledged_at=datetime.now(UTC).isoformat(timespec="seconds"))
        self.record(made)
        return made

    def needed(self, profile: ModelProfile) -> bool:
        """Whether this model's terms still need acknowledging.

        Two kinds, and the distinction is what keeps this from becoming noise.

        A SPECIFIC restriction — forbidden, research-only, conditions to meet —
        is about this model, and is acknowledged per model. It is rare, it is
        actionable, and it is worth a stop.

        "Nobody has read this licence" is not about the model at all; it is a
        statement about how much the catalogue knows. In a catalogue where that
        is true of most entries, asking per model would put an identical dialog
        in front of every single download — which does not inform anybody, and
        does train them to dismiss the dialogs that matter. So it is
        acknowledged ONCE, as the class of thing it is.
        """
        disclosure = describe(profile)
        if not disclosure.must_acknowledge:
            return False
        if profile.licence.commercial_use is CommercialUse.UNVERIFIED:
            return UNVERIFIED_CLASS not in self.entries
        existing = self.entries.get(profile.id)
        if existing is None:
            return True
        # Consent to terms that no longer exist is not consent: a publisher who
        # relicenses invalidates what somebody was told.
        return existing.stale_against(profile.licence)
