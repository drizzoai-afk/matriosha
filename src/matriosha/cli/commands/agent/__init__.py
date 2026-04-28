"""Connected agent command package."""

from __future__ import annotations

import typer

from . import connect as connect_command
from . import list as list_command
from . import remove as remove_command

app = typer.Typer(help="Connect or remove agents that use Matriosha memory.", no_args_is_help=True)

connect_command.register(app)
list_command.register(app)
remove_command.register(app)

__all__ = ["app"]
