"""Which address to hand out, when the machine has several.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

A laptop on a desk routinely has four or five IPv4 addresses: Wi-Fi, a dock's
ethernet, a VPN tunnel, a Docker bridge, and something a virtual machine
installed. Exactly one of them is the one the phone in your hand can reach, and
which one that is depends on facts this process cannot see — whether the VPN
carries local traffic, whether the phone is on the guest network, whether the
dock is plugged in.

So this module does not choose. It finds every candidate, says what kind each
appears to be and which one currently holds the default route, and leaves the
choosing to the person looking at the screen. Guessing and being wrong produces
a QR that silently fails to connect, which is the worst outcome available: it
looks like the software is broken rather than like the address is wrong.
"""

from __future__ import annotations

import ipaddress
import platform
import re
import socket
import subprocess
from dataclasses import dataclass

#: Name prefixes that say what an interface is for. Ordered: the first match
#: wins, so the more specific prefixes come first.
_KINDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("utun", "tun", "tap", "ppp", "wg", "ipsec", "nordlynx", "tailscale"), "VPN"),
    (("docker", "br-", "veth", "virbr", "vboxnet", "vmnet", "lxc", "cni", "flannel"),
     "virtual"),
    (("wl", "wifi", "wlan", "ath"), "Wi-Fi"),
    (("en", "eth", "eno", "enp", "ens", "em"), "Ethernet"),
)


@dataclass(frozen=True)
class Interface:
    """One address this machine could be reached on."""

    name: str
    address: str
    kind: str
    default_route: bool

    @property
    def label(self) -> str:
        """What to print above this candidate's QR."""
        suffix = "  (default route)" if self.default_route else ""
        return f"{self.kind} — {self.name} — {self.address}{suffix}"


def _classify(name: str) -> str:
    lowered = name.lower()
    for prefixes, kind in _KINDS:
        if lowered.startswith(prefixes):
            return kind
    return "Unknown"


def default_address() -> str | None:
    """The source address the kernel would use to leave this machine.

    A UDP socket is connected but nothing is sent — connect() on UDP only sets
    the peer and asks the routing table which local address that implies. No
    packet leaves, no name is resolved, and it works with no network at all
    (it simply fails, and returns None).
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))          # TEST-NET-1: reserved, unroutable
        return str(probe.getsockname()[0])
    except OSError:
        return None
    finally:
        probe.close()


def _run(command: list[str]) -> str:
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=5.0,
                              check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _hardware_ports() -> dict[str, str]:
    """macOS device -> the name in Network preferences ("Wi-Fi", "Ethernet").

    Worth the subprocess: on a Mac `en0` is Wi-Fi on a laptop and Ethernet on a
    desktop, so the prefix table is a coin flip and this is the answer.
    """
    if platform.system() != "Darwin":
        return {}
    ports: dict[str, str] = {}
    current = None
    for line in _run(["networksetup", "-listallhardwareports"]).splitlines():
        if line.startswith("Hardware Port:"):
            current = line.split(":", 1)[1].strip()
        elif line.startswith("Device:") and current:
            ports[line.split(":", 1)[1].strip()] = current
            current = None
    return ports


def _from_ifconfig() -> list[tuple[str, str]]:
    text = _run(["ifconfig", "-a"]) or _run(["/sbin/ifconfig", "-a"])
    out, name = [], ""
    for line in text.splitlines():
        if line and not line[0].isspace():
            name = line.split(":", 1)[0].strip()
        elif name:
            found = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)", line)
            if found:
                out.append((name, found.group(1)))
    return out


def _from_ip() -> list[tuple[str, str]]:
    out = []
    for line in _run(["ip", "-o", "-4", "addr", "show"]).splitlines():
        found = re.search(r"^\d+:\s+(\S+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)", line)
        if found:
            out.append((found.group(1), found.group(2)))
    return out


def _from_hostname() -> list[tuple[str, str]]:
    """Last resort, and the usual path on Windows: no names, just addresses."""
    try:
        info = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    return [(f"interface {i + 1}", str(entry[4][0])) for i, entry in enumerate(
        dict.fromkeys(info))]


def _usable(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    # Loopback is already served and is not a LAN address; link-local means
    # DHCP failed and nothing else is on that network anyway.
    return not (parsed.is_loopback or parsed.is_link_local or parsed.is_unspecified)


def candidates() -> list[Interface]:
    """Every address a device on the network might reach this machine at.

    Ordered so the likeliest is first: the default route, then Wi-Fi and
    ethernet, then VPNs, then virtual bridges — which are almost never right
    but are shown because "almost never" is not "never", and because a Docker
    bridge that is silently omitted is a bug report nobody can reproduce.
    """
    found = _from_ip() or _from_ifconfig() or _from_hostname()
    ports = _hardware_ports()
    default = default_address()

    seen: set[tuple[str, str]] = set()
    out: list[Interface] = []
    for name, address in found:
        if not _usable(address) or (name, address) in seen:
            continue
        seen.add((name, address))
        kind = ports.get(name) or _classify(name)
        out.append(Interface(name=name, address=address, kind=kind,
                             default_route=address == default))

    rank = {"Wi-Fi": 1, "Ethernet": 2, "VPN": 3, "Unknown": 4, "virtual": 5}
    out.sort(key=lambda i: (not i.default_route, rank.get(i.kind, 4), i.name))
    return out
