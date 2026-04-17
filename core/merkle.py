"""
Matriosha Merkle Tree — P3: Integrity Verification Engine

Implements a Merkle Tree for cryptographic integrity verification of memory blocks.
Each leaf is a SHA-256 hash of an encrypted binary block. The tree enables:

1. Proof-of-Inclusion: Prove a specific block exists in the vault without
   revealing other blocks (zero-knowledge property).

2. Tamper Detection: Any modification to a single block changes the Merkle Root,
   making unauthorized modifications immediately detectable.

3. Efficient Sync: Compare Merkle Roots between local and remote storage to
   detect conflicts before data transfer.

Tree Structure:

                    Root Hash
                   /         \\
              Hash(A+B)    Hash(C+D)
             /      \\      /      \\
          Hash(A) Hash(B) Hash(C) Hash(D)
           Leaf     Leaf    Leaf    Leaf

Odd Number of Leaves:
  If the number of leaves is odd, the last leaf is duplicated to form a pair.
  Example: [A, B, C] → pairs: (A,B), (C,C)

Reference:
  Merkle Trees are widely used in blockchain (Bitcoin, Ethereum) and
  version control systems (Git) for integrity verification.
"""

import hashlib
import base64
from typing import List, Dict, Optional


def hash_leaf(data: bytes) -> bytes:
    """
    Compute SHA-256 hash of a leaf node (encrypted memory block).

    Args:
        data: Encrypted binary block content.

    Returns:
        32-byte SHA-256 hash.

    Security Note:
        SHA-256 is collision-resistant and preimage-resistant, making it
        suitable for integrity verification. The hash is computed over the
        ENCRYPTED data, so the server never sees plaintext.
    """
    return hashlib.sha256(data).digest()


def hash_nodes(left: bytes, right: bytes) -> bytes:
    """
    Compute SHA-256 hash of two child nodes concatenated.

    Args:
        left: Left child hash (32 bytes).
        right: Right child hash (32 bytes).

    Returns:
        32-byte SHA-256 hash of concatenation.

    Note:
        Order matters: hash(left + right) != hash(right + left)
        This prevents second-preimage attacks on the tree structure.
    """
    if len(left) != 32 or len(right) != 32:
        raise ValueError("Node hashes must be 32 bytes each")
    return hashlib.sha256(left + right).digest()


