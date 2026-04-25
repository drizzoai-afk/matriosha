"""Managed agent-token command package."""

from __future__ import annotations

import sys

import typer

from matriosha.cli.utils.mode_guard import require_mode
from matriosha.core.config import get_active_profile, load_config


def _sync_test_patchables() -> None:
    """Propagate package-level monkeypatches into token implementation modules."""
    for module in (generate_command, list_command, revoke_command, inspect_command):
        module.load_config = load_config
        module.get_active_profile = get_active_profile


from . import generate as generate_command
from . import inspect as inspect_command
from . import list as list_command
from . import revoke as revoke_command

app = typer.Typer(
    help=(
        "Create and manage access tokens for agents.\n\n"
        "Scopes:\n"
        "  - read  : recall/search/list only\n"
        "  - write : read + remember/delete/sync operations\n"
        "  - admin : full managed workspace access for automation\n\n"
        "Expiration format for --expires:\n"
        "  <number><unit> where unit is m, h, d, or w (examples: 30m, 1h, 7d, 2w)."
    ),
    no_args_is_help=True,
)


@app.callback()
def callback(ctx: typer.Context) -> None:
    """Enforce managed mode for all token commands, except help rendering."""

    if ctx.resilient_parsing:
        return
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        return

    require_mode("managed")(ctx)


_sync_test_patchables()
generate_command.register(app)
list_command.register(app)
revoke_command.register(app)
inspect_command.register(app)

__all__ = ["app", "load_config", "get_active_profile"]
