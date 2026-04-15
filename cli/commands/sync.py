"""Matriosha CLI — Sync Command (Stub)"""

import typer


def sync_cmd(
    mode: str = typer.Option("hybrid", "--mode", "-m", help="Sync mode: local, managed, hybrid"),
):
    """Sync vault with Supabase cloud storage."""
    typer.echo("⚠️  Sync not yet implemented. Coming in P5.")
