"""CLI command group skeleton for phase 1."""

from __future__ import annotations

import typer

from cli.utils.context import get_global_context
from cli.utils.errors import EXIT_UNKNOWN

app = typer.Typer(help="Shell completion integration helpers.", no_args_is_help=True)


@app.callback(invoke_without_command=True)
def callback(ctx: typer.Context) -> None:
    """Stub for `completion`."""
    _ = get_global_context(ctx)
    typer.echo("not implemented in phase 1")
    raise typer.Exit(code=EXIT_UNKNOWN)
