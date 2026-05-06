from __future__ import annotations

import base64
import stat
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag
import keyring

from matriosha.core import security


def test_generate_salt_returns_expected_length_and_random_values() -> None:
    salt1 = security.generate_salt()
    salt2 = security.generate_salt()

    assert len(salt1) == security.ARGON2_SALT_LEN
    assert len(salt2) == security.ARGON2_SALT_LEN
    assert salt1 != salt2


def test_derive_key_rejects_invalid_salt_before_hashing() -> None:
    with pytest.raises(ValueError, match="Salt must be 16 bytes"):
        security.derive_key("password", b"too-short")


def test_encrypt_decrypt_roundtrip_with_associated_data() -> None:
    key = b"k" * 32
    plaintext = b"secret memory payload"
    aad = b"vault-id:vault-1"

    encrypted = security.encrypt_data(key, plaintext, associated_data=aad)
    decrypted = security.decrypt_data(
        key,
        encrypted["ciphertext"],
        encrypted["nonce"],
        encrypted["tag"],
        associated_data=aad,
    )

    assert decrypted == plaintext
    assert set(encrypted) == {"ciphertext", "nonce", "tag"}
    assert len(base64.b64decode(encrypted["nonce"])) == 12
    assert len(base64.b64decode(encrypted["tag"])) == 16


def test_decrypt_rejects_wrong_associated_data() -> None:
    key = b"k" * 32
    encrypted = security.encrypt_data(key, b"payload", associated_data=b"expected-aad")

    with pytest.raises(InvalidTag):
        security.decrypt_data(
            key,
            encrypted["ciphertext"],
            encrypted["nonce"],
            encrypted["tag"],
            associated_data=b"wrong-aad",
        )


def test_decrypt_rejects_tampered_ciphertext() -> None:
    key = b"k" * 32
    encrypted = security.encrypt_data(key, b"payload")

    ciphertext = bytearray(base64.b64decode(encrypted["ciphertext"]))
    ciphertext[0] ^= 1
    encrypted["ciphertext"] = base64.b64encode(bytes(ciphertext)).decode("ascii")

    with pytest.raises(InvalidTag):
        security.decrypt_data(key, encrypted["ciphertext"], encrypted["nonce"], encrypted["tag"])


@pytest.mark.parametrize("key", [b"", b"short", b"k" * 31, b"k" * 33])
def test_encrypt_rejects_invalid_key_lengths(key: bytes) -> None:
    with pytest.raises(ValueError, match="Key must be 32 bytes"):
        security.encrypt_data(key, b"payload")


def test_encrypt_rejects_oversized_plaintext_without_large_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(security, "MAX_PLAINTEXT_SIZE", 3)

    with pytest.raises(ValueError, match="Plaintext too large"):
        security.encrypt_data(b"k" * 32, b"four")


def test_decrypt_rejects_invalid_key_length() -> None:
    with pytest.raises(ValueError, match="Key must be 32 bytes"):
        security.decrypt_data(b"short", "", "", "")


def test_decrypt_rejects_invalid_nonce_length() -> None:
    ciphertext = base64.b64encode(b"cipher").decode("ascii")
    nonce = base64.b64encode(b"bad").decode("ascii")
    tag = base64.b64encode(b"t" * 16).decode("ascii")

    with pytest.raises(ValueError, match="Nonce must be 12 bytes"):
        security.decrypt_data(b"k" * 32, ciphertext, nonce, tag)


def test_decrypt_rejects_invalid_tag_length() -> None:
    ciphertext = base64.b64encode(b"cipher").decode("ascii")
    nonce = base64.b64encode(b"n" * 12).decode("ascii")
    tag = base64.b64encode(b"bad").decode("ascii")

    with pytest.raises(ValueError, match="Tag must be 16 bytes"):
        security.decrypt_data(b"k" * 32, ciphertext, nonce, tag)


