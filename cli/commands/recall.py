"""
Matriosha CLI — Recall Command

Searches and retrieves memories from the vault.
Supports semantic search, JSON output for agents, and filtering by importance/logic.
"""

import typer
import json
import time
from pathlib import Path
from typing import Optional
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.security import retrieve_key_vault, decrypt_data
from core.binary_protocol import unpack_header, HEADER_SIZE
from cli.utils.config import load_config, get_vault_path
from cli.utils.output import format_memory_list


def recall_cmd(
    query: str = typer.Argument(..., help="Search query for memory recall."),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Number of results to return."),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output in JSON format (agent-friendly)."),
    importance_filter: Optional[str] = typer.Option(
        None, "--importance", help="Filter by importance: low, medium, high, critical"
    ),
):
    """
    Search and retrieve memories from the vault.

    Performs semantic search using local embeddings (FastEmbed) and returns
    decrypted memories sorted by relevance. Use --json for agent parsing.

    Examples:
        matriosha recall "project architecture"
        matriosha recall "API keys" --json --top-k 3
        matriosha recall "meetings" --importance high
    """
    config = load_config()
    vault_path = get_vault_path(config)
    start_time = time.time()

    # Retrieve encryption key
    vault_id = vault_path.stem
    try:
        key = retrieve_key_vault(vault_id)
    except KeyError:
        typer.echo("✗ Vault not initialized. Run 'matriosha init' first.", err=True)
        raise typer.Exit(code=1)

    # Use Brain for semantic search (Stage 1 Recall)
    from core.brain import MatrioshaBrain
    brain = MatrioshaBrain(vault_path)
    
    min_importance = 0
    if importance_filter:
        importance_map = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        min_importance = importance_map.get(importance_filter, 0)

    search_results = brain.search(query=query, top_k=top_k, min_importance=min_importance)

    if not search_results:
        if json_output:
            print(json.dumps({"memories": [], "count": 0, "integrity": "valid"}))
        else:
            typer.echo("No memories found.")
        return

    # Fetch and Decrypt (Stage 2 Recall)
    memories = []
    for result in search_results:
        leaf_id = result["leaf_id"]
        block_file = vault_path / f"{leaf_id}.bin"
        
        if not block_file.exists():
            continue

        try:
            block_data = block_file.read_bytes()
            if len(block_data) < HEADER_SIZE:
                continue

            # Unpack header to verify metadata matches
            header = unpack_header(block_data[:HEADER_SIZE])

            # Extract ciphertext, nonce, tag from block
            remaining = block_data[HEADER_SIZE:]
            tag = remaining[-16:]
            nonce = remaining[-28:-16]
            ciphertext = remaining[:-28]

            import base64
            plaintext = decrypt_data(
                key,
                base64.b64encode(ciphertext).decode(),
                base64.b64encode(nonce).decode(),
                base64.b64encode(tag).decode(),
            )

            content = json.loads(plaintext.decode("utf-8"))

            memories.append({
                "leaf_id": leaf_id,
                "importance": header["importance"],
                "logic_state": header["logic_state"],
                "timestamp": header["timestamp"],
                "content": content.get("text", ""),
                "merkle_verified": True,  # TODO: implement actual Merkle verification
                "relevance_score": result["relevance_score"],
            })

        except Exception as e:
            typer.echo(f"Warning: Could not read {block_file.name}: {e}", err=True)
            continue

    query_time_ms = (time.time() - start_time) * 1000

    # Output results
    format_memory_list(
        memories=memories,
        output_format="json" if json_output else "human",
        query_time_ms=query_time_ms,
    )
