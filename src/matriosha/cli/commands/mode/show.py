"""Show active profile mode command."""

from __future__ import annotations

import typer

from matriosha.cli.commands.mode.common import resolve_target_profile
from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.output import resolve_output
from matriosha.core.config import load_config


def show(ctx: typer.Context) -> None:
    """Show active profile mode."""

    out = resolve_output(ctx)
    gctx = get_global_context(ctx)
    cfg = load_config()
    profile = resolve_target_profile(cfg, gctx.profile, create_if_missing=False)

    payload = {
        "status": "ok",
        "operation": "mode.show",
        "data": {"active_profile": profile.name, "mode": profile.mode},
        "error": None,
    }
    if out.ctx.json_output:
        out.json(payload)
        return

    out.ok("mode", {"profile": profile.name, "mode": profile.mode})


def register(app: typer.Typer) -> None:
    app.command("show")(show)
