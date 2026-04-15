"""
Matriosha CLI — Main Entry Point

Typer-based CLI for seamless memory management.
Commands: init, remember, recall, sync, verify, export, import
"""

import typer
from typing import Optional

from cli.commands import init, remember, recall, sync, verify, export_import

app = typer.Typer(
    name="matriosha",
    help="Secure Agentic Memory Layer — Binary standard for AI memory",
    add_completion=True,
)

# Register commands
app.command()(init.init_cmd)
app.command()(remember.remember_cmd)
app.command()(recall.recall_cmd)
app.command()(sync.sync_cmd)
app.command()(verify.verify_cmd)
app.command(name="export")(export_import.export_cmd)
app.command(name="import")(export_import.import_cmd)


@app.callback()
def callback(
    version: bool = typer.Option(
        False, "--version", "-v", help="Show version and exit."
    ),
):
    """Matriosha CLI — Secure Agentic Memory Layer"""
    if version:
        from cli import __version__
        typer.echo(f"Matriosha v{__version__}")
        raise typer.Exit()


if __name__ == "__main__":
    app()
