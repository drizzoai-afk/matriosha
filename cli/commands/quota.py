"""CLI command group skeleton for phase 1."""

from __future__ import annotations

import typer

from cli.utils.errors import EXIT_UNKNOWN
from cli.utils.output import resolve_output

app = typer.Typer(help="Storage quota helpers.", no_args_is_help=True)


def _not_implemented(ctx: typer.Context) -> None:
    out = resolve_output(ctx)
    out.error("not implemented in phase 1", exit_code=EXIT_UNKNOWN, operation="quota")


@app.command("status")
def status(ctx: typer.Context) -> None:
    """Stub for `quota status`."""

    _not_implemented(ctx)
