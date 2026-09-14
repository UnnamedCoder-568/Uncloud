"""A certificate for an IP address nobody can buy one for.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

The pairing secret crosses the network. That settles the question of whether
this is worth doing: plain HTTP would put a working credential on the air in
the clear, where every other device on the café Wi-Fi can read it. So the LAN
listener is HTTPS, always.

No public authority will issue for 192.168.1.x, so the machine issues its own:
a small local authority, created once and kept here, which signs a certificate
for whatever addresses this machine currently answers on. The authority
certificate is the one-time trust step — install it on the phone and every
later pairing is silent. Until it is installed the browser shows a warning, and
the connection is still encrypted, which is the part that matters for the
secret in the URL.

The private keys never leave this directory and are written 0600. The authority
certificate is public by nature and readable — it is what you send to the
phone.

Two deliberate choices about validity. The leaf lasts 397 days because Apple
platforms refuse to trust a server certificate valid for longer, and a
certificate iOS will not accept is not a certificate. The authority lasts ten
years, because re-installing it on every device once a year is how a security
step becomes a thing people click past.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

#: Apple will not trust a server certificate valid for longer than 398 days.
LEAF_DAYS = 397
AUTHORITY_YEARS = 10

#: Reissued this far before expiry, so a long-running install never serves an
#: expired certificate.
RENEW_WITHIN_DAYS = 30


@dataclass(frozen=True)
class Material:
    """Where the files are, and what to tell the person installing them."""

    authority: Path
    certificate: Path
    key: Path
    fingerprint: str
    addresses: tuple[str, ...]
    issued: bool


def _write_private(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(pem)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _read_private(path: Path) -> ec.EllipticCurvePrivateKey | None:
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError):
        return None
    return key if isinstance(key, ec.EllipticCurvePrivateKey) else None


def _read_certificate(path: Path) -> x509.Certificate | None:
    try:
        return x509.load_pem_x509_certificate(path.read_bytes())
    except (OSError, ValueError):
        return None


def _names(addresses: tuple[str, ...]) -> list[x509.GeneralName]:
    out: list[x509.GeneralName] = [x509.DNSName("localhost")]
    for address in addresses:
        try:
            out.append(x509.IPAddress(ipaddress.ip_address(address)))
        except ValueError:
            out.append(x509.DNSName(address))
    if not any(isinstance(n, x509.IPAddress) and n.value.is_loopback for n in out):
        out.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
    return out


def _authority(directory: Path, product: str) -> tuple[x509.Certificate,
                                                       ec.EllipticCurvePrivateKey, bool]:
    certificate_path = directory / "lan-authority.pem"
    key_path = directory / "lan-authority-key.pem"

    existing = _read_certificate(certificate_path)
    key = _read_private(key_path)
    if existing is not None and key is not None:
        soon = dt.datetime.now(dt.UTC) + dt.timedelta(days=RENEW_WITHIN_DAYS)
        if existing.not_valid_after_utc > soon:
            return existing, key, False

    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"{product} local authority"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, product),
    ])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))     # tolerate clock skew
        .not_valid_after(now + dt.timedelta(days=365 * AUTHORITY_YEARS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=False, content_commitment=False, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=True,
            crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                       critical=False)
        .sign(key, hashes.SHA256())
    )
    directory.mkdir(parents=True, exist_ok=True)
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    _write_private(key_path, key)
    return certificate, key, True


def ensure(directory: Path, addresses: tuple[str, ...], *, product: str) -> Material:
    """Certificates covering `addresses`, making them if they are missing or stale.

    Reissues when the address set changes — a laptop that moved networks has a
    new address, and a certificate that does not name it produces a warning
    that teaches people to ignore warnings.
    """
    authority, authority_key, made_authority = _authority(directory, product)
    certificate_path = directory / "lan.pem"
    key_path = directory / "lan-key.pem"

    wanted = tuple(sorted(set(addresses)))
    existing = _read_certificate(certificate_path)
    key = _read_private(key_path)
    fresh = True
    if existing is not None and key is not None and not made_authority:
        try:
            san = existing.extensions.get_extension_for_class(
                x509.SubjectAlternativeName).value
            covered = {str(n.value) for n in san}
        except x509.ExtensionNotFound:
            covered = set()
        soon = dt.datetime.now(dt.UTC) + dt.timedelta(days=RENEW_WITHIN_DAYS)
        fresh = not (set(wanted) <= covered and existing.not_valid_after_utc > soon)

    if fresh:
        key = ec.generate_private_key(ec.SECP256R1())
        now = dt.datetime.now(dt.UTC)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([
                x509.NameAttribute(NameOID.COMMON_NAME, f"{product} on this network")]))
            .issuer_name(authority.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=LEAF_DAYS))
            .add_extension(x509.SubjectAlternativeName(_names(wanted)), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                           critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
                           critical=False)
            .add_extension(x509.KeyUsage(
                digital_signature=True, content_commitment=False,
                key_encipherment=False, data_encipherment=False, key_agreement=False,
                key_cert_sign=False, crl_sign=False, encipher_only=False,
                decipher_only=False), critical=True)
            .sign(authority_key, hashes.SHA256())
        )
        certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        _write_private(key_path, key)

    digest = authority.fingerprint(hashes.SHA256()).hex().upper()
    return Material(
        authority=(directory / "lan-authority.pem"),
        certificate=certificate_path,
        key=key_path,
        fingerprint=":".join(digest[i:i + 2] for i in range(0, len(digest), 2)),
        addresses=wanted,
        issued=fresh or made_authority,
    )
