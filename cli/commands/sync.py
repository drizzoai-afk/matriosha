"""Legacy sync command shim.

Use `matriosha vault sync` for production managed/local synchronization.
"""

from __future__ import annotations

import typer

from cli.utils.errors import EXIT_USAGE


app = typer.Typer(help="Legacy sync helpers.", no_args_is_help=True)


@app.callback(invoke_without_command=True)
def sync_cmd() -> None:
    """Redirect users to the supported vault sync command."""

    typer.echo("`sync` command group is deprecated; use `matriosha vault sync` instead.")
    raise typer.Exit(code=EXIT_USAGE)
