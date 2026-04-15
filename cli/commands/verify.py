"""Matriosha CLI — Verify Command (Stub)"""

import typer


def verify_cmd(
    full: bool = typer.Option(False, "--full", "-f", help="Full verification (slower)"),
):
    """Verify Merkle tree integrity of vault."""
    typer.echo("⚠️  Verify not yet implemented. Coming in P3 integration.")
