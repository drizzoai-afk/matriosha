"""Matriosha Core — Secure Agentic Memory Layer"""

__version__ = "1.0.0"

from .security import derive_key, encrypt_data, decrypt_data
from .binary_protocol import (
    BLOCK_SIZE,
    MemoryEnvelope,
    block_hash,
    chunk_blocks,
    decode_envelope,
    encode_envelope,
    envelope_from_json,
    envelope_to_json,
    merkle_root,
)
from .merkle import MerkleTree, hash_leaf, hash_nodes

__all__ = [
    "derive_key",
    "encrypt_data",
    "decrypt_data",
    "BLOCK_SIZE",
    "MemoryEnvelope",
    "chunk_blocks",
    "block_hash",
    "merkle_root",
    "encode_envelope",
    "decode_envelope",
    "envelope_to_json",
    "envelope_from_json",
    "MerkleTree",
    "hash_leaf",
    "hash_nodes",
]
