"""CLI command group skeleton for phase 1."""

from __future__ import annotations

import typer

from cli.utils.errors import EXIT_UNKNOWN
from cli.utils.mode_guard import require_mode
from cli.utils.output import resolve_output

app = typer.Typer(help="Authentication commands for managed mode.", no_args_is_help=True)


@app.callback()
def callback(ctx: typer.Context) -> None:
    """Enforce managed mode for all auth commands."""

    require_mode("managed")(ctx)


def _not_implemented(ctx: typer.Context) -> None:
    out = resolve_output(ctx)
    out.error("not implemented in phase 1", exit_code=EXIT_UNKNOWN, operation="auth")


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
