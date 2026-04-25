"""Managed billing command package."""

from __future__ import annotations

import typer

from . import cancel as cancel_command
from . import status as status_command
from . import subscribe as subscribe_command
from . import upgrade as upgrade_command

app = typer.Typer(help="Managed subscription and billing operations.", no_args_is_help=True)

status_command.register(app)
subscribe_command.register(app)
upgrade_command.register(app)
cancel_command.register(app)

__all__ = ["app"]
