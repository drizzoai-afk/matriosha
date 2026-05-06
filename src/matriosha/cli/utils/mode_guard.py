"""Mode enforcement helpers for Typer commands."""

from __future__ import annotations

from typing import Literal

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_MODE
from matriosha.core.config import get_active_profile, load_config


def require_mode(required: Literal["local", "managed"]):
    """Return a Typer dependency that enforces the active profile mode."""

    def _dependency(ctx: typer.Context) -> None:
        gctx = get_global_context(ctx)
        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)
        if profile.mode != required:
            typer.echo(
                f"this command requires {required} mode; run `matriosha mode set {required}`"
            )
            raise typer.Exit(code=EXIT_MODE)

    return _dependency
