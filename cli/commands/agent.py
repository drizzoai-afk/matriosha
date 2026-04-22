"""CLI command group skeleton for phase 1."""

from __future__ import annotations

import typer

from cli.utils.context import get_global_context
from cli.utils.errors import EXIT_UNKNOWN

app = typer.Typer(help="Connected agent management commands.", no_args_is_help=True)


def _not_implemented(ctx: typer.Context) -> None:
    _ = get_global_context(ctx)
    typer.echo("not implemented in phase 1")
    raise typer.Exit(code=EXIT_UNKNOWN)

@app.command("connect")
def connect(ctx: typer.Context) -> None:
    """Stub for `agent connect`."""
    _not_implemented(ctx)

@app.command("list")
def list(ctx: typer.Context) -> None:
    """Stub for `agent list`."""
    _not_implemented(ctx)

@app.command("remove")
def remove(ctx: typer.Context) -> None:
    """Stub for `agent remove`."""
    _not_implemented(ctx)
