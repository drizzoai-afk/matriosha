"""Merkle tree primitives for SHA-256 hex digests.

Public API:
- merkle_root
- merkle_proof
- verify_proof

Rules implemented (SPECIFICATION.md §4.2 / P2.3 prompt):
- Inputs are SHA-256 hex digests (64 chars).
- For odd node counts at any level, duplicate the last node (Bitcoin-style).
- Empty leaves root convention: sha256(b"").hexdigest().
- Single-leaf tree root is the leaf itself.
- Parent hash: sha256(bytes.fromhex(left) + bytes.fromhex(right)).hexdigest().
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Literal

Direction = Literal["L", "R"]
ProofStep = tuple[str, Direction]

_EMPTY_ROOT = hashlib.sha256(b"").hexdigest()


def _validate_digest_hex(value: str, *, name: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{name} must be a 64-char sha256 hex digest")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be valid lowercase/uppercase hex") from exc


def _hash_pair(left_hex: str, right_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(left_hex) + bytes.fromhex(right_hex)).hexdigest()


def _next_level(level: list[str]) -> list[str]:
    working = list(level)
    if len(working) % 2 == 1:
        working.append(working[-1])

    return [_hash_pair(working[i], working[i + 1]) for i in range(0, len(working), 2)]


def merkle_root(leaves: list[str]) -> str:
    """Return Merkle root for sha256-hex leaves.

    Empty list convention: sha256(b"").hexdigest().
    Single leaf convention: root == leaf.
    """
    if not leaves:
        return _EMPTY_ROOT

    for i, leaf in enumerate(leaves):
        _validate_digest_hex(leaf, name=f"leaves[{i}]")

    level = list(leaves)
    while len(level) > 1:
        level = _next_level(level)
    return level[0]


def merkle_proof(leaves: list[str], index: int) -> list[ProofStep]:
    """Build inclusion proof for a leaf index.

    Proof step format: (sibling_hash_hex, direction)
    where direction indicates where sibling is relative to current node:
    - "L": sibling is left
    - "R": sibling is right
    """
    if not leaves:
        raise ValueError("cannot build proof for empty leaves")

    if index < 0 or index >= len(leaves):
        raise IndexError("index out of range")

    for i, leaf in enumerate(leaves):
        _validate_digest_hex(leaf, name=f"leaves[{i}]")

    proof: list[ProofStep] = []
    level = list(leaves)
    current_index = index

    while len(level) > 1:
        working = list(level)
        if len(working) % 2 == 1:
            working.append(working[-1])

        if current_index % 2 == 0:
            sibling_index = current_index + 1
            direction: Direction = "R"
        else:
            sibling_index = current_index - 1
            direction = "L"

        proof.append((working[sibling_index], direction))

        current_index //= 2
        level = [_hash_pair(working[i], working[i + 1]) for i in range(0, len(working), 2)]

    return proof


def verify_proof(leaf: str, proof: list[ProofStep], root: str) -> bool:
    """Verify a Merkle inclusion proof against a root.

    Returns False for malformed proof entries/directions.
    """
    try:
        _validate_digest_hex(leaf, name="leaf")
        _validate_digest_hex(root, name="root")
    except ValueError:
        return False

    current = leaf

    for step in proof:
        if not isinstance(step, tuple) or len(step) != 2:
            return False

        sibling, direction = step
        if direction not in ("L", "R"):
            return False

        try:
            _validate_digest_hex(sibling, name="proof sibling")
        except ValueError:
            return False

        if direction == "L":
            current = _hash_pair(sibling, current)
        else:
            current = _hash_pair(current, sibling)

    return hmac.compare_digest(current, root)
