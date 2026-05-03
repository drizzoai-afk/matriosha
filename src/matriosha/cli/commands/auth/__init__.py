"""Managed authentication command package."""

from __future__ import annotations

import sys

import typer

from matriosha.cli.utils.mode_guard import require_mode

from . import login as login_command
from . import logout as logout_command
from . import refresh as refresh_command
from . import status as status_command
from . import switch as switch_command
from . import whoami as whoami_command

app = typer.Typer(
    help=(
        "Log in or out of managed mode.\n\n"
        "Login uses email OTP and sets up managed encryption automatically on first use."
    ),
    no_args_is_help=True,
)


@app.callback()
def callback(ctx: typer.Context) -> None:
    """Enforce managed mode for auth commands, except help/login bootstrap."""

    if ctx.resilient_parsing:
        return
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        return

    # `auth login` is the bootstrap path that creates/refreshes managed auth.
    # Requiring managed mode before login creates a deadlock for new profiles:
    # `mode set managed` needs a token, while `auth login` needs managed mode.
    invoked = ctx.invoked_subcommand or (sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "auth" else None)
    if invoked == "login":
        return

    require_mode("managed")(ctx)


login_command.register(app)
logout_command.register(app)
refresh_command.register(app)
whoami_command.register(app)
status_command.register(app)
switch_command.register(app)

__all__ = ["app"]
