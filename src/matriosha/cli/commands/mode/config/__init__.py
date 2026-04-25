"""Mode configuration command group."""

from __future__ import annotations

import typer

from . import get, set

app = typer.Typer(help="View or change advanced mode settings.", no_args_is_help=True)

get.register(app)
set.register(app)
