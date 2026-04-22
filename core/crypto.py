"""Core cryptographic primitives for Matriosha.

This module provides:
- Argon2id key derivation
- AES-256-GCM authenticated encryption/decryption
- Ed25519 keypair generation for signatures
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from nacl.signing import SigningKey


class IntegrityError(Exception):
    """Raised when authenticated decryption integrity checks fail."""


class KDFError(Exception):
    """Raised when key-derivation inputs or parameters are invalid."""


@dataclass(frozen=True)
class KDFParams:
    time_cost: int = 3
    memory_cost: int = 64 * 1024  # 64 MiB in KiB
    parallelism: int = 4
    salt_len: int = 16
    hash_len: int = 32


def generate_salt(length: int = 16) -> bytes:
    """Generate a cryptographically secure random salt using os.urandom."""
    if length <= 0:
        raise KDFError("Salt length must be a positive integer")
    return os.urandom(length)


def derive_key(passphrase: str, salt: bytes, params: KDFParams = KDFParams()) -> bytes:
    """Derive a 32-byte key from passphrase+salt using Argon2id."""
    if params.time_cost < 3:
        raise KDFError("Weak KDF params: time_cost must be >= 3")
    if params.memory_cost < 64 * 1024:
        raise KDFError("Weak KDF params: memory_cost must be >= 64*1024 KiB")
    if params.parallelism < 4:
        raise KDFError("Weak KDF params: parallelism must be >= 4")

    if params.hash_len != 32:
        raise KDFError("KDF hash_len must be exactly 32 bytes")

    if len(salt) != params.salt_len:
        raise KDFError(f"Salt must be exactly {params.salt_len} bytes")

    try:
        key = hash_secret_raw(
            secret=passphrase.encode("utf-8"),
            salt=salt,
            time_cost=params.time_cost,
            memory_cost=params.memory_cost,
            parallelism=params.parallelism,
            hash_len=params.hash_len,
            type=Type.ID,
        )
    except Exception as exc:  # pragma: no cover
        raise KDFError("Argon2id key derivation failed") from exc

    if len(key) != 32:
        raise KDFError("Derived key length must be exactly 32 bytes")

    return key


def generate_nonce() -> bytes:
    """Generate a 12-byte AES-GCM nonce using os.urandom."""
    return os.urandom(12)


def encrypt(plaintext: bytes, key: bytes, aad: bytes = b"") -> tuple[bytes, bytes]:
    """Encrypt plaintext using AES-256-GCM.

    Returns:
        tuple[bytes, bytes]: (nonce, ciphertext_plus_tag)
    """
    if len(key) != 32:
        raise ValueError("Key length must be exactly 32 bytes")

    nonce = generate_nonce()
    if len(nonce) != 12:
        raise ValueError("Nonce length must be exactly 12 bytes")

    aesgcm = AESGCM(key)
    ct_and_tag = aesgcm.encrypt(nonce, plaintext, aad)
    return nonce, ct_and_tag


def decrypt(nonce: bytes, ct_and_tag: bytes, key: bytes, aad: bytes = b"") -> bytes:
    """Decrypt AES-256-GCM ciphertext and verify integrity.

    Raises:
        IntegrityError: If authentication fails.
    """
    if len(key) != 32:
        raise ValueError("Key length must be exactly 32 bytes")
    if len(nonce) != 12:
        raise ValueError("Nonce length must be exactly 12 bytes")

    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(nonce, ct_and_tag, aad)
    except InvalidTag as exc:
        raise IntegrityError("Ciphertext integrity check failed") from exc


def new_keypair_ed25519() -> tuple[bytes, bytes]:
    """Generate a new Ed25519 keypair as (private_key_bytes, public_key_bytes)."""
    signing_key = SigningKey.generate()
    verify_key = signing_key.verify_key
    return signing_key.encode(), verify_key.encode()
