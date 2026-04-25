"""Managed authentication command package."""

from __future__ import annotations

import typer

from matriosha.cli.utils.mode_guard import require_mode

from . import login as login_command
from . import logout as logout_command
from . import switch as switch_command
from . import whoami as whoami_command

app = typer.Typer(
    help=(
        "Log in or out of managed mode.\n\n"
        "Login opens a secure device flow and sets up managed encryption automatically on first use."
    ),
    no_args_is_help=True,
)


@app.callback()
def callback(ctx: typer.Context) -> None:
    """Enforce managed mode for auth commands."""

    require_mode("managed")(ctx)


login_command.register(app)
logout_command.register(app)
whoami_command.register(app)
switch_command.register(app)

__all__ = ["app"]
