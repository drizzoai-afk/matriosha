"""Managed billing command package."""

from __future__ import annotations

import typer

from . import cancel as cancel_command
from . import status as status_command
from . import subscribe as subscribe_command
from . import upgrade as upgrade_command
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.managed.client import ManagedClient
from .common import SUBSCRIBE_POLL_SECONDS, SUBSCRIBE_TIMEOUT_SECONDS


def _sync_test_patchables() -> None:
    """Propagate package-level monkeypatches into billing implementation modules."""
    common_command.load_config = load_config
    common_command.get_active_profile = get_active_profile
    common_command.ManagedClient = ManagedClient


from . import common as common_command

app = typer.Typer(help="Managed subscription and billing operations.", no_args_is_help=True)

_sync_test_patchables()
status_command.register(app)
subscribe_command.register(app)
upgrade_command.register(app)
cancel_command.register(app)

__all__ = ["app", "load_config", "get_active_profile", "ManagedClient", "SUBSCRIBE_POLL_SECONDS", "SUBSCRIBE_TIMEOUT_SECONDS"]
