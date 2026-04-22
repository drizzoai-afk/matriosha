"""CLI command group skeleton for phase 1."""

from __future__ import annotations

import typer

from cli.utils.context import get_global_context
from cli.utils.errors import EXIT_UNKNOWN

app = typer.Typer(help="Managed subscription and billing operations.", no_args_is_help=True)


def _not_implemented(ctx: typer.Context) -> None:
    _ = get_global_context(ctx)
    typer.echo("not implemented in phase 1")
    raise typer.Exit(code=EXIT_UNKNOWN)

@app.command("status")
def status(ctx: typer.Context) -> None:
    """Stub for `billing status`."""
    _not_implemented(ctx)

@app.command("subscribe")
def subscribe(ctx: typer.Context) -> None:
    """Stub for `billing subscribe`."""
    _not_implemented(ctx)

@app.command("upgrade")
def upgrade(ctx: typer.Context) -> None:
    """Stub for `billing upgrade`."""
    _not_implemented(ctx)

@app.command("cancel")
def cancel(ctx: typer.Context) -> None:
    """Stub for `billing cancel`."""
    _not_implemented(ctx)
