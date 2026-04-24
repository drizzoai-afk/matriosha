"""Legacy export/import shim.

Use `matriosha vault export` for supported encrypted archive export.
"""

from __future__ import annotations

import typer

from matriosha.cli.utils.errors import EXIT_USAGE


app = typer.Typer(help="Legacy export/import helpers.", no_args_is_help=True)


@app.command("export")
def export_cmd() -> None:
    """Redirect to supported export command."""

    typer.echo("`export` moved to `matriosha vault export`.")
    raise typer.Exit(code=EXIT_USAGE)


@app.command("import")
def import_cmd() -> None:
    """Restore command placeholder with explicit guidance."""

    typer.echo("`import` is not exposed in this release; use managed sync + backups from vault export archives.")
    raise typer.Exit(code=EXIT_USAGE)
