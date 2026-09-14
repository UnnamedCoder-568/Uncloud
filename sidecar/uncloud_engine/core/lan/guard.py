"""Host and Origin checking: the defence cookie authentication does not give you.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

A bearer token in a header is safe from a hostile web page because the page
cannot read it and therefore cannot send it. A cookie is not: the browser
attaches it for whoever persuaded the browser to make the request. DNS
rebinding is the attack — a page on any domain points its own hostname at
192.168.x.x, waits for the cache to turn over, and then talks to this server
from inside the victim's browser with the victim's cookie attached.

The defence is to refuse any request whose Host header is not one this server
actually answers to, because the rebound request carries the attacker's
hostname. It is cheap, it is absolute, and it must be on EVERY request, not
only the ones that change something: reading somebody's projects is already
the breach.

SameSite=Lax stops cross-site POSTs. It does not stop this, because after
rebinding the request is not cross-site any more — it is the attacker's origin
talking to itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Guard:
    """The hosts and origins this server admits.

    `hosts` are authority strings as they appear in a Host header, lowercased
    and including the port. `origins` are full scheme://host:port strings.
    """

    hosts: frozenset[str]
    origins: frozenset[str]

    @classmethod
    def build(cls, addresses: list[str], port: int, *, scheme: str = "https") -> Guard:
        """From the addresses actually bound, plus the loopback names."""
        hosts, origins = set(), set()
        for address in [*addresses, "localhost", "127.0.0.1"]:
            authority = f"[{address}]:{port}" if ":" in address else f"{address}:{port}"
            hosts.add(authority.lower())
            origins.add(f"{scheme}://{authority}".lower())
        return cls(frozenset(hosts), frozenset(origins))

    def refuse(self, host: str | None, origin: str | None,
               referer: str | None = None) -> str | None:
        """The reason to reject this request, or None to let it through.

        A returned string is for the server's own 403 body. It names the header
        at fault and nothing else — never the allowlist, which would tell an
        attacker exactly what to send.
        """
        if not host:
            return "No Host header"
        if host.strip().lower() not in self.hosts:
            return "Host not served here"

        # Origin is present on anything a script initiated and on every
        # non-GET. Absent on a plain navigation, which is legitimate.
        if origin and origin.lower() != "null":
            if origin.strip().lower() not in self.origins:
                return "Origin not allowed"
            return None

        if referer:
            parts = urlsplit(referer.strip())
            if (parts.scheme and parts.netloc
                    and f"{parts.scheme}://{parts.netloc}".lower() not in self.origins):
                return "Referer not allowed"
        return None
