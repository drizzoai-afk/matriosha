"""Matriosha Core — Secure Agentic Memory Layer"""

__version__ = "1.0.0"

from .security import derive_key, encrypt_data, decrypt_data
from .binary_protocol import pack_header, unpack_header, validate_header
from .merkle import MerkleTree, hash_leaf, hash_nodes

__all__ = [
    "derive_key",
    "encrypt_data",
    "decrypt_data",
    "pack_header",
    "unpack_header",
    "validate_header",
    "MerkleTree",
    "hash_leaf",
    "hash_nodes",
]
