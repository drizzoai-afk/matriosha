"""CLI command group skeleton for phase 1."""

from __future__ import annotations

import typer

from cli.utils.context import get_global_context
from cli.utils.errors import EXIT_UNKNOWN

app = typer.Typer(help="Vault key lifecycle and integrity commands.", no_args_is_help=True)


def _not_implemented(ctx: typer.Context) -> None:
    _ = get_global_context(ctx)
    typer.echo("not implemented in phase 1")
    raise typer.Exit(code=EXIT_UNKNOWN)

@app.command("init")
def init(ctx: typer.Context) -> None:
    """Stub for `vault init`."""
    _not_implemented(ctx)

@app.command("verify")
def verify(ctx: typer.Context) -> None:
    """Stub for `vault verify`."""
    _not_implemented(ctx)

@app.command("rotate")
def rotate(ctx: typer.Context) -> None:
    """Stub for `vault rotate`."""
    _not_implemented(ctx)

@app.command("export")
def export(ctx: typer.Context) -> None:
    """Stub for `vault export`."""
    _not_implemented(ctx)

@app.command("sync")
def sync(ctx: typer.Context) -> None:
    """Stub for `vault sync`."""
    _not_implemented(ctx)
