"""Managed key-custody helpers for double wrapping vault data keys.

Plaintext data keys stay client-side. Managed custody stores only wrapped key material.
"""

from __future__ import annotations

import base64
from typing import Any, Callable

from nacl.public import PrivateKey, PublicKey, SealedBox

from matriosha.core.crypto import decrypt, encrypt

_INNER_MAGIC = b"MKC1"


class KeyCustodyError(RuntimeError):
    """Raised when managed key custody operations fail."""


def _coerce_public_key(server_pubkey: bytes | str | PublicKey) -> PublicKey:
    if isinstance(server_pubkey, PublicKey):
        return server_pubkey
    if isinstance(server_pubkey, str):
        try:
            raw = base64.b64decode(server_pubkey, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise KeyCustodyError("server public key must be base64 or raw bytes") from exc
        return PublicKey(raw)
    return PublicKey(server_pubkey)


def _coerce_private_key(server_privkey_ref: Any) -> PrivateKey:
    if isinstance(server_privkey_ref, PrivateKey):
        return server_privkey_ref
    if isinstance(server_privkey_ref, str):
        try:
            raw = base64.b64decode(server_privkey_ref, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise KeyCustodyError("server private key must be base64 or raw bytes") from exc
        return PrivateKey(raw)
    if isinstance(server_privkey_ref, bytes):
        return PrivateKey(server_privkey_ref)
    raise KeyCustodyError("unsupported private key reference")


async def upload_wrapped_key(
    remote: Any,
    kek_salt: bytes,
    wrapped_key_bytes: bytes,
    *,
    algo: str = "aes-gcm",
    data_key: bytes | None = None,
) -> None:
    """Upload wrapped key material to managed custody.

    The remote adapter can provide:
    - `upsert_vault_key(kdf_salt_b64, wrapped_key_b64, algo=..., managed_custody_data_key_b64=...)`, or
    - `_request(method, path, json_payload=...)`.
    """

    payload = {
        "kdf_salt_b64": base64.b64encode(kek_salt).decode("ascii"),
        "wrapped_key_b64": base64.b64encode(wrapped_key_bytes).decode("ascii"),
        "algo": algo,
    }
    if data_key is not None:
        payload["managed_custody_data_key_b64"] = base64.b64encode(data_key).decode("ascii")

    if hasattr(remote, "upsert_vault_key"):
        await remote.upsert_vault_key(
            payload["kdf_salt_b64"],
            payload["wrapped_key_b64"],
            algo=payload["algo"],
            managed_custody_data_key_b64=payload.get("managed_custody_data_key_b64"),
        )
        return

    if hasattr(remote, "_request"):
        await remote._request(
            "POST", "/functions/v1/vault-custody", json_payload={"action": "upsert", **payload}
        )
        return

    raise KeyCustodyError("remote client does not support vault key upload")


async def fetch_wrapped_key(remote: Any) -> tuple[bytes, bytes, bytes | None]:
    """Fetch managed wrapped key material and return (kdf_salt, wrapped_key, custody_data_key)."""

    data: dict[str, Any]
    if hasattr(remote, "fetch_vault_key"):
        data = await remote.fetch_vault_key()
    elif hasattr(remote, "_request"):
        data = await remote._request(
            "POST", "/functions/v1/vault-custody", json_payload={"action": "fetch"}
        )
    else:
        raise KeyCustodyError("remote client does not support vault key fetch")

    salt_b64 = data.get("kdf_salt_b64")
    wrapped_b64 = data.get("wrapped_key_b64")
    custody_b64 = data.get("managed_custody_data_key_b64")
    if not isinstance(salt_b64, str) or not isinstance(wrapped_b64, str):
        raise KeyCustodyError("managed vault response missing wrapped key material")

    try:
        salt = base64.b64decode(salt_b64)
        wrapped = base64.b64decode(wrapped_b64)
        custody = (
            base64.b64decode(custody_b64) if isinstance(custody_b64, str) and custody_b64 else None
        )
    except Exception as exc:  # noqa: BLE001
        raise KeyCustodyError("managed vault response contains invalid base64") from exc

    return salt, wrapped, custody


def double_wrap(data_key: bytes, kek: bytes, server_pubkey: bytes | str | PublicKey) -> bytes:
    """AES-GCM wrap with KEK, then sealed-box wrap for server custody."""

    if len(data_key) != 32:
        raise KeyCustodyError("data_key must be exactly 32 bytes")
    if len(kek) != 32:
        raise KeyCustodyError("kek must be exactly 32 bytes")

    nonce, ciphertext = encrypt(data_key, kek)
    inner = _INNER_MAGIC + nonce + ciphertext
    sealed = SealedBox(_coerce_public_key(server_pubkey)).encrypt(inner)
    return sealed


def double_unwrap(
    blob: bytes,
    kek: bytes,
    server_privkey_ref: bytes | str | PrivateKey | Callable[[bytes], bytes],
) -> bytes:
    """Reverse double-wrap using server-side unseal ref + client KEK unwrap."""

    if len(kek) != 32:
        raise KeyCustodyError("kek must be exactly 32 bytes")

    if callable(server_privkey_ref):
        inner = server_privkey_ref(blob)
    else:
        box = SealedBox(_coerce_private_key(server_privkey_ref))
        inner = box.decrypt(blob)

    expected_min = len(_INNER_MAGIC) + 12 + 16
    if len(inner) < expected_min or not inner.startswith(_INNER_MAGIC):
        raise KeyCustodyError("wrapped key blob has invalid shape")

    nonce_start = len(_INNER_MAGIC)
    nonce = inner[nonce_start : nonce_start + 12]
    ciphertext = inner[nonce_start + 12 :]
    return decrypt(nonce, ciphertext, kek)
