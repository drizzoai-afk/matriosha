"""Matriosha CLI — Export/Import Commands (Stubs)"""

import typer


def export_cmd(
    output: str = typer.Option("-", "--output", "-o", help="Output file (default: stdout)"),
):
    """Export vault to encrypted archive."""
    typer.echo("⚠️  Export not yet implemented. Coming in P6.")


def import_cmd(
    input_file: str = typer.Argument(..., help="Encrypted archive to import."),
):
    """Import vault from encrypted archive."""
    typer.echo("⚠️  Import not yet implemented. Coming in P6.")