class MerkleTree:
    """
    Merkle Tree for integrity verification of memory blocks.

    Attributes:
        leaves: List of leaf hashes (SHA-256 of encrypted blocks).
        tree: Full tree structure (list of levels, bottom-up).
        root: Merkle Root hash (top of tree).

    Example:
        >>> leaf_hashes = [hash_leaf(b"block1"), hash_leaf(b"block2")]
        >>> tree = MerkleTree(leaf_hashes)
        >>> root = tree.build_tree()
        >>> proof = tree.get_proof(0)
        >>> MerkleTree.verify_proof(leaf_hashes[0], proof, root)
        True
    """

    def __init__(self, leaf_hashes: List[bytes]):
        """
        Initialize Merkle Tree with leaf hashes.

        Args:
            leaf_hashes: List of 32-byte SHA-256 hashes of encrypted blocks.

        Raises:
            ValueError: If leaf_hashes is empty or contains invalid hashes.
        """
        if not leaf_hashes:
            raise ValueError("Cannot create MerkleTree with empty leaf list")

        for i, h in enumerate(leaf_hashes):
            if len(h) != 32:
                raise ValueError(f"Leaf {i} hash must be 32 bytes, got {len(h)}")

        self.leaves = list(leaf_hashes)  # Copy to avoid mutation
        self.tree: List[List[bytes]] = []
        self.root: Optional[bytes] = None

    def build_tree(self) -> bytes:
        """
        Build the Merkle Tree from leaf hashes and compute the Root.

        Returns:
            32-byte Merkle Root hash.

        Algorithm:
            1. Start with leaf hashes as level 0.
            2. Pair adjacent hashes and compute parent hash.
            3. If odd number of nodes, duplicate the last one.
            4. Repeat until only one hash remains (the Root).

        Thread Safety:
            Caller should use portalocker for concurrent access safety.
        """
        if not self.leaves:
            raise ValueError("Cannot build tree with no leaves")

        # Level 0 = leaves
        current_level = list(self.leaves)
        self.tree = [current_level]

        # Build tree bottom-up
        while len(current_level) > 1:
            next_level = []

            # If odd number of nodes, duplicate the last one
            if len(current_level) % 2 == 1:
                current_level.append(current_level[-1])

            # Pair adjacent nodes
            for i in range(0, len(current_level), 2):
                parent = hash_nodes(current_level[i], current_level[i + 1])
                next_level.append(parent)

            self.tree.append(next_level)
            current_level = next_level

        # Root is the single remaining hash
        self.root = current_level[0]
        return self.root

    def get_proof(self, leaf_index: int) -> List[Dict[str, str]]:
        """
        Generate a Proof-of-Inclusion for a specific leaf.

        Args:
            leaf_index: Index of the leaf to prove (0-based).

        Returns:
            List of sibling hashes with position indicators.
            Format: [{"hash": base64_string, "position": "left"|"right"}, ...]

        Raises:
            IndexError: If leaf_index is out of range.
            ValueError: If tree hasn't been built yet.

        Usage:
            The proof allows anyone to verify that a specific leaf is part of
            the tree without knowing other leaves. To verify:
            1. Start with the leaf hash.
            2. For each step in the proof:
               - If position is "left", compute hash(sibling + current)
               - If position is "right", compute hash(current + sibling)
            3. Final result should match the Merkle Root.
        """
        if self.root is None:
            raise ValueError("Tree not built. Call build_tree() first.")

        if leaf_index < 0 or leaf_index >= len(self.leaves):
            raise IndexError(f"Leaf index {leaf_index} out of range [0, {len(self.leaves) - 1}]")

        proof = []
        index = leaf_index

        # Traverse from leaf to root (excluding root level)
        for level in range(len(self.tree) - 1):
            level_nodes = self.tree[level]

            # Handle odd-length levels (last node duplicated)
            if len(level_nodes) % 2 == 1:
                level_nodes = level_nodes + [level_nodes[-1]]

            # Determine sibling index
            if index % 2 == 0:
                # Current is left child, sibling is right
                sibling_index = index + 1
                position = "right"
            else:
                # Current is right child, sibling is left
                sibling_index = index - 1
                position = "left"

            sibling_hash = level_nodes[sibling_index]
            proof.append({
                "hash": base64.b64encode(sibling_hash).decode("ascii"),
                "position": position,
            })

            # Move to parent index
            index = index // 2

        return proof

    @staticmethod
    def verify_proof(
        leaf_hash: bytes,
        proof: List[Dict[str, str]],
        root: bytes
    ) -> bool:
        """
        Verify a Proof-of-Inclusion against a Merkle Root.

        Args:
            leaf_hash: 32-byte hash of the leaf to verify.
            proof: Proof generated by get_proof().
            root: Expected Merkle Root (32 bytes).

        Returns:
            True if the proof is valid (leaf is part of the tree with this root).
            False if the proof is invalid or tampered.

        Security Note:
            This function performs all computations locally. No network calls
            or external dependencies. Verification is deterministic and fast
            (<5ms for typical tree depths).

        Example:
            >>> leaf = hash_leaf(b"test data")
            >>> tree = MerkleTree([leaf, hash_leaf(b"other")])
            >>> root = tree.build_tree()
            >>> proof = tree.get_proof(0)
            >>> MerkleTree.verify_proof(leaf, proof, root)
            True
        """
        if len(leaf_hash) != 32:
            raise ValueError(f"leaf_hash must be 32 bytes, got {len(leaf_hash)}")
        if len(root) != 32:
            raise ValueError(f"root must be 32 bytes, got {len(root)}")

        current = leaf_hash

        for step in proof:
            sibling = base64.b64decode(step["hash"])
            position = step["position"]

            if position == "left":
                # Sibling is on the left
                current = hash_nodes(sibling, current)
            elif position == "right":
                # Sibling is on the right
                current = hash_nodes(current, sibling)
            else:
                raise ValueError(f"Invalid position: {position}")

        # Constant-time comparison to prevent timing attacks
        return _constant_time_compare(current, root)

    def get_root_hex(self) -> str:
        """Return Merkle Root as hexadecimal string."""
        if self.root is None:
            raise ValueError("Tree not built. Call build_tree() first.")
        return self.root.hex()

    def get_leaf_count(self) -> int:
        """Return number of leaves in the tree."""
        return len(self.leaves)

    def get_tree_depth(self) -> int:
        """Return depth of the tree (number of levels)."""
        return len(self.tree)


def _constant_time_compare(a: bytes, b: bytes) -> bool:
    """
    Compare two byte strings in constant time to prevent timing attacks.

    Args:
        a: First byte string.
        b: Second byte string.

    Returns:
        True if a == b, False otherwise.

    Security Note:
        Standard == operator short-circuits on first mismatch, leaking
        information about how many bytes match. This function always
        compares all bytes regardless of where mismatches occur.
    """
    if len(a) != len(b):
        return False

    result = 0
    for x, y in zip(a, b):
        result |= x ^ y

    return result == 0
