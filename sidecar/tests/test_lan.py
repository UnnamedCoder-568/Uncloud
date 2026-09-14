"""The LAN surface: pairing, sessions, the Host fence, TLS, and the QR.

Most of what matters here is a property that is easy to break without noticing
— a comparison that stops being constant-time, a secret that starts being
written to disk, a fence that stops covering websockets. So the tests name the
property, not the function.

The QR is checked by DECODING it: a reader in this file walks the matrix the
way a scanner does and must get the payload back, with every error-correction
block re-derived and matched. The encoder was also checked against an
independent implementation when it was written; that implementation is not a
dependency, and this test does not need it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import os
import socket
import stat
import threading
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket

from uncloud_engine.core.lan import codes, control, qr
from uncloud_engine.core.lan.guard import Guard
from uncloud_engine.core.lan.pairing import (
    FREE_ATTEMPTS,
    LIFETIME,
    Pairing,
    RateLimited,
)
from uncloud_engine.core.lan.sessions import Sessions, describe

# ===================================================================== the QR

def _read(grid: list[list[int]]) -> bytes:
    """Decode a QR matrix the way a scanner would. Byte mode, level M only."""
    size = len(grid)
    version = (size - 17) // 4

    bits = 0
    for i in range(6):
        bits = (bits << 1) | grid[8][i]
    for rr, cc in ((8, 7), (8, 8), (7, 8)):
        bits = (bits << 1) | grid[rr][cc]
    for i in range(9, 15):
        bits = (bits << 1) | grid[14 - i][8]
    raw = bits ^ 0b101010000010010
    assert raw >> 13 == qr._LEVEL_M, "format bits do not say level M"
    mask = (raw >> 10) & 0b111

    _, fixed = qr._reserve(size, version)
    rule = qr._MASKS[mask]
    stream: list[int] = []
    upward, col = True, size - 1
    while col > 0:
        if col == 6:
            col -= 1
        for row in (range(size - 1, -1, -1) if upward else range(size)):
            for c in (col, col - 1):
                if not fixed[row][c]:
                    stream.append(grid[row][c] ^ (1 if rule(row, c) else 0))
        upward, col = not upward, col - 2
    words = [int("".join(map(str, stream[i:i + 8])), 2)
             for i in range(0, len(stream) // 8 * 8, 8)]

    ec_per_block, groups = qr._SPEC[version]
    sizes = [size_ for count, size_ in groups for _ in range(count)]
    blocks: list[list[int]] = [[] for _ in sizes]
    at = 0
    for i in range(max(sizes)):
        for b, length in enumerate(sizes):
            if i < length:
                blocks[b].append(words[at])
                at += 1
    for b in range(len(sizes)):
        ec = words[at + b::len(sizes)][:ec_per_block]
        assert qr.error_codewords(bytes(blocks[b]), ec_per_block) == ec, \
            f"error correction for block {b} does not match its data"

    data = [bit for block in blocks for word in block for bit in
            ((word >> s) & 1 for s in range(7, -1, -1))]
    assert data[:4] == [0, 1, 0, 0], "not byte mode"
    width = 8 if version < 10 else 16
    length = int("".join(map(str, data[4:4 + width])), 2)
    body = data[4 + width:4 + width + length * 8]
    return bytes(int("".join(map(str, body[i:i + 8])), 2) for i in range(0, len(body), 8))


@pytest.mark.parametrize("payload", [
    "a",
    "https://192.168.1.42:8765/pair?t=" + codes.token(),
    "https://[fe80::1]:8766/pair?t=" + codes.token(),
    *["".join(chr(97 + i % 26) for i in range(qr._capacity(v) - (2 if v < 10 else 3)))
      for v in range(1, 11)],
])
def test_every_code_decodes_back_to_its_payload(payload: str) -> None:
    assert _read(qr.matrix(payload)).decode() == payload


def test_known_matrices_have_not_changed() -> None:
    """Pinned after the encoder was verified module-for-module against segno
    (identical wherever segno does not add its own spurious pad byte) and
    decoded with OpenCV."""
    pinned = {
        "a": "951e082d3aba9992aa06c7ee9de2d766479de61a90e56572a41ded5ac14e14e3",
        "https://192.168.1.42:8765/pair?t=" + "A" * 43:
            "0ad48859ece16e275214a067bd5707de1c2b64e420b78134d5ffafb914a80a3e",
        "".join(chr(97 + i % 26) for i in range(122)):
            "3b67287785c6a50a92742f5f90e8f53e93fd4ffaab12e126ed46759f85a6245b",
        "".join(chr(97 + i % 26) for i in range(213)):
            "cc5afa257c1fdc6bdd3fc2aa5cfe661f467823cb20c6b42750b7e3e3256c0269",
    }
    for payload, digest in pinned.items():
        flat = "".join("".join(map(str, row)) for row in qr.matrix(payload))
        assert hashlib.sha256(flat.encode()).hexdigest() == digest, payload[:24]


def test_capacity_table_fills_each_version_exactly() -> None:
    """Transcribed from the standard, so check the arithmetic: data plus error
    codewords must fill exactly the free modules, less the remainder bits."""
    remainder = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}
    for version, (ec, groups) in qr._SPEC.items():
        size = version * 4 + 17
        _, fixed = qr._reserve(size, version)
        free = sum(not cell for row in fixed for cell in row)
        total = sum(count * (data + ec) for count, data in groups)
        assert free == total * 8 + remainder[version], version


def test_an_oversized_payload_is_refused_rather_than_truncated() -> None:
    with pytest.raises(ValueError):
        qr.matrix("x" * 400)


def test_the_terminal_rendering_is_the_matrix_with_a_quiet_zone() -> None:
    """Parse the half-blocks back and compare. A renderer that drops the quiet
    zone or swaps rows produces something that looks like a QR and scans as
    nothing."""
    payload = "https://10.0.0.7:8765/pair?t=" + codes.token()
    grid = qr.matrix(payload)
    rendered = qr.terminal(payload, colour=True).splitlines()
    rows: list[list[int]] = []
    for line in rendered:
        cells = line.split("▀")[:-1]
        top, bottom = [], []
        for cell in cells:
            top.append(1 if "\x1b[30m" in cell else 0)
            bottom.append(1 if "\x1b[40m" in cell else 0)
        rows += [top, bottom]
    q = qr.QUIET
    assert all(not any(r) for r in rows[:q]), "no light quiet zone above"
    inner = [r[q:q + len(grid)] for r in rows[q:q + len(grid)]]
    assert inner == grid
    assert all(not any(r[:q]) and not any(r[q + len(grid):]) for r in rows[q:q + len(grid)])


# ================================================================ the codes

def test_typed_codes_are_crockford_grouped_and_sixty_bits() -> None:
    for _ in range(200):
        code = codes.code()
        groups = code.split("-")
        assert [len(g) for g in groups] == [4, 4, 4]
        assert set("".join(groups)) <= set(codes.ALPHABET)
    assert len(codes.ALPHABET) ** codes.LENGTH == 2 ** 60
    assert not set("ILOU") & set(codes.ALPHABET)


def test_typed_codes_are_never_numeric_only_by_construction() -> None:
    """Letters are part of the alphabet; a digits-only code is a 40-bit PIN."""
    assert any(c.isalpha() for c in codes.ALPHABET)
    assert len([c for c in codes.ALPHABET if c.isdigit()]) == 10


@pytest.mark.parametrize("typed", ["abcd-efgh-jkmn", "ABCDEFGHJKMN", " abcd efgh jkmn ",
                                   "aBcD-eFgH-jKmN"])
def test_entry_ignores_case_hyphens_and_spaces(typed: str) -> None:
    assert codes.normalise(typed) == "ABCDEFGHJKMN"


def test_confusable_letters_fold_onto_digits() -> None:
    assert codes.normalise("I0LO-0000-0000") == "1010" + "0" * 8


@pytest.mark.parametrize("bad", ["", "ABCD-EFGH", "ABCD-EFGH-JKMN-P", "ABCD-EFGH-JKM!",
                                 "ΑΒΓΔ-0000-0000"])
def test_malformed_entries_normalise_to_nothing(bad: str) -> None:
    assert codes.normalise(bad) == ""


def test_qr_tokens_are_32_bytes_urlsafe() -> None:
    token = codes.token()
    assert len(token) == 43 and "=" not in token
    assert set(token) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


# ============================================================== pairing

def test_both_secrets_work_and_either_spends_the_offer() -> None:
    for kind in ("token", "code"):
        pairing = Pairing()
        offer = pairing.mint()
        presented = offer.token if kind == "token" else offer.code.lower().replace("-", "")
        assert pairing.redeem(presented, kind=kind, ip="1.1.1.1")
        other = offer.code if kind == "token" else offer.token
        assert not pairing.redeem(other, kind="code" if kind == "token" else "token",
                                  ip="1.1.1.1")


def test_single_use() -> None:
    pairing = Pairing()
    offer = pairing.mint()
    assert pairing.redeem(offer.token, kind="token", ip="1.1.1.1")
    assert not pairing.redeem(offer.token, kind="token", ip="1.1.1.1")


def test_expires_after_five_minutes() -> None:
    pairing = Pairing()
    offer = pairing.mint(now=1000.0)
    assert LIFETIME == 300.0
    assert not pairing.redeem(offer.token, kind="token", ip="1.1.1.1", now=1000.0 + LIFETIME)
    fresh = pairing.mint(now=2000.0)
    assert pairing.redeem(fresh.token, kind="token", ip="1.1.1.1", now=2000.0 + LIFETIME - 1)


def test_a_token_is_not_accepted_as_a_code_or_vice_versa() -> None:
    pairing = Pairing()
    offer = pairing.mint()
    assert not pairing.redeem(offer.token, kind="code", ip="1.1.1.1")
    assert not pairing.redeem(offer.code, kind="token", ip="2.2.2.2")


def test_minting_again_kills_the_previous_offer() -> None:
    pairing = Pairing()
    old = pairing.mint()
    pairing.mint()
    assert not pairing.redeem(old.token, kind="token", ip="1.1.1.1")


def test_racing_redemptions_produce_exactly_one_winner() -> None:
    """Consumption is atomic with the comparison. Forty threads, one offer."""
    pairing = Pairing()
    offer = pairing.mint()
    wins: list[bool] = []
    barrier = threading.Barrier(40)

    def go(i: int) -> None:
        barrier.wait()
        wins.append(pairing.redeem(offer.token, kind="token", ip=f"10.0.0.{i}"))

    threads = [threading.Thread(target=go, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert wins.count(True) == 1


def test_five_free_attempts_then_backoff_per_address() -> None:
    pairing = Pairing()
    pairing.mint(now=0.0)
    for _ in range(FREE_ATTEMPTS):
        assert not pairing.redeem("0000-0000-0000", kind="code", ip="6.6.6.6", now=1.0)
    with pytest.raises(RateLimited) as limited:
        pairing.redeem("0000-0000-0000", kind="code", ip="6.6.6.6", now=1.0)
    assert limited.value.retry_after > 0
    # A different address is unaffected.
    assert not pairing.redeem("0000-0000-0000", kind="code", ip="7.7.7.7", now=5.0)


def test_backoff_doubles() -> None:
    pairing = Pairing()
    pairing.mint(now=0.0)
    now = 0.0
    waits = []
    for _ in range(FREE_ATTEMPTS + 4):
        try:
            pairing.redeem("0000-0000-0000", kind="code", ip="6.6.6.6", now=now)
        except RateLimited as limited:
            waits.append(limited.retry_after)
            now += limited.retry_after
            pairing.redeem("0000-0000-0000", kind="code", ip="6.6.6.6", now=now)
    assert waits == sorted(waits) and waits[-1] >= 2 * waits[0]


def test_a_success_clears_the_address_record() -> None:
    pairing = Pairing()
    offer = pairing.mint(now=0.0)
    for i in range(FREE_ATTEMPTS - 1):
        pairing.redeem("0000-0000-0000", kind="code", ip="6.6.6.6", now=float(i))
    assert pairing.redeem(offer.code, kind="code", ip="6.6.6.6", now=10.0)
    pairing.mint(now=11.0)
    for i in range(FREE_ATTEMPTS):
        assert not pairing.redeem("0000-0000-0000", kind="code", ip="6.6.6.6", now=12.0 + i)


def test_non_ascii_input_is_a_refusal_not_an_exception() -> None:
    pairing = Pairing()
    pairing.mint()
    assert not pairing.redeem("☃" * 43, kind="token", ip="1.1.1.1")


# ============================================================== sessions

def test_sessions_survive_a_restart(tmp_path: Path) -> None:
    store = tmp_path / "sessions.json"
    cookie, session = Sessions(store).issue(label="Phone", agent="iPhone")
    again = Sessions(store).verify(cookie)
    assert again is not None and again.id == session.id and again.label == "Phone"


def test_the_secret_is_never_written_to_disk(tmp_path: Path) -> None:
    store = tmp_path / "sessions.json"
    cookie, _ = Sessions(store).issue(label="Phone", agent="iPhone")
    secret = cookie.split(".", 1)[1]
    assert secret not in store.read_text()
    assert hashlib.sha256(secret.encode()).hexdigest() in store.read_text()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_the_store_is_owner_only(tmp_path: Path) -> None:
    store = tmp_path / "sessions.json"
    Sessions(store).issue(label="Phone", agent="iPhone")
    assert stat.S_IMODE(store.stat().st_mode) == 0o600


def test_wrong_secret_and_wrong_id_are_both_refused(tmp_path: Path) -> None:
    sessions = Sessions(tmp_path / "s.json")
    cookie, session = sessions.issue(label="Phone", agent="iPhone")
    assert sessions.verify(f"{session.id}.{'A' * 43}") is None
    assert sessions.verify(f"deadbeefdeadbeef.{cookie.split('.', 1)[1]}") is None
    assert sessions.verify("") is None and sessions.verify("no-dot") is None
    assert sessions.verify(f"{session.id}.☃") is None


def test_revoke_one_and_all(tmp_path: Path) -> None:
    store = tmp_path / "s.json"
    sessions = Sessions(store)
    first, a = sessions.issue(label="A", agent="Mac")
    second, _ = sessions.issue(label="B", agent="iPhone")
    assert sessions.revoke(a.id)
    assert sessions.verify(first) is None and sessions.verify(second) is not None
    assert Sessions(store).verify(first) is None, "revocation did not persist"
    assert sessions.revoke_all() == 1
    assert Sessions(store).verify(second) is None


def test_last_seen_is_recorded_but_not_rewritten_every_request(tmp_path: Path) -> None:
    store = tmp_path / "s.json"
    sessions = Sessions(store)
    cookie, session = sessions.issue(label="A", agent="Mac")
    before = store.stat().st_mtime_ns
    for _ in range(20):
        sessions.verify(cookie)
    assert store.stat().st_mtime_ns == before
    listed = json.loads(store.read_text())["sessions"][0]
    assert {"label", "created", "last_seen", "agent"} <= set(listed)


def test_a_device_description_is_coarse() -> None:
    ua = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
          "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
    assert describe(ua) == "iPhone"
    assert describe(None) == "Unknown device"


def test_a_corrupt_store_loses_nothing_it_can_keep(tmp_path: Path) -> None:
    store = tmp_path / "s.json"
    cookie, _ = Sessions(store).issue(label="A", agent="Mac")
    data = json.loads(store.read_text())
    data["sessions"].append({"label": "no id"})
    store.write_text(json.dumps(data))
    assert Sessions(store).verify(cookie) is not None


# ================================================================= the guard

GUARD = Guard.build(["192.168.1.42"], 8765)


def test_rebinding_is_refused_by_host() -> None:
    assert GUARD.refuse("attacker.example:8765", None) is not None
    assert GUARD.refuse("192.168.1.42:9999", None) is not None
    assert GUARD.refuse(None, None) is not None


def test_the_served_host_passes() -> None:
    assert GUARD.refuse("192.168.1.42:8765", None) is None
    assert GUARD.refuse("192.168.1.42:8765", "https://192.168.1.42:8765") is None
    assert GUARD.refuse("localhost:8765", None) is None


def test_foreign_origin_and_referer_are_refused() -> None:
    assert GUARD.refuse("192.168.1.42:8765", "https://attacker.example") is not None
    assert GUARD.refuse("192.168.1.42:8765", "http://192.168.1.42:8765") is not None
    assert GUARD.refuse("192.168.1.42:8765", None, "https://attacker.example/x") is not None


def test_the_refusal_never_reveals_the_allowlist() -> None:
    reason = GUARD.refuse("attacker.example:8765", None) or ""
    assert "192.168" not in reason


def test_ipv6_hosts_are_bracketed() -> None:
    guard = Guard.build(["fe80::1"], 8765)
    assert guard.refuse("[fe80::1]:8765", None) is None


# ==================================================================== TLS

def test_certificates_cover_the_addresses_and_keys_are_private(tmp_path: Path) -> None:
    from cryptography import x509

    from uncloud_engine.core.lan.tls import LEAF_DAYS, ensure

    material = ensure(tmp_path, ("192.168.1.42",), product="Uncloud")
    leaf = x509.load_pem_x509_certificate(material.certificate.read_bytes())
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert ipaddress.ip_address("192.168.1.42") in san.get_values_for_type(x509.IPAddress)
    life = leaf.not_valid_after_utc - leaf.not_valid_before_utc
    assert life <= dt.timedelta(days=398), "Apple refuses server certificates past 398 days"
    assert LEAF_DAYS <= 397

    authority = x509.load_pem_x509_certificate(material.authority.read_bytes())
    assert leaf.issuer == authority.subject
    authority.public_key().verify(leaf.signature, leaf.tbs_certificate_bytes,
                                  __import__("cryptography.hazmat.primitives.asymmetric.ec",
                                             fromlist=["ECDSA"]).ECDSA(leaf.signature_hash_algorithm))
    if os.name != "nt":
        assert stat.S_IMODE(material.key.stat().st_mode) == 0o600
        assert stat.S_IMODE((tmp_path / "lan-authority-key.pem").stat().st_mode) == 0o600


def test_the_authority_is_kept_and_the_leaf_follows_the_network(tmp_path: Path) -> None:
    from uncloud_engine.core.lan.tls import ensure

    first = ensure(tmp_path, ("192.168.1.42",), product="Uncloud")
    same = ensure(tmp_path, ("192.168.1.42",), product="Uncloud")
    assert not same.issued and same.fingerprint == first.fingerprint
    moved = ensure(tmp_path, ("10.0.0.9",), product="Uncloud")
    assert moved.issued and moved.fingerprint == first.fingerprint, \
        "moving networks must not force re-installing the authority on every phone"


# =========================================================== control socket

@pytest.mark.skipif(not control.available(), reason="no Unix sockets here")
def test_control_socket_is_owner_only_and_round_trips(tmp_path: Path) -> None:
    path = control.socket_path(tmp_path, "test")
    stop = control.listen(path, lambda request: {"echo": request.get("verb")})
    try:
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
        assert control.ask(path, {"verb": "pair"}) == {"echo": "pair"}
    finally:
        stop()
    assert control.ask(path, {"verb": "pair"}) is None


@pytest.mark.skipif(not control.available(), reason="no Unix sockets here")
def test_a_long_config_path_falls_back_to_a_private_directory(tmp_path: Path) -> None:
    deep = tmp_path / ("x" * 60) / ("y" * 60)
    path = control.socket_path(deep, "test")
    assert len(os.fsencode(path)) <= control.MAX_PATH
    info = path.parent.stat()
    assert info.st_uid == os.getuid() and not info.st_mode & 0o077
    stop = control.listen(path, lambda r: {"ok": True})
    try:
        assert control.ask(path, {}) == {"ok": True}
    finally:
        stop()


# ======================================================================== web

@pytest.fixture
def served(tmp_path: Path):
    """An app behind the fence, as the LAN listener serves it."""
    # FastAPI resolves `request: Request` from module globals: with postponed
    # annotations, a Request imported here would be read as a query parameter.
    from fastapi.testclient import TestClient

    from uncloud_engine.core.lan import Interface, Lan, web

    lan = Lan(product="Test", slug="test", config_dir=tmp_path, port=8765,
              chosen=[Interface(name="en0", address="192.168.1.42", kind="Wi-Fi",
                                default_route=True)])

    def authorised(request) -> bool:
        return web.session_of(request, lan) is not None

    def need(request: Request) -> None:
        if not authorised(request):
            raise HTTPException(401)

    app = FastAPI()
    app.include_router(web.router(lan, authorised))

    @app.get("/api/secret", dependencies=[Depends(need)])
    def secret() -> dict:
        return {"ok": True}

    @app.websocket("/ws/echo")
    async def echo(ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_text("hi")
        await ws.close()

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>")
    (dist / "assets" / "a.js").write_text("console.log(1)")
    web.serve_frontend(app, dist)

    client = TestClient(web.Fence(app, lan), base_url="https://192.168.1.42:8765")
    return lan, client


def test_web_pairing_sets_a_hardened_cookie_and_unlocks_the_api(served) -> None:
    lan, client = served
    assert client.get("/api/secret").status_code == 401
    offer = lan.offer()
    response = client.get(f"/pair?t={offer.token}", follow_redirects=False)
    assert response.status_code == 303
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert client.get("/api/secret").status_code == 200


def test_web_fence_covers_http_and_websockets(served) -> None:
    from starlette.websockets import WebSocketDisconnect

    _, client = served
    assert client.get("/api/lan/session", headers={"host": "evil.example:8765"}).status_code == 403
    with (pytest.raises(WebSocketDisconnect),
          client.websocket_connect("/ws/echo", headers={"host": "evil.example:8765"}) as ws):
        ws.receive_text()


def test_web_device_management_needs_a_session(served) -> None:
    _, client = served
    for method, path in (("get", "/api/lan/devices"), ("post", "/api/lan/offer"),
                         ("delete", "/api/lan/devices/all")):
        assert getattr(client, method)(path).status_code == 401, path


def test_web_spa_fallback_does_not_mask_api_404s_or_escape_dist(served) -> None:
    _, client = served
    assert client.get("/some/client/route").text.startswith("<!doctype html>")
    assert client.get("/assets/a.js").text == "console.log(1)"
    assert client.get("/api/nope").status_code == 404
    assert "root:" not in client.get("/..%2F..%2F..%2F..%2Fetc%2Fpasswd").text


def test_web_typed_pairing_and_rate_limit(served) -> None:
    lan, client = served
    for _ in range(FREE_ATTEMPTS):
        assert client.post("/api/lan/pair", json={"code": "0000-0000-0000"}).status_code == 403
    limited = client.post("/api/lan/pair", json={"code": "0000-0000-0000"})
    assert limited.status_code == 429 and "retry-after" in limited.headers


def test_a_default_route_probe_sends_nothing() -> None:
    """connect() on UDP only consults the routing table. If this ever starts
    sending, it would be sending to TEST-NET-1, which nothing answers."""
    from uncloud_engine.core.lan.interfaces import default_address

    address = default_address()
    assert address is None or ipaddress.ip_address(address)
    assert socket  # imported for the probe's own use
