"""CLI command group skeleton for phase 1."""

from __future__ import annotations

import typer

from cli.utils.context import get_global_context
from cli.utils.errors import EXIT_UNKNOWN

app = typer.Typer(help="Mode management (local or managed).", no_args_is_help=True)


def _not_implemented(ctx: typer.Context) -> None:
    _ = get_global_context(ctx)
    typer.echo("not implemented in phase 1")
    raise typer.Exit(code=EXIT_UNKNOWN)

@app.command("show")
def show(ctx: typer.Context) -> None:
    """Stub for `mode show`."""
    _not_implemented(ctx)

@app.command("set")
def set(ctx: typer.Context) -> None:
    """Stub for `mode set`."""
    _not_implemented(ctx)
