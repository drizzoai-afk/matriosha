"""Tests for core.binary_protocol envelope encoding/decoding."""

from __future__ import annotations

import base64
import hashlib
import json
import os

import pytest

from matriosha.core.binary_protocol import (
    MemoryEnvelope,
    block_hash,
    chunk_blocks,
    decode_envelope,
    encode_envelope,
    envelope_from_json,
    envelope_to_json,
    merkle_root,
)
from matriosha.core.crypto import IntegrityError, derive_key, generate_salt


def _test_key() -> bytes:
    return derive_key("binary-protocol-passphrase", generate_salt())


def test_roundtrip_small_plaintext_lt_one_block() -> None:
    plaintext = b"hello matriosha"
    key = _test_key()

    env, payload = encode_envelope(plaintext, key, mode="local", tags=["unit", "small"])
    restored = decode_envelope(env, payload, key)

    assert restored == plaintext
    assert env.merkle_leaves == [block_hash(plaintext)]
    assert env.merkle_root == merkle_root(env.merkle_leaves)


def test_roundtrip_large_plaintext_5mb_verifies_all_leaves_and_root() -> None:
    plaintext = os.urandom(5 * 1024 * 1024)
    key = _test_key()

    env, payload = encode_envelope(plaintext, key, mode="managed", tags=["large"])
    restored = decode_envelope(env, payload, key)

    expected_leaves = [block_hash(b) for b in chunk_blocks(plaintext)]
    assert restored == plaintext
    assert env.merkle_leaves == expected_leaves
    assert env.merkle_root == merkle_root(expected_leaves)


def test_tampered_payload_byte_raises_integrity_error() -> None:
    plaintext = b"detect payload tamper"
    key = _test_key()

    env, payload = encode_envelope(plaintext, key, mode="local", tags=[])

    raw = bytearray(base64.b64decode(payload))
    raw[len(raw) // 2] ^= 0x01
    tampered_payload = base64.b64encode(bytes(raw))

    with pytest.raises(IntegrityError):
        decode_envelope(env, tampered_payload, key)


def test_tampered_leaf_in_envelope_raises_integrity_error() -> None:
    plaintext = os.urandom(200_000)  # multiple blocks
    key = _test_key()

    env, payload = encode_envelope(plaintext, key, mode="local", tags=[])

    tampered_env = MemoryEnvelope(
        memory_id=env.memory_id,
        mode=env.mode,
        encoding=env.encoding,
        hash_algo=env.hash_algo,
        merkle_leaves=list(env.merkle_leaves),
        merkle_root=env.merkle_root,
        vector_dim=env.vector_dim,
        created_at=env.created_at,
        tags=list(env.tags),
        source=env.source,
    )
    tampered_env.merkle_leaves[0] = "0" * 64

    with pytest.raises(IntegrityError):
        decode_envelope(tampered_env, payload, key)


def test_json_roundtrip_produces_identical_envelope() -> None:
    key = _test_key()
    env, _ = encode_envelope(b"json-check", key, mode="managed", tags=["json"], source="agent")

    s = envelope_to_json(env)
    parsed = json.loads(s)

    assert list(parsed.keys()) == [
        "memory_id",
        "mode",
        "encoding",
        "hash_algo",
        "merkle_leaf",
        "merkle_root",
        "vector_dim",
        "created_at",
        "tags",
        "source",
        "children",
    ]

    restored_env = envelope_from_json(s)
    assert restored_env == env


def test_empty_plaintext_uses_empty_tree_root_convention() -> None:
    """Empty tree convention: merkle_root == sha256(b"").hexdigest()."""
    key = _test_key()

    env, payload = encode_envelope(b"", key, mode="local", tags=[])
    restored = decode_envelope(env, payload, key)

    assert restored == b""
    assert env.merkle_leaves == []
    assert env.merkle_root == hashlib.sha256(b"").hexdigest()
