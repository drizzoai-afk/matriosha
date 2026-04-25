"""Vault command package."""

from __future__ import annotations

import os
import signal

import platformdirs

import typer

from matriosha.core.managed.client import ManagedClient
from matriosha.core.managed.key_custody import upload_wrapped_key
from matriosha.core.managed.sync import SyncEngine
from . import export as export_command
from . import init as init_command
from . import rotate as rotate_command
from . import sync as sync_command
from . import verify as verify_command

def _sync_test_patchables() -> None:
    """Propagate package-level monkeypatches into vault implementation modules."""
    rotate_command.os = os
    rotate_command.ManagedClient = ManagedClient
    rotate_command.upload_wrapped_key = upload_wrapped_key


app = typer.Typer(help="Vault key lifecycle and integrity commands.", no_args_is_help=True)

_sync_test_patchables()
init_command.register(app)
verify_command.register(app)
rotate_command.register(app)
export_command.register(app)
sync_command.register(app)

__all__ = ["app", "platformdirs", "os", "signal", "ManagedClient", "SyncEngine", "upload_wrapped_key"]
