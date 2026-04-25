"""Shell completion command group."""

from __future__ import annotations

import typer

from . import bash, fish, install, zsh

app = typer.Typer(help="Set up Terminal command suggestions.", no_args_is_help=True)

bash.register(app)
zsh.register(app)
fish.register(app)
install.register(app)
