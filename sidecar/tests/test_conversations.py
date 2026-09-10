"""Conversations survive a restart, and nothing else can read them.

The failure this guards against is the one that loses work: a conversation that
saved, and then could not be opened. So the tests care less about the happy
path than about what happens when a file is truncated, altered, written under a
different key, or interrupted halfway through.
"""

from __future__ import annotations

import secrets

import pytest
from cryptography.exceptions import InvalidTag

from uncloud_engine import conversations as convo
from uncloud_engine import vault as vault_module


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """A fresh directory and a fresh key per test, touching neither the real
    conversations nor the real keychain."""
    monkeypatch.setattr(convo, "DIR", tmp_path / "conversations")
    key = secrets.token_bytes(32)

    class FixedVault:
        is_secure = True
        backend = "test"

        def key(self) -> bytes:
            return key

    monkeypatch.setattr(convo, "vault", FixedVault())
    return tmp_path


def _saved(text: str = "how do I crop an image?") -> convo.Conversation:
    c = convo.create([{"role": "user", "content": text},
                      {"role": "assistant", "content": "Use the Design tab."}])
    return convo.save(c)


# ------------------------------------------------------------- round trip
def test_a_conversation_survives_being_closed_and_reopened() -> None:
    saved = _saved()
    loaded = convo.load(saved.id)
    assert loaded is not None
    assert loaded.messages == saved.messages
    assert loaded.title == saved.title


def test_the_title_comes_from_what_the_user_asked() -> None:
    c = _saved("why is the export blank?")
    assert c.title == "why is the export blank?"


def test_a_long_first_line_is_shortened_rather_than_stored_whole() -> None:
    c = _saved("x" * 400)
    assert len(c.title) <= convo.TITLE_CHARS + 1
    assert c.title.endswith("…")


def test_a_conversation_with_no_user_turn_still_gets_a_name() -> None:
    c = convo.create([{"role": "assistant", "content": "hello"}])
    assert convo.save(c).title == "New conversation"


def test_listing_is_newest_first_and_carries_no_message_bodies() -> None:
    convo.save(convo.create([{"role": "user", "content": "first"}]))
    second = convo.save(convo.create([{"role": "user", "content": "second"}]))
    result = convo.listing()
    assert [c["title"] for c in result.conversations][0] == second.title
    assert all("messages" not in c or isinstance(c["messages"], int)
               for c in result.conversations)


def test_delete_removes_it_and_says_whether_it_was_there() -> None:
    c = _saved()
    assert convo.delete(c.id) is True
    assert convo.load(c.id) is None
    assert convo.delete(c.id) is False


# ---------------------------------------------------------------- at rest
def test_the_file_does_not_contain_the_conversation_in_the_clear() -> None:
    c = _saved("my bank password is hunter2")
    raw = (convo.DIR / f"{c.id}.enc").read_bytes()
    assert b"hunter2" not in raw
    assert b"bank" not in raw
    assert b"assistant" not in raw


def test_every_write_uses_a_fresh_nonce() -> None:
    """Reusing a nonce under one key is the one thing GCM cannot survive."""
    c = _saved()
    first = (convo.DIR / f"{c.id}.enc").read_bytes()
    c.messages.append({"role": "user", "content": "and now?"})
    convo.save(c)
    second = (convo.DIR / f"{c.id}.enc").read_bytes()
    start, end = len(convo.MAGIC), len(convo.MAGIC) + convo.NONCE_BYTES
    assert first[start:end] != second[start:end]


def test_a_file_written_under_another_key_will_not_open(monkeypatch) -> None:
    c = _saved()
    other = secrets.token_bytes(32)

    class OtherVault:
        is_secure = True
        backend = "test"

        def key(self) -> bytes:
            return other

    monkeypatch.setattr(convo, "vault", OtherVault())
    # Named rather than blind: a test that passes because an unrelated import
    # broke is a test that has stopped checking anything.
    with pytest.raises((InvalidTag, ValueError)):
        convo.load(c.id)


def test_an_altered_file_is_refused_rather_than_half_read() -> None:
    """Authentication is the point of GCM: tampering must fail, not decode
    into plausible text that gets shown as though the user wrote it."""
    c = _saved()
    path = convo.DIR / f"{c.id}.enc"
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0x01
    path.write_bytes(bytes(raw))
    with pytest.raises((InvalidTag, ValueError)):
        convo.load(c.id)


def test_a_file_from_a_different_format_is_refused() -> None:
    path = convo.DIR
    path.mkdir(parents=True, exist_ok=True)
    (path / "abcdef01.enc").write_bytes(b"NOT-UNCLOUD" + b"\x00" * 40)
    with pytest.raises(ValueError):
        convo.load("abcdef01")


def test_one_unreadable_file_does_not_hide_the_others() -> None:
    good = _saved()
    (convo.DIR / "deadbeef.enc").write_bytes(b"rubbish")
    result = convo.listing()
    assert [c["id"] for c in result.conversations] == [good.id]
    assert result.unreadable == 1


# ------------------------------------------------------------ interruption
def test_an_interrupted_write_leaves_the_previous_version_intact(monkeypatch) -> None:
    """Saved after every reply, so a badly timed quit is a real event. A
    truncated GCM file does not decrypt AT ALL, so writing in place would lose
    the whole conversation rather than the last message."""
    c = _saved()
    original = convo.load(c.id)

    real_replace = convo.os.replace

    def die(*_args, **_kwargs):
        raise OSError("power cut")

    monkeypatch.setattr(convo.os, "replace", die)
    c.messages.append({"role": "user", "content": "lost"})
    with pytest.raises(OSError):
        convo.save(c)

    monkeypatch.setattr(convo.os, "replace", real_replace)
    recovered = convo.load(c.id)
    assert recovered is not None
    assert recovered.messages == original.messages


def test_a_rogue_id_cannot_reach_outside_the_folder() -> None:
    for bad in ("../../etc/passwd", "", "a/b", "..", "Z"):
        with pytest.raises(ValueError):
            convo.load(bad)


# ------------------------------------------------------------------ vault
def test_the_file_fallback_is_owner_only_and_says_it_is_not_secure(tmp_path, monkeypatch) -> None:
    """No keychain at all — a headless Linux box, or a locked one.

    Both directions have to be stubbed. Patching only the write left the read
    reaching the REAL keychain, so once this machine had a key the test passed
    against it and never exercised the fallback it was named for.
    """
    monkeypatch.setattr(vault_module, "_FALLBACK", tmp_path / "conversation.key")
    monkeypatch.setattr(vault_module, "_to_keychain", lambda _key: False)
    monkeypatch.setattr(vault_module, "_from_keychain", lambda: None)
    v = vault_module.Vault()
    key = v.key()
    assert len(key) == vault_module.KEY_BYTES
    assert v.is_secure is False
    assert v.backend == "file"
    mode = (tmp_path / "conversation.key").stat().st_mode & 0o777
    assert mode == 0o600, f"the key file is {oct(mode)}, readable by others"


def test_the_key_is_stable_across_restarts(tmp_path, monkeypatch) -> None:
    """A key that changes is every previous conversation lost."""
    monkeypatch.setattr(vault_module, "_FALLBACK", tmp_path / "conversation.key")
    monkeypatch.setattr(vault_module, "_to_keychain", lambda _key: False)
    monkeypatch.setattr(vault_module, "_from_keychain", lambda: None)
    first = vault_module.Vault().key()
    second = vault_module.Vault().key()
    assert first == second
