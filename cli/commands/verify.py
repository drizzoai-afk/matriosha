"""
Matriosha CLI — Verify Command

Verifies Merkle tree integrity of all memory blocks in the vault.
Detects tampering, corruption, and missing blocks.
"""

import typer
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.merkle import MerkleTree, hash_leaf  # noqa: E402
from core.binary_protocol import unpack_header, validate_header, HEADER_SIZE  # noqa: E402
from cli.utils.config import load_config, get_vault_path  # noqa: E402


def verify_cmd(
    full: bool = typer.Option(False, "--full", "-f", help="Full verification (validates headers too)"),
):
    """
    Verify Merkle tree integrity of all vault blocks.

    Scans all .bin files in the vault, builds a Merkle tree, and verifies
    each block's proof-of-inclusion. With --full, also validates binary headers.

    Examples:
        matriosha verify
        matriosha verify --full
    """
    config = load_config()
    vault_path = get_vault_path(config)

    block_files = sorted(vault_path.glob("*.bin"))

    if not block_files:
        typer.echo("⚠ No memory blocks found in vault.")
        return

    typer.echo(f"Verifying {len(block_files)} blocks...")

    errors = []
    leaf_hashes = []

    for bf in block_files:
        try:
            data = bf.read_bytes()

            # Minimum size check: 16-byte header + at least 28 bytes (12 nonce + 16 tag)
            if len(data) < HEADER_SIZE + 28:
                errors.append(f"  ✗ {bf.name}: Block too small ({len(data)} bytes)")
                continue

            # Header validation (if full mode)
            if full:
                if not validate_header(data[:HEADER_SIZE]):
                    errors.append(f"  ✗ {bf.name}: Invalid binary header")
                    continue

                header = unpack_header(data[:HEADER_SIZE])
                # Verify leaf_id_hash in header matches filename
                expected_leaf_id = header["leaf_id_hash"].hex()
                actual_leaf_id = bf.stem
                if expected_leaf_id != actual_leaf_id:
                    errors.append(f"  ✗ {bf.name}: Leaf ID mismatch (header={expected_leaf_id}, file={actual_leaf_id})")
                    continue

            leaf_hashes.append(hash_leaf(data))

        except Exception as e:
            errors.append(f"  ✗ {bf.name}: Read error: {e}")

    if not leaf_hashes:
        typer.echo("✗ No valid blocks to verify.")
        for err in errors:
            typer.echo(err, err=True)
        raise typer.Exit(code=1)

    # Build Merkle tree and verify all proofs
    tree = MerkleTree(leaf_hashes)
    root = tree.build_tree()

    proof_errors = 0
    for i in range(len(leaf_hashes)):
        proof = tree.get_proof(i)
        if not MerkleTree.verify_proof(leaf_hashes[i], proof, root):
            proof_errors += 1
            errors.append(f"  ✗ Block {i}: Merkle proof verification failed")

    # Report
    if errors:
        typer.echo(f"\n✗ Verification completed with {len(errors)} error(s):")
        for err in errors:
            typer.echo(err, err=True)
        raise typer.Exit(code=1)
    else:
        typer.echo(f"\n✓ All {len(block_files)} blocks verified")
        typer.echo(f"  Merkle Root: {root.hex()[:24]}...")
        typer.echo(f"  Tree depth:  {tree.get_tree_depth()}")
        typer.echo("  Integrity:   VALID")
