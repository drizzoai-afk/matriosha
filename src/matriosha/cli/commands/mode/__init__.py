"""Mode management command group."""

from __future__ import annotations

import typer

from . import config, set, show

app = typer.Typer(
    help="Choose local mode or managed mode. Managed mode requires `auth login` first.",
    no_args_is_help=True,
)

show.register(app)
set.register(app)
app.add_typer(config.app, name="config")
