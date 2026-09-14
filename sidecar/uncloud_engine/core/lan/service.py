"""The LAN surface as one object, and the block of text it prints.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Both products need the same seven things in the same order — decide which
addresses to offer, get certificates for them, build the Host allowlist from
exactly those addresses, mint a pairing offer, render it, check sessions, and
revoke them. This holds all seven so neither product writes its own version and
they drift.

What this deliberately does NOT hold is a web framework. Core is imported by
two applications and imports neither; the routes live with each product and
call into this.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import qr
from .guard import Guard
from .interfaces import Interface, candidates
from .pairing import Offer, Pairing
from .sessions import Sessions
from .tls import Material, ensure

#: The cookie the browser sends back. Named per product so two products on one
#: machine do not overwrite each other's session.
COOKIE_PREFIX = "lan_session"


@dataclass(frozen=True)
class Reach:
    """One address, and the URL a device would open to pair with it."""

    interface: Interface
    url: str


class Lan:
    """Everything the LAN listener needs, assembled once at startup."""

    def __init__(self, *, product: str, slug: str, config_dir: Path, port: int,
                 chosen: list[Interface] | None = None) -> None:
        self.product = product
        self.slug = slug
        self.port = port
        self.interfaces: tuple[Interface, ...] = tuple(
            chosen if chosen is not None else candidates())

        addresses = tuple(i.address for i in self.interfaces)
        self.material: Material = ensure(config_dir / "lan", addresses, product=product)

        # Built from exactly the addresses being served, so a Host header for
        # anything else — including an attacker's rebound hostname — is refused
        # before any route sees it.
        self.guard = Guard.build(list(addresses), port)
        self.pairing = Pairing()
        self.sessions = Sessions(config_dir / "lan" / "sessions.json")
        self.cookie = f"{COOKIE_PREFIX}_{slug}"

    # ------------------------------------------------------------------ pairing

    def offer(self) -> Offer:
        """Mint a fresh single-use offer, replacing any that was outstanding."""
        return self.pairing.mint()

    def reaches(self, offer: Offer) -> list[Reach]:
        out = []
        for interface in self.interfaces:
            host = (f"[{interface.address}]" if ":" in interface.address
                    else interface.address)
            out.append(Reach(interface=interface,
                             url=f"https://{host}:{self.port}/pair?t={offer.token}"))
        return out

    # ----------------------------------------------------------------- printing

    def banner(self, offer: Offer, *, colour: bool = True) -> str:
        """The whole block to print on start, or when `pair` is run.

        One QR per candidate address, each labelled, because this machine
        cannot know which network the phone is on. A single QR would be a guess
        that fails silently.
        """
        lines: list[str] = ["", f"  {self.product} is available on this network.", ""]

        if not self.interfaces:
            lines += [
                "  No network interface with a usable address was found.",
                "  Connect to a network and run pairing again.", ""]
            return "\n".join(lines)

        reaches = self.reaches(offer)
        if len(reaches) > 1:
            lines += [
                f"  This machine has {len(reaches)} addresses and only one of them is",
                "  reachable from the device you are holding. Scan the one that",
                "  matches the network that device is on.", ""]

        for reach in reaches:
            lines += [f"  {reach.interface.label}", ""]
            lines += ["    " + row for row in
                      qr.terminal(reach.url, colour=colour).splitlines()]
            # The same secret as the QR, for a laptop that has no camera but
            # can click. Printed only where the QR is, so it goes nowhere new.
            lines += ["", f"    {reach.url}", ""]

        lines += [
            f"  Or open  https://{self._primary()}:{self.port}  and type this code:",
            "",
            f"      {offer.code}",
            "",
            "  The code and the QR are single-use and expire in five minutes.",
            "  A paired device stays paired; this code changes every start.",
            "",
            "  First time on a device, the browser will warn that the connection",
            "  is not private. The connection IS encrypted — the certificate is",
            "  issued by this machine, which no public authority vouches for.",
            "  To silence it for good, install this on the device:",
            "",
            f"      {self.material.authority}",
            f"      SHA-256  {self.material.fingerprint}",
            "",
        ]
        return "\n".join(lines)

    def _primary(self) -> str:
        first = next((i for i in self.interfaces if i.default_route), None)
        first = first or (self.interfaces[0] if self.interfaces else None)
        if first is None:
            return "localhost"
        return f"[{first.address}]" if ":" in first.address else first.address
