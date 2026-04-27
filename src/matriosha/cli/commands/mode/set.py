"""Set active profile mode command."""

from __future__ import annotations

import typer
from typing import Literal, cast

from matriosha.cli.commands.mode.common import resolve_target_profile
from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_USAGE
from matriosha.cli.utils.output import resolve_output
from matriosha.core.config import load_config, save_config


def set_mode(ctx: typer.Context, mode_value: str = typer.Argument(..., help="Mode to use: local or managed.")) -> None:
    """Choose local or managed mode for this workspace."""

    if mode_value not in {"local", "managed"}:
        typer.echo("mode must be one of: local, managed", err=True)
        raise typer.Exit(code=EXIT_USAGE)
    mode_literal = cast(Literal["local", "managed"], mode_value)

    out = resolve_output(ctx)
    gctx = get_global_context(ctx)
    cfg = load_config()
    profile = resolve_target_profile(cfg, gctx.profile, create_if_missing=True)
    profile.mode = mode_literal
    cfg.profiles[profile.name] = profile
    cfg.active_profile = profile.name
    save_config(cfg)

    payload = {
        "status": "ok",
        "operation": "mode.set",
        "data": {"active_profile": profile.name, "mode": profile.mode},
        "error": None,
    }
    if out.ctx.json_output:
        out.json(payload)
        return

    out.ok("mode updated", {"profile": profile.name, "mode": mode_value})


def register(app: typer.Typer) -> None:
    app.command("set")(set_mode)
