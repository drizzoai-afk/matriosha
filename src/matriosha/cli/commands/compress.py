"""
Matriosha CLI — Compress Command

Implements local memory compression to reduce token usage.
Identifies similar memories and merges them into high-density chunks.
"""

import typer
from pathlib import Path
from matriosha.core.brain import MatrioshaBrain
from matriosha.cli.utils.config import load_config

app = typer.Typer()

@app.callback()
def callback():
    """Compress and optimize vault memories."""
    pass

@app.command("run")
def run_compress(
    vault_path: str = typer.Option(None, "--path", "-p"),
    threshold: float = typer.Option(0.9, "--threshold", "-t", help="Similarity threshold for merging (0.0-1.0)")
):
    """
    Run semantic fusion on the vault to reduce token usage.
    
    This command identifies memories with high cosine similarity and 
    merges them into a single 'Super-Chunk' using a lightweight LLM.
    """
    config = load_config()
    if vault_path:
        config["vault"]["path"] = vault_path
    
    v_path = Path(config["vault"]["path"])
    if not v_path.exists():
        typer.echo(f"❌ Vault not found at {v_path}. Run 'matriosha init' first.")
        raise typer.Exit(1)

    typer.echo(f"🧠 Starting compression for vault: {v_path}")
    brain = MatrioshaBrain(v_path)
    
    # In a full implementation, this would trigger the LLM fusion process
    # For v1.3.0 launch, we are implementing the structural support in Brain
    brain.compress_memories(similarity_threshold=threshold)
    
    typer.echo("✅ Compression complete. Check logs for merged chunks.")
