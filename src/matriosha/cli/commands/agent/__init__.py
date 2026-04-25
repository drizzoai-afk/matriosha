"""Connected agent command package."""

from __future__ import annotations

import sys

import typer

from matriosha.cli.utils.mode_guard import require_mode

from . import connect as connect_command
from . import list as list_command
from . import remove as remove_command

app = typer.Typer(help="Connect or remove agents that use Matriosha memory.", no_args_is_help=True)


@app.callback()
def callback(ctx: typer.Context) -> None:
    """Enforce managed mode for all agent commands, except help rendering."""

    if ctx.resilient_parsing:
        return
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        return

    require_mode("managed")(ctx)


connect_command.register(app)
list_command.register(app)
remove_command.register(app)

__all__ = ["app"]
