"""Vault key material bootstrap and unlock primitives."""

from __future__ import annotations

import os
from pathlib import Path
import platformdirs  # noqa: F401

from matriosha.core.paths import data_dir

from matriosha.core.crypto import (
    KDFError,
    IntegrityError,
    decrypt,
    derive_key,
    encrypt,
    generate_salt,
)

MAGIC = b"MTR1"
NONCE_LEN = 12
DATA_KEY_LEN = 32
TAG_LEN = 16
SALT_LEN = 16
KEY_FILE_NAME = "vault.key.enc"
SALT_FILE_NAME = "vault.salt"


class VaultError(Exception):
    """Base vault exception."""


class AuthError(VaultError):
    """Raised when passphrase does not unlock existing vault material."""


class VaultIntegrityError(VaultError):
    """Raised for malformed/corrupt vault key material files."""


class VaultAlreadyInitializedError(VaultError):
    """Raised when attempting to initialize an already initialized vault without force."""


class Vault:
    """In-memory representation of unlocked vault key material."""

    def __init__(self, profile: str, data_key: bytes, key_file: Path, salt_file: Path):
        if len(data_key) != DATA_KEY_LEN:
            raise VaultIntegrityError("vault data key must be exactly 32 bytes")
        self.profile = profile
        self.data_key = data_key
        self.key_file = key_file
        self.salt_file = salt_file

    @classmethod
    def init(cls, profile: str, passphrase: str, *, force: bool = False) -> "Vault":
        key_file, salt_file = cls._paths(profile)
        key_exists = key_file.exists()
        salt_exists = salt_file.exists()

        if (key_exists or salt_exists) and not force:
            raise VaultAlreadyInitializedError(f"vault already initialized for profile '{profile}'")

        if force and (key_exists or salt_exists):
            cls.validate_material(profile)

        key_file.parent.mkdir(parents=True, exist_ok=True)

        salt = generate_salt(SALT_LEN)
        kek = derive_key(passphrase, salt)
        data_key = os.urandom(DATA_KEY_LEN)

        nonce, ciphertext = encrypt(data_key, kek)
        if len(nonce) != NONCE_LEN:
            raise VaultIntegrityError("cipher nonce length invalid")
        if len(ciphertext) != DATA_KEY_LEN + TAG_LEN:
            raise VaultIntegrityError("ciphertext+tag length invalid")

        wrapped = MAGIC + nonce + ciphertext
        cls._write_secure(salt_file, salt)
        cls._write_secure(key_file, wrapped)

        return cls(profile=profile, data_key=data_key, key_file=key_file, salt_file=salt_file)

    @classmethod
    def unlock(cls, profile: str, passphrase: str) -> "Vault":
        key_file, salt_file = cls._paths(profile)

        if not key_file.exists() or not salt_file.exists():
            raise VaultIntegrityError(f"vault material missing for profile '{profile}'")

        salt = cls._read_secure(salt_file)
        if len(salt) != SALT_LEN:
            raise VaultIntegrityError("vault salt file is corrupted")

        blob = cls._read_secure(key_file)
        if len(blob) != len(MAGIC) + NONCE_LEN + DATA_KEY_LEN + TAG_LEN:
            raise VaultIntegrityError("vault key file has invalid size")
        if blob[: len(MAGIC)] != MAGIC:
            raise VaultIntegrityError("vault key file magic mismatch")

        nonce = blob[len(MAGIC) : len(MAGIC) + NONCE_LEN]
        ct = blob[len(MAGIC) + NONCE_LEN :]

        try:
            kek = derive_key(passphrase, salt)
            data_key = decrypt(nonce, ct, kek)
        except (IntegrityError, KDFError) as exc:
            raise AuthError("invalid passphrase") from exc

        if len(data_key) != DATA_KEY_LEN:
            raise VaultIntegrityError("decrypted vault data key has invalid length")

        return cls(profile=profile, data_key=data_key, key_file=key_file, salt_file=salt_file)

    @classmethod
    def validate_material(cls, profile: str) -> tuple[Path, Path]:
        """Validate on-disk file shape and invariants without decrypting content."""
        key_file, salt_file = cls._paths(profile)
        if not key_file.exists() or not salt_file.exists():
            raise VaultIntegrityError("vault material missing")

        salt = cls._read_secure(salt_file)
        if len(salt) != SALT_LEN:
            raise VaultIntegrityError("vault salt file has invalid size")

        blob = cls._read_secure(key_file)
        expected = len(MAGIC) + NONCE_LEN + DATA_KEY_LEN + TAG_LEN
        if len(blob) != expected:
            raise VaultIntegrityError("vault key file has invalid size")
        if blob[: len(MAGIC)] != MAGIC:
            raise VaultIntegrityError("vault key file magic mismatch")
        return key_file, salt_file

    @staticmethod
    def _profile_root(profile: str) -> Path:
        base = data_dir()
        return base / profile

    @classmethod
    def _paths(cls, profile: str) -> tuple[Path, Path]:
        root = cls._profile_root(profile)
        return root / KEY_FILE_NAME, root / SALT_FILE_NAME

    @staticmethod
    def _write_secure(path: Path, data: bytes) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise

        if os.name != "nt":
            os.chmod(path, 0o600)

    @staticmethod
    def _read_secure(path: Path) -> bytes:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags)
        try:
            with os.fdopen(fd, "rb") as f:
                return f.read()
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
