"""CLI command group skeleton for phase 1."""

from __future__ import annotations

import typer

from cli.utils.context import get_global_context
from cli.utils.errors import EXIT_UNKNOWN

app = typer.Typer(help="Encrypted memory operations.", no_args_is_help=True)


def _not_implemented(ctx: typer.Context) -> None:
    _ = get_global_context(ctx)
    typer.echo("not implemented in phase 1")
    raise typer.Exit(code=EXIT_UNKNOWN)

@app.command("remember")
def remember(ctx: typer.Context) -> None:
    """Stub for `memory remember`."""
    _not_implemented(ctx)

@app.command("recall")
def recall(ctx: typer.Context) -> None:
    """Stub for `memory recall`."""
    _not_implemented(ctx)

@app.command("search")
def search(ctx: typer.Context) -> None:
    """Stub for `memory search`."""
    _not_implemented(ctx)

@app.command("list")
def list(ctx: typer.Context) -> None:
    """Stub for `memory list`."""
    _not_implemented(ctx)

@app.command("delete")
def delete(ctx: typer.Context) -> None:
    """Stub for `memory delete`."""
    _not_implemented(ctx)

@app.command("compress")
def compress(ctx: typer.Context) -> None:
    """Stub for `memory compress`."""
    _not_implemented(ctx)

@app.command("decompress")
def decompress(ctx: typer.Context) -> None:
    """Stub for `memory decompress`."""
    _not_implemented(ctx)
