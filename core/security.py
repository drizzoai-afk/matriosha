"""
Matriosha Security Module — P1: Cryptographic Foundation

Implements AES-256-GCM encryption and Argon2id key derivation
following OWASP A02 cryptographic failure prevention guidelines.

Security Decisions:
- AES-256-GCM provides authenticated encryption (confidentiality + integrity)
- Argon2id is resistant to GPU/ASIC attacks (memory-hard function)
- Keys are never written to disk; Python keyring uses OS-level secure storage
- Each vault gets a unique 16-byte salt to prevent rainbow table attacks
"""

import os
import base64
import hashlib
from typing import Dict

import argon2
from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import keyring

# Constants
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST = 65536  # 64 MB in KB
ARGON2_PARALLELISM = 4
ARGON2_HASH_LEN = 32  # 256 bits for AES-256 key
ARGON2_SALT_LEN = 16  # 128 bits

KEYRING_SERVICE_NAME = "matriosha"
KEYRING_KEY_ID_PREFIX = "vault_key_"


def generate_salt() -> bytes:
    """
    Generate a cryptographically secure random salt.
    
    Returns:
        16-byte random salt for Argon2id KDF.
    
    Security Note:
        os.urandom() uses the OS CSPRNG (/dev/urandom on Linux, 
        CryptGenRandom on Windows, SecRandomCopyBytes on macOS).
    """
    return os.urandom(ARGON2_SALT_LEN)


def derive_key(password: str, salt: bytes) -> bytes:
    """
    Derive a 256-bit encryption key from a password using Argon2id.
    
    Args:
        password: User's plaintext password.
        salt: Unique 16-byte salt for this vault.
    
    Returns:
        32-byte (256-bit) key suitable for AES-256-GCM.
    
    Security Decisions:
        - Argon2id combines Argon2i (side-channel resistance) and 
          Argon2d (GPU resistance) for optimal security.
        - time_cost=3 provides reasonable security without excessive latency.
        - memory_cost=64MB makes GPU/ASIC attacks prohibitively expensive.
        - parallelism=4 utilizes multi-core CPUs efficiently.
    
    Reference:
        RFC 9106: https://datatracker.ietf.org/doc/html/rfc9106
    """
    if len(salt) != ARGON2_SALT_LEN:
        raise ValueError(f"Salt must be {ARGON2_SALT_LEN} bytes, got {len(salt)}")
    
    key = hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LEN,
        type=Type.ID,  # Argon2id
    )
    
    return key


def store_key_vault(vault_id: str, key: bytes) -> None:
    """
    Store an encryption key in the OS-level keyring.
    
    Args:
        vault_id: Unique identifier for the vault.
        key: 32-byte encryption key.
    
    Security Decisions:
        - Python keyring delegates to OS secure storage:
          * macOS: Keychain
          * Windows: Credential Vault
          * Linux: Secret Service API (GNOME Keyring / KWallet)
        - Keys are never written to disk in plaintext.
        - Key is base64-encoded for keyring compatibility.
    """
    key_b64 = base64.b64encode(key).decode("ascii")
    keyring.set_password(KEYRING_SERVICE_NAME, KEYRING_KEY_ID_PREFIX + vault_id, key_b64)


def retrieve_key_vault(vault_id: str) -> bytes:
    """
    Retrieve an encryption key from the OS-level keyring.
    
    Args:
        vault_id: Unique identifier for the vault.
    
    Returns:
        32-byte encryption key.
    
    Raises:
        KeyError: If no key is found for this vault_id.
    """
    key_b64 = keyring.get_password(KEYRING_SERVICE_NAME, KEYRING_KEY_ID_PREFIX + vault_id)
    if key_b64 is None:
        raise KeyError(f"No key found for vault: {vault_id}")
    return base64.b64decode(key_b64)


def delete_key_vault(vault_id: str) -> None:
    """
    Delete an encryption key from the OS-level keyring.
    
    Args:
        vault_id: Unique identifier for the vault.
    """
    try:
        keyring.delete_password(KEYRING_SERVICE_NAME, KEYRING_KEY_ID_PREFIX + vault_id)
    except keyring.errors.PasswordDeleteError:
        pass  # Key already deleted or doesn't exist