def test_hash_for_leaf_id_returns_sha256_digest() -> None:
    digest = security.hash_for_leaf_id(b"encrypted block")

    assert len(digest) == 32
    assert digest.hex() == "d586685ae9f4346cdf8d86e5c20ad9c4b6397818a61cf7830f53403245b096c3"


def test_store_key_uses_keyring_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, str]] = []

    def fake_set_password(service: str, username: str, password: str) -> None:
        calls.append((service, username, password))

    monkeypatch.setattr(security.keyring, "set_password", fake_set_password)

    security.store_key_vault("vault-1", b"k" * 32)

    assert calls == [
        (
            security.KEYRING_SERVICE_NAME,
            security.KEYRING_KEY_ID_PREFIX + "vault-1",
            base64.b64encode(b"k" * 32).decode("ascii"),
        )
    ]


def test_store_key_falls_back_to_600_file_when_keyring_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_set_password(service: str, username: str, password: str) -> None:
        raise keyring.errors.KeyringError("no backend")

    monkeypatch.setattr(security.keyring, "set_password", fake_set_password)
    monkeypatch.setattr(security.Path, "home", lambda: tmp_path)

    security.store_key_vault("vault-1", b"k" * 32)

    key_file = tmp_path / ".matriosha" / ".key_vault-1"
    assert key_file.read_text() == base64.b64encode(b"k" * 32).decode("ascii")
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


def test_retrieve_key_uses_cache_before_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    security._key_cache.clear()
    security._key_cache["vault-1"] = (b"cached-key", security.time.time() + 60)

    def fail_get_password(service: str, username: str) -> str:
        raise AssertionError("keyring should not be called for unexpired cache")

    monkeypatch.setattr(security.keyring, "get_password", fail_get_password)

    assert security.retrieve_key_vault("vault-1") == b"cached-key"


def test_retrieve_key_refreshes_expired_cache_from_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    security._key_cache.clear()
    security._key_cache["vault-1"] = (b"old-key", security.time.time() - 1)

    key_b64 = base64.b64encode(b"k" * 32).decode("ascii")
    monkeypatch.setattr(security.keyring, "get_password", lambda service, username: key_b64)

    assert security.retrieve_key_vault("vault-1") == b"k" * 32
    assert security._key_cache["vault-1"][0] == b"k" * 32


def test_retrieve_key_falls_back_to_file_and_warns_on_insecure_permissions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    security._key_cache.clear()

    def fake_get_password(service: str, username: str) -> str:
        raise keyring.errors.KeyringError("no backend")

    monkeypatch.setattr(security.keyring, "get_password", fake_get_password)
    monkeypatch.setattr(security.Path, "home", lambda: tmp_path)

    key_dir = tmp_path / ".matriosha"
    key_dir.mkdir()
    key_file = key_dir / ".key_vault-1"
    key_file.write_text(base64.b64encode(b"k" * 32).decode("ascii"))
    key_file.chmod(0o644)

    assert security.retrieve_key_vault("vault-1") == b"k" * 32
    assert "insecure permissions" in caplog.text


def test_retrieve_key_raises_when_missing_from_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    security._key_cache.clear()
    monkeypatch.setattr(security.keyring, "get_password", lambda service, username: None)

    with pytest.raises(KeyError, match="No key found for vault"):
        security.retrieve_key_vault("missing")


def test_retrieve_key_raises_when_fallback_file_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    security._key_cache.clear()

    def fake_get_password(service: str, username: str) -> str:
        raise keyring.errors.KeyringError("no backend")

    monkeypatch.setattr(security.keyring, "get_password", fake_get_password)
    monkeypatch.setattr(security.Path, "home", lambda: tmp_path)

    with pytest.raises(KeyError, match="No key found for vault"):
        security.retrieve_key_vault("missing")


def test_delete_key_vault_ignores_already_missing_password(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_delete_password(service: str, username: str) -> None:
        raise keyring.errors.PasswordDeleteError("missing")

    monkeypatch.setattr(security.keyring, "delete_password", fake_delete_password)

    security.delete_key_vault("vault-1")
