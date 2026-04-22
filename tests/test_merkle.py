"""Tests for core.merkle canonical API."""

from __future__ import annotations

import hashlib

from core.merkle import merkle_proof, merkle_root, verify_proof


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_known_vector_four_leaves_root_matches_expected() -> None:
    # Hard-coded known vector.
    leaves = [
        "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
        "3e23e8160039594a33894f6564e1b1348bbd7a0088d42c4acb73eeaed59c009d",
        "2e7d2c03a9507ae265ecf5b5356885a53393a2029d241394997265a1a25aefc6",
        "18ac3e7343f016890c510e93f935261169d9e3f565436429830faf0934f4f8e4",
    ]
    expected_root = "14ede5e8e97ad9372327728f5099b95604a39593cac3bd38a343ad76205213e7"

    assert merkle_root(leaves) == expected_root


def test_odd_count_three_leaves_duplicate_last_rule() -> None:
    leaves = [_sha256_hex(b"a"), _sha256_hex(b"b"), _sha256_hex(b"c")]
    # Precomputed expected root with duplicate-last behavior for the odd node.
    expected_root = "d31a37ef6ac14a2db1470c4316beb5592e6afd4465022339adafda76a18ffabe"

    assert merkle_root(leaves) == expected_root


def test_proof_roundtrip_for_every_leaf_index() -> None:
    leaves = [_sha256_hex(b"L0"), _sha256_hex(b"L1"), _sha256_hex(b"L2"), _sha256_hex(b"L3"), _sha256_hex(b"L4")]
    root = merkle_root(leaves)

    for i, leaf in enumerate(leaves):
        proof = merkle_proof(leaves, i)
        assert verify_proof(leaf, proof, root)


def test_tampered_proof_fails_verification() -> None:
    leaves = [_sha256_hex(b"x"), _sha256_hex(b"y"), _sha256_hex(b"z")]
    root = merkle_root(leaves)
    proof = merkle_proof(leaves, 1)

    # Tamper sibling digest in first step while preserving hex shape.
    sibling, direction = proof[0]
    tampered_sibling = ("0" if sibling[0] != "0" else "1") + sibling[1:]
    tampered_proof = [(tampered_sibling, direction), *proof[1:]]

    assert not verify_proof(leaves[1], tampered_proof, root)


def test_single_leaf_tree_root_and_empty_proof() -> None:
    leaf = _sha256_hex(b"single")
    root = merkle_root([leaf])
    proof = merkle_proof([leaf], 0)

    assert root == leaf
    assert proof == []
    assert verify_proof(leaf, proof, root)
