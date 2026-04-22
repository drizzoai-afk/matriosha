"""CLI command group skeleton for phase 1."""

from __future__ import annotations

import typer

from cli.utils.context import get_global_context
from cli.utils.errors import EXIT_UNKNOWN

app = typer.Typer(help="Authentication commands for managed mode.", no_args_is_help=True)


def _not_implemented(ctx: typer.Context) -> None:
    _ = get_global_context(ctx)
    typer.echo("not implemented in phase 1")
    raise typer.Exit(code=EXIT_UNKNOWN)

@app.command("login")
def login(ctx: typer.Context) -> None:
    """Stub for `auth login`."""
    _not_implemented(ctx)

@app.command("logout")
def logout(ctx: typer.Context) -> None:
    """Stub for `auth logout`."""
    _not_implemented(ctx)

@app.command("whoami")
def whoami(ctx: typer.Context) -> None:
    """Stub for `auth whoami`."""
    _not_implemented(ctx)

@app.command("switch")
def switch(ctx: typer.Context) -> None:
    """Stub for `auth switch`."""
    _not_implemented(ctx)
