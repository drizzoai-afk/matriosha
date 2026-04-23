"""CLI command group skeleton for phase 1."""

from __future__ import annotations

import typer

from cli.utils.context import get_global_context
from cli.utils.errors import EXIT_UNKNOWN
from cli.utils.mode_guard import require_mode

app = typer.Typer(help="Agent token lifecycle commands.", no_args_is_help=True)


@app.callback()
def callback(ctx: typer.Context) -> None:
    """Enforce managed mode for all token commands."""

    require_mode("managed")(ctx)


def _not_implemented(ctx: typer.Context) -> None:
    _ = get_global_context(ctx)
    typer.echo("not implemented in phase 1")
    raise typer.Exit(code=EXIT_UNKNOWN)

@app.command("generate")
def generate(ctx: typer.Context) -> None:
    """Stub for `token generate`."""
    _not_implemented(ctx)

@app.command("list")
def list(ctx: typer.Context) -> None:
    """Stub for `token list`."""
    _not_implemented(ctx)

@app.command("revoke")
def revoke(ctx: typer.Context) -> None:
    """Stub for `token revoke`."""
    _not_implemented(ctx)

@app.command("inspect")
def inspect(ctx: typer.Context) -> None:
    """Stub for `token inspect`."""
    _not_implemented(ctx)
