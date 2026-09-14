"""Reaching a local engine from another device on the same network.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

LAN and nothing further. There is no relay, no tunnel, no port forwarding and
no account, and that is a boundary rather than an unfinished edge: the moment
this is reachable from outside the building it stops being a local-first
product and becomes a service with a threat model to match. Somebody who wants
it from elsewhere should put a real overlay network under it — Tailscale and
the like exist and are better at this than anything that could be written here.

What is in the box:

* `qr`         — a QR encoder, so a pairing URL can be scanned off a terminal.
* `codes`      — the two secrets: one to scan, one to type.
* `pairing`    — minting and spending them, once, within five minutes.
* `sessions`   — paired devices, which survive restarts; secrets hashed on disk.
* `guard`      — Host and Origin checking, which is what makes cookie auth safe.
* `interfaces` — every address this machine could be reached on, unranked.
* `tls`        — a local authority, because the pairing secret crosses the wire.
* `service`    — the seven of those assembled, plus the block printed on start.
"""

from .guard import Guard
from .interfaces import Interface, candidates, default_address
from .pairing import LIFETIME, Offer, Pairing, RateLimited
from .service import Lan, Reach
from .sessions import Session, Sessions, describe
from .tls import Material

__all__ = [
    "LIFETIME",
    "Guard",
    "Interface",
    "Lan",
    "Material",
    "Offer",
    "Pairing",
    "RateLimited",
    "Reach",
    "Session",
    "Sessions",
    "candidates",
    "default_address",
    "describe",
]