def encrypt_data(key: bytes, plaintext: bytes, associated_data: bytes = None) -> Dict[str, str]:
    """
    Encrypt data using AES-256-GCM (authenticated encryption).
    
    Args:
        key: 32-byte encryption key (from derive_key or keyring).
        plaintext: Data to encrypt.
        associated_data: Optional additional authenticated data (AAD).
    
    Returns:
        Dictionary with base64-encoded ciphertext, nonce, and tag.
        Format: {"ciphertext": str, "nonce": str, "tag": str}
    
    Security Decisions:
        - AES-256-GCM provides both confidentiality and integrity.
        - 12-byte (96-bit) nonce is optimal for GCM mode.
        - Nonce is randomly generated per encryption (never reused with same key).
        - 16-byte authentication tag detects any tampering.
        - Associated data (if provided) is authenticated but not encrypted.
    
    Reference:
        NIST SP 800-38D: https://csrc.nist.gov/publications/detail/sp/800-38d/final
    """
    if len(key) != 32:
        raise ValueError(f"Key must be 32 bytes for AES-256, got {len(key)}")
    
    # Generate random 12-byte nonce (optimal for GCM)
    nonce = os.urandom(12)
    
    # Initialize AES-GCM with 256-bit key
    aesgcm = AESGCM(key)
    
    # Encrypt: returns ciphertext + 16-byte auth tag concatenated
    ct_and_tag = aesgcm.encrypt(nonce, plaintext, associated_data)
    
    # Split ciphertext and tag (last 16 bytes are the tag)
    ciphertext = ct_and_tag[:-16]
    tag = ct_and_tag[-16:]
    
    return {
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
    }


def decrypt_data(
    key: bytes, 
    ciphertext_b64: str, 
    nonce_b64: str, 
    tag_b64: str, 
    associated_data: bytes = None
) -> bytes:
    """
    Decrypt data using AES-256-GCM with integrity verification.
    
    Args:
        key: 32-byte decryption key.
        ciphertext_b64: Base64-encoded ciphertext.
        nonce_b64: Base64-encoded nonce.
        tag_b64: Base64-encoded authentication tag.
        associated_data: Optional additional authenticated data (must match encryption).
    
    Returns:
        Decrypted plaintext bytes.
    
    Raises:
        cryptography.exceptions.InvalidTag: If ciphertext was tampered with 
            or wrong key/nonce/AAD was provided.
    
    Security Decisions:
        - Decryption fails if authentication tag doesn't match, preventing
          use of tampered data.
        - This implements "fail-fast" integrity checking.
        - The same associated_data used during encryption must be provided.
    """
    if len(key) != 32:
        raise ValueError(f"Key must be 32 bytes for AES-256, got {len(key)}")
    
    ciphertext = base64.b64decode(ciphertext_b64)
    nonce = base64.b64decode(nonce_b64)
    tag = base64.b64decode(tag_b64)
    
    if len(nonce) != 12:
        raise ValueError(f"Nonce must be 12 bytes, got {len(nonce)}")
    
    if len(tag) != 16:
        raise ValueError(f"Tag must be 16 bytes, got {len(tag)}")
    
    # Reconstruct ciphertext + tag for AES-GCM
    ct_and_tag = ciphertext + tag
    
    # Initialize AES-GCM and decrypt
    aesgcm = AESGCM(key)
    
    # This will raise InvalidTag if integrity check fails
    plaintext = aesgcm.decrypt(nonce, ct_and_tag, associated_data)
    
    return plaintext


def hash_for_leaf_id(data: bytes) -> bytes:
    """
    Compute SHA-256 hash for use as Leaf ID in Merkle Tree.
    
    Args:
        data: Data to hash (typically encrypted binary block).
    
    Returns:
        32-byte SHA-256 hash.
    
    Note:
        For the binary protocol header, only the first 10 bytes (80 bits)
        of this hash are used as the Leaf ID.
    """
    return hashlib.sha256(data).digest()
