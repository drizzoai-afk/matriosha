"""Vault command package."""

from __future__ import annotations

import signal

import platformdirs

import typer

from matriosha.core.managed.client import ManagedClient
from matriosha.core.managed.sync import SyncEngine
from . import export as export_command
from . import init as init_command
from . import rotate as rotate_command
from . import sync as sync_command
from . import verify as verify_command

app = typer.Typer(help="Vault key lifecycle and integrity commands.", no_args_is_help=True)

init_command.register(app)
verify_command.register(app)
rotate_command.register(app)
export_command.register(app)
sync_command.register(app)

__all__ = ["app", "platformdirs", "signal", "ManagedClient", "SyncEngine"]
