"""Handing a device the right to talk to this engine, once.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

Nothing here is configured by anybody. The server starts, it mints one QR
token and one typed code, and both die five minutes later or the first time
either is used — whichever comes first. There is no password to choose, no
account to make, and nothing to get wrong at setup, because setup is where
people get security wrong.

Rate limiting is here as depth, not as the control. Sixty bits inside a five
minute window is roughly a one in ten-to-the-eighteenth chance per attempt;
the entropy is what makes guessing hopeless. The limiter exists so that a
machine trying anyway is not also free to spend the CPU, and so that the
attempt shows up somewhere.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

from . import codes

#: Long enough to walk to the other device, short enough that a code left on a
#: screen is not a standing invitation.
LIFETIME = 300.0

#: Failures from one address before the wait starts doubling.
FREE_ATTEMPTS = 5

#: The first wait, and the ceiling. Doubling from one second reaches the cap in
#: about eleven further failures.
BACKOFF_START = 1.0
BACKOFF_CAP = 900.0

#: Failure counts older than this are forgotten, so an honest person who
#: fumbled the code an hour ago is not still being punished for it.
FORGET_AFTER = 3600.0


@dataclass(frozen=True)
class Offer:
    """What is on offer right now. `token` goes in the QR; `code` is typed."""

    token: str
    code: str
    expires: float

    def live(self, now: float | None = None) -> bool:
        return (now if now is not None else time.time()) < self.expires


class RateLimited(Exception):
    """Too many failures from one address. `retry_after` is in seconds."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"Too many attempts; wait {retry_after:.0f}s")
        self.retry_after = retry_after


class Pairing:
    """The live offer, and who has been guessing at it.

    One offer at a time. Minting again replaces what was there, which is what
    `pair` on the command line and the button in the application both do: the
    code on the old screen stops working, which is the point.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._offer: Offer | None = None
        self._failures: dict[str, tuple[int, float]] = {}

    def mint(self, *, now: float | None = None) -> Offer:
        now = time.time() if now is None else now
        offer = Offer(token=codes.token(), code=codes.code(), expires=now + LIFETIME)
        with self._lock:
            self._offer = offer
        return offer

    def current(self, *, now: float | None = None) -> Offer | None:
        with self._lock:
            if self._offer is not None and self._offer.live(now):
                return self._offer
            return None

    def retire(self) -> None:
        """Drop the offer without minting another. Used once pairing is done."""
        with self._lock:
            self._offer = None

    # ------------------------------------------------------------------ redeem

    def _wait_for(self, ip: str, now: float) -> float:
        count, last = self._failures.get(ip, (0, 0.0))
        if now - last > FORGET_AFTER:
            return 0.0
        if count < FREE_ATTEMPTS:
            return 0.0
        wait = min(BACKOFF_START * 2 ** (count - FREE_ATTEMPTS), BACKOFF_CAP)
        return max(0.0, last + wait - now)

    def redeem(self, presented: str, *, kind: str, ip: str,
               now: float | None = None) -> bool:
        """Spend the offer. True only if `presented` is it, and it was unspent.

        Consumption happens under the same lock as the comparison, so two
        devices racing on the same code cannot both win. `kind` is "token" for
        the scanned secret and "code" for the typed one; they are separate
        secrets and a token presented as a code is simply wrong.
        """
        now = time.time() if now is None else now
        with self._lock:
            wait = self._wait_for(ip, now)
            if wait > 0:
                raise RateLimited(wait)

            offer = self._offer
            expected = ""
            if offer is not None and offer.live(now):
                expected = offer.token if kind == "token" else codes.compact(offer.code)

            given = presented if kind == "token" else codes.normalise(presented)

            # Compared even when there is nothing to compare against, so a
            # request arriving after expiry is not faster than a wrong guess.
            # As bytes: compare_digest raises on non-ASCII str, and a query
            # string can carry anything — that would be a 500, not a refusal.
            ok = (bool(expected) and bool(given) and secrets.compare_digest(
                given.encode("utf-8", "surrogateescape"), expected.encode("utf-8")))

            if ok:
                self._offer = None                      # single use, atomically
                self._failures.pop(ip, None)
                return True

            count, last = self._failures.get(ip, (0, 0.0))
            if now - last > FORGET_AFTER:
                count = 0
            self._failures[ip] = (count + 1, now)
            return False
