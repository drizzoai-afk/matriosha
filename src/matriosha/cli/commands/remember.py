"""
Matriosha CLI — Remember Command

Encrypts and stores a new memory block in the vault.
Supports importance levels, logic states, and tags.
"""

import typer
import time
import json
from pathlib import Path
from typing import Optional
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from matriosha.core.security import retrieve_key_vault, encrypt_data, hash_for_leaf_id  # noqa: E402
from matriosha.core.binary_protocol import pack_header, LOGIC_TRUE, LOGIC_FALSE, LOGIC_UNCERTAIN  # noqa: E402
from matriosha.core.binary_protocol import IMPORTANCE_LOW, IMPORTANCE_MEDIUM, IMPORTANCE_HIGH, IMPORTANCE_CRITICAL  # noqa: E402
from matriosha.cli.utils.config import load_config, get_vault_path  # noqa: E402


def remember_cmd(
    text: str = typer.Argument(..., help="Memory content to store."),
    importance: str = typer.Option(
        "medium", "--importance", "-i",
        help="Importance level: low, medium, high, critical"
    ),
    logic: str = typer.Option(
        "uncertain", "--logic", "-l",
        help="Logic state: true, false, uncertain"
    ),
    tags: Optional[str] = typer.Option(
        None, "--tags", "-t", help="Comma-separated tags (e.g., 'project,backend')"
    ),
):
    """
    Store a new memory in the vault.

    The memory is encrypted with AES-256-GCM and indexed with a 128-bit binary header.
    Metadata (importance, logic state) can be read without decryption for token-efficient filtering.

    Examples:
        matriosha remember "The project uses Supabase + Clerk"
        matriosha remember "API key is abc123" --importance critical --logic true
        matriosha remember "Meeting tomorrow" --tags calendar,work
    """
    config = load_config()
    vault_path = get_vault_path(config)

    # Map importance string to numeric value
    importance_map = {
        "low": IMPORTANCE_LOW,
        "medium": IMPORTANCE_MEDIUM,
        "high": IMPORTANCE_HIGH,
        "critical": IMPORTANCE_CRITICAL,
    }
    if importance not in importance_map:
        typer.echo(f"✗ Invalid importance: {importance}. Use: low, medium, high, critical", err=True)
        raise typer.Exit(code=1)
    importance_val = importance_map[importance]

    # Map logic string to numeric value
    logic_map = {
        "true": LOGIC_TRUE,
        "false": LOGIC_FALSE,
        "uncertain": LOGIC_UNCERTAIN,
    }
    if logic not in logic_map:
        typer.echo(f"✗ Invalid logic: {logic}. Use: true, false, uncertain", err=True)
        raise typer.Exit(code=1)
    logic_val = logic_map[logic]

    # Retrieve encryption key from keyring
    vault_id = vault_path.stem
    try:
        key = retrieve_key_vault(vault_id)
    except KeyError:
        typer.echo("✗ Vault not initialized. Run 'matriosha init' first.", err=True)
        raise typer.Exit(code=1)

    # Prepare memory content
    timestamp = int(time.time())
    memory_content = json.dumps({
        "text": text,
        "tags": tags.split(",") if tags else [],
        "created_at": timestamp,
    }).encode("utf-8")

    # Encrypt content
    encrypted = encrypt_data(key, memory_content)

    # Compute leaf ID hash from ciphertext + nonce + tag (excludes header to avoid circular dependency)
    import base64
    ciphertext_bytes = base64.b64decode(encrypted["ciphertext"])
    nonce_bytes = base64.b64decode(encrypted["nonce"])
    tag_bytes = base64.b64decode(encrypted["tag"])
    block_body = ciphertext_bytes + nonce_bytes + tag_bytes
    leaf_id_hash = hash_for_leaf_id(block_body)[:10]  # First 10 bytes (80 bits)

    # Pack binary header
    header = pack_header(
        version=1,
        logic_state=logic_val,
        importance=importance_val,
        timestamp=timestamp,
        leaf_id_hash=leaf_id_hash,
    )

    # Write binary block to vault (header + encrypted body: ciphertext + nonce + tag)
    block = header + ciphertext_bytes + nonce_bytes + tag_bytes

    leaf_id = leaf_id_hash.hex()
    block_file = vault_path / f"{leaf_id}.bin"
    block_file.write_bytes(block)

    # Update Brain Index (Semantic Search)
    try:
        from matriosha.core.brain import MatrioshaBrain
        brain = MatrioshaBrain(vault_path)
        brain.add_to_index(
            leaf_id=leaf_id,
            content=text,
            importance=importance_val,
            logic_state=logic_val,
            timestamp=timestamp
        )
    except Exception as e:
        typer.echo(f"Warning: Could not update search index: {e}", err=True)

    # Update Merkle root metadata (with file locking for concurrent safety)
    try:
        import hashlib
        import portalocker
        
        merkle_root = hashlib.sha256(block).hexdigest()
        merkle_meta_file = vault_path / ".merkle_root"
        lock_file = vault_path / ".merkle.lock"
        
        with portalocker.Lock(str(lock_file), timeout=10):
            merkle_meta_file.write_text(merkle_root)
    except Exception as e:
        typer.echo(f"Warning: Could not update Merkle root: {e}", err=True)

    typer.echo(f"✓ Memory stored: {leaf_id}")
    typer.echo(f"  Importance: {importance.capitalize()}")
    typer.echo(f"  Logic: {logic.capitalize()}")
    if tags:
        typer.echo(f"  Tags: {tags}")
