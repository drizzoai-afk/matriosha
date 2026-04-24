"""Tests for core.crypto cryptographic primitives."""

from __future__ import annotations

import pytest
from nacl.signing import SigningKey, VerifyKey

from matriosha.core.crypto import (
    IntegrityError,
    KDFError,
    KDFParams,
    decrypt,
    derive_key,
    encrypt,
    generate_nonce,
    generate_salt,
    new_keypair_ed25519,
)


def test_encrypt_decrypt_roundtrip() -> None:
    key = derive_key("correct horse battery staple", generate_salt())
    plaintext = b"matriosha secret payload"

    nonce, ct_and_tag = encrypt(plaintext, key)
    recovered = decrypt(nonce, ct_and_tag, key)

    assert recovered == plaintext


def test_tampered_ciphertext_raises_integrity_error() -> None:
    key = derive_key("passphrase", generate_salt())
    plaintext = b"immutable"

    nonce, ct_and_tag = encrypt(plaintext, key)
    tampered = bytearray(ct_and_tag)
    tampered[0] ^= 0x01

    with pytest.raises(IntegrityError):
        decrypt(nonce, bytes(tampered), key)


def test_wrong_aad_raises_integrity_error() -> None:
    key = derive_key("passphrase", generate_salt())
    plaintext = b"aad-bound payload"

    nonce, ct_and_tag = encrypt(plaintext, key, aad=b"right-aad")

    with pytest.raises(IntegrityError):
        decrypt(nonce, ct_and_tag, key, aad=b"wrong-aad")


def test_derive_key_deterministic_for_same_passphrase_and_salt() -> None:
    salt = generate_salt()
    passphrase = "same input"

    key1 = derive_key(passphrase, salt)
    key2 = derive_key(passphrase, salt)

    assert key1 == key2
    assert len(key1) == 32


def test_weak_kdf_params_raise_kdf_error() -> None:
    salt = generate_salt()

    with pytest.raises(KDFError):
        derive_key("passphrase", salt, KDFParams(time_cost=2))

    with pytest.raises(KDFError):
        derive_key("passphrase", salt, KDFParams(memory_cost=(64 * 1024) - 1))

    with pytest.raises(KDFError):
        derive_key("passphrase", salt, KDFParams(parallelism=3))


def test_nonces_unique_across_1000_calls() -> None:
    nonces = {generate_nonce() for _ in range(1000)}
    assert len(nonces) == 1000


def test_ed25519_sign_verify_roundtrip() -> None:
    priv, pub = new_keypair_ed25519()

    signing_key = SigningKey(priv)
    verify_key = VerifyKey(pub)

    message = b"vault operation payload"
    signature = signing_key.sign(message).signature

    recovered = verify_key.verify(message, signature)
    assert recovered == message
