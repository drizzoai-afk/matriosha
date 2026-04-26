"""Matriosha Core — Secure Agentic Memory Layer"""

__version__ = "2.0.0"

from .binary_protocol import (
    BLOCK_SIZE,
    MemoryEnvelope,
    block_hash,
    chunk_blocks,
    decode_envelope,
    encode_envelope,
    envelope_from_json,
    envelope_to_json,
)
from .merkle import merkle_proof, merkle_root, verify_proof
from .security import decrypt_data, derive_key, encrypt_data

__all__ = [
    "derive_key",
    "encrypt_data",
    "decrypt_data",
    "BLOCK_SIZE",
    "MemoryEnvelope",
    "chunk_blocks",
    "block_hash",
    "merkle_root",
    "merkle_proof",
    "verify_proof",
    "encode_envelope",
    "decode_envelope",
    "envelope_to_json",
    "envelope_from_json",
]
