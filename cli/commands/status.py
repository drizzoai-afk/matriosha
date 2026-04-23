"""CLI command group skeleton for phase 1."""

from __future__ import annotations

import typer

from cli.utils.errors import EXIT_UNKNOWN
from cli.utils.output import resolve_output

app = typer.Typer(help="Show overall CLI/system status.", no_args_is_help=True)


@app.callback(invoke_without_command=True)
def callback(ctx: typer.Context) -> None:
    """Stub for `status`."""

    out = resolve_output(ctx)
    out.error("not implemented in phase 1", exit_code=EXIT_UNKNOWN, operation="status")
