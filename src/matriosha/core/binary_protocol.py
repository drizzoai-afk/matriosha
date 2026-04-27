"""Binary memory envelope protocol for encrypted payload transport.

Implements the P2.2 contract from SPECIFICATION.md §4:
- Binary plaintext payload encrypted with AES-256-GCM
- Base64 exchange encoding
- SHA-256 block hashes + Merkle root integrity metadata
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, cast
from uuid import uuid4

from matriosha.core import merkle as merkle_module
from matriosha.core.crypto import IntegrityError, decrypt, encrypt

BLOCK_SIZE = 64 * 1024  # 64 KiB fixed
_NONCE_SIZE = 12


@dataclass(kw_only=True)
class MemoryEnvelope:
    memory_id: str  # uuid4 str
    mode: Literal["local", "managed"]
    encoding: Literal["base64"] = "base64"
    hash_algo: Literal["sha256"] = "sha256"
    merkle_leaves: list[str]  # hex digests per block
    merkle_root: str  # hex digest
    vector_dim: int = 384
    created_at: str  # ISO-8601 UTC
    tags: list[str]
    source: Literal["cli", "agent"] = "cli"
    children: list[str] | None = None
    filename: str | None = None
    mime_type: str | None = None
    content_kind: str | None = None
    plaintext_bytes: int | None = None


def chunk_blocks(plaintext: bytes, block_size: int = BLOCK_SIZE) -> list[bytes]:
    """Split plaintext bytes into fixed-size blocks."""
    if block_size <= 0:
        raise ValueError("block_size must be > 0")
    if not plaintext:
        return []
    return [plaintext[i : i + block_size] for i in range(0, len(plaintext), block_size)]


def block_hash(block: bytes) -> str:
    """Return SHA-256 hex digest for one block."""
    return hashlib.sha256(block).hexdigest()


def merkle_root(leaves: list[str]) -> str:
    """Compute Merkle root via the canonical core.merkle module implementation."""
    return merkle_module.merkle_root(leaves)


def encode_envelope(
    plaintext: bytes,
    key: bytes,
    *,
    mode: str,
    tags: list[str],
    vector_dim: int = 384,
    source: str = "cli",
    filename: str | None = None,
    mime_type: str | None = None,
    content_kind: str | None = None,
) -> tuple[MemoryEnvelope, bytes]:
    """Encode plaintext into envelope metadata + base64 encrypted payload."""
    if mode not in ("local", "managed"):
        raise ValueError("mode must be 'local' or 'managed'")
    if source not in ("cli", "agent"):
        raise ValueError("source must be 'cli' or 'agent'")
    mode_literal = cast(Literal["local", "managed"], mode)
    source_literal = cast(Literal["cli", "agent"], source)

    blocks = chunk_blocks(plaintext)
    leaves = [block_hash(block) for block in blocks]
    root = merkle_root(leaves)

    nonce, ciphertext = encrypt(plaintext, key)
    encrypted_blob = nonce + ciphertext
    b64_payload = base64.b64encode(encrypted_blob)

    env = MemoryEnvelope(
        memory_id=str(uuid4()),
        mode=mode_literal,
        merkle_leaves=leaves,
        merkle_root=root,
        vector_dim=vector_dim,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        tags=list(tags),
        source=source_literal,
        filename=filename,
        mime_type=mime_type,
        content_kind=content_kind,
        plaintext_bytes=len(plaintext),
    )
    return env, b64_payload


def decode_envelope(env: MemoryEnvelope, b64_payload: bytes, key: bytes) -> bytes:
    """Decode base64 payload, decrypt, and verify block/merkle integrity."""
    try:
        encrypted_blob = base64.b64decode(b64_payload, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise IntegrityError("Payload is not valid base64") from exc

    if len(encrypted_blob) < _NONCE_SIZE:
        raise IntegrityError("Encrypted payload is too short")

    nonce = encrypted_blob[:_NONCE_SIZE]
    ciphertext = encrypted_blob[_NONCE_SIZE:]

    plaintext = decrypt(nonce, ciphertext, key)

    blocks = chunk_blocks(plaintext)
    actual_leaves = [block_hash(block) for block in blocks]

    if len(actual_leaves) != len(env.merkle_leaves):
        raise IntegrityError("Block count mismatch")

    for expected, actual in zip(env.merkle_leaves, actual_leaves):
        if not hmac.compare_digest(expected, actual):
            raise IntegrityError("Merkle leaf mismatch")

    actual_root = merkle_root(actual_leaves)
    if not hmac.compare_digest(env.merkle_root, actual_root):
        raise IntegrityError("Merkle root mismatch")

    return plaintext


def envelope_to_json(env: MemoryEnvelope) -> str:
    """Serialize envelope to SPECIFICATION.md §4.3 key schema.

    NOTE: The schema key is `merkle_leaf`; for multi-block support this field is
    serialized as an array of per-block leaf digests.
    """
    payload = {
        "memory_id": env.memory_id,
        "mode": env.mode,
        "encoding": env.encoding,
        "hash_algo": env.hash_algo,
        "merkle_leaf": env.merkle_leaves,
        "merkle_root": env.merkle_root,
        "vector_dim": env.vector_dim,
        "created_at": env.created_at,
        "tags": env.tags,
        "source": env.source,
        "children": env.children,
        "filename": env.filename,
        "mime_type": env.mime_type,
        "content_kind": env.content_kind,
        "plaintext_bytes": env.plaintext_bytes,
    }
    return json.dumps(payload, separators=(",", ":"))


def envelope_from_json(s: str) -> MemoryEnvelope:
    """Deserialize JSON metadata into a MemoryEnvelope."""
    data = json.loads(s)
    leaves = data.get("merkle_leaf", [])
    if isinstance(leaves, str):
        leaves = [leaves]

    children = data.get("children")
    if children is not None and (not isinstance(children, list) or not all(isinstance(item, str) for item in children)):
        raise ValueError("children must be a list of strings or null")

    return MemoryEnvelope(
        memory_id=data["memory_id"],
        mode=data["mode"],
        encoding=data.get("encoding", "base64"),
        hash_algo=data.get("hash_algo", "sha256"),
        merkle_leaves=leaves,
        merkle_root=data["merkle_root"],
        vector_dim=data.get("vector_dim", 384),
        created_at=data["created_at"],
        tags=data.get("tags", []),
        source=data.get("source", "cli"),
        children=children,
        filename=data.get("filename"),
        mime_type=data.get("mime_type"),
        content_kind=data.get("content_kind"),
        plaintext_bytes=data.get("plaintext_bytes"),
    )
