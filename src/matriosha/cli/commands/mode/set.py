"""Set active profile mode command."""

from __future__ import annotations

import typer
from typing import Literal, cast

from matriosha.cli.commands.mode.common import resolve_target_profile
from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_AUTH, EXIT_USAGE
from matriosha.cli.utils.output import resolve_output
from matriosha.core.config import load_config, save_config
from matriosha.core.managed.auth import resolve_access_token
from matriosha.core.managed.client import AuthError


def set_mode(
    ctx: typer.Context,
    mode_value: str = typer.Argument(..., help="Mode to use: local or managed."),
    auto_sync: bool | None = typer.Option(
        None,
        "--auto-sync/--no-auto-sync",
        help="Enable or disable best-effort background sync for managed memory writes.",
    ),
) -> None:
    """Choose local or managed mode and optionally toggle managed auto-sync."""

    if mode_value not in {"local", "managed"}:
        typer.echo("mode must be one of: local, managed", err=True)
        raise typer.Exit(code=EXIT_USAGE)
    mode_literal = cast(Literal["local", "managed"], mode_value)

    out = resolve_output(ctx)
    gctx = get_global_context(ctx)
    cfg = load_config()

    try:
        profile = resolve_target_profile(
            cfg,
            gctx.profile,
            create_if_missing=True,
        )
    except ValueError as exc:
        out.error(str(exc), exit_code=EXIT_USAGE)
        return

    if mode_literal == "managed":
        try:
            token = resolve_access_token(profile.name)
        except AuthError as exc:
            out.error(
                "managed session token missing; run `matriosha auth login` first",
                exit_code=EXIT_AUTH,
                stable_code="AUTH-212",
                debug_hint=str(exc),
            )
            return
        if not token:
            out.error(
                "managed session token missing; run `matriosha auth login` first",
                exit_code=EXIT_AUTH,
                stable_code="AUTH-212",
            )
            return

    profile.mode = mode_literal
    if auto_sync is not None:
        cfg.managed.auto_sync = auto_sync
    cfg.profiles[profile.name] = profile
    cfg.active_profile = profile.name
    save_config(cfg)

    payload = {
        "status": "ok",
        "operation": "mode.set",
        "data": {"active_profile": profile.name, "mode": profile.mode, "auto_sync": cfg.managed.auto_sync},
        "error": None,
    }
    if out.ctx.json_output:
        out.json(payload)
        return

    out.ok("mode updated", {"profile": profile.name, "mode": mode_value, "auto_sync": cfg.managed.auto_sync})


def register(app: typer.Typer) -> None:
    app.command("set")(set_mode)
