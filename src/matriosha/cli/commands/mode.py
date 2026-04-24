"""Mode management commands."""

from __future__ import annotations

from datetime import datetime, timezone

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_USAGE
from matriosha.cli.utils.output import resolve_output
from matriosha.core.config import Profile, get_active_profile, load_config, save_config

app = typer.Typer(help="Mode management (local or managed).", no_args_is_help=True)
config_app = typer.Typer(help="Configuration flags.", no_args_is_help=True)


def _resolve_target_profile(
    cfg: object,
    override: str | None,
    *,
    create_if_missing: bool,
) -> Profile:
    if override and override not in cfg.profiles and create_if_missing:
        cfg.profiles[override] = Profile(
            name=override,
            mode="local",
            created_at=datetime.now(timezone.utc),
        )

    profile = get_active_profile(cfg, override)
    if override:
        cfg.active_profile = override
    return profile


@app.command("show")
def show(ctx: typer.Context) -> None:
    """Show active profile mode."""

    out = resolve_output(ctx)
    gctx = get_global_context(ctx)
    cfg = load_config()
    profile = _resolve_target_profile(cfg, gctx.profile, create_if_missing=False)

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


@app.command("set")
def set_mode(ctx: typer.Context, mode_value: str) -> None:
    """Set mode for the selected profile."""

    if mode_value not in {"local", "managed"}:
        raise typer.Exit(code=EXIT_USAGE)

    out = resolve_output(ctx)
    gctx = get_global_context(ctx)
    cfg = load_config()
    profile = _resolve_target_profile(cfg, gctx.profile, create_if_missing=True)
    profile.mode = mode_value
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


@config_app.command("set")
def set_config(ctx: typer.Context, key: str, value: str) -> None:
    """Set supported config key values (currently managed.auto_sync)."""

    out = resolve_output(ctx)
    gctx = get_global_context(ctx)
    cfg = load_config()

    if key != "managed.auto_sync":
        raise typer.Exit(code=EXIT_USAGE)

    lowered = value.strip().lower()
    if lowered not in {"true", "false"}:
        raise typer.Exit(code=EXIT_USAGE)

    cfg.managed.auto_sync = lowered == "true"
    save_config(cfg)

    payload = {
        "status": "ok",
        "operation": "mode.config.set",
        "data": {"key": key, "value": cfg.managed.auto_sync},
        "error": None,
    }
    if out.ctx.json_output:
        out.json(payload)
        return

    out.ok("config updated", {"key": key, "value": str(cfg.managed.auto_sync).lower()})


@config_app.command("get")
def get_config(ctx: typer.Context, key: str) -> None:
    """Get supported config key values (currently managed.auto_sync)."""

    out = resolve_output(ctx)
    cfg = load_config()

    if key != "managed.auto_sync":
        raise typer.Exit(code=EXIT_USAGE)

    value = cfg.managed.auto_sync

    payload = {
        "status": "ok",
        "operation": "mode.config.get",
        "data": {"key": key, "value": value},
        "error": None,
    }
    if out.ctx.json_output:
        out.json(payload)
        return

    out.ok("config", {"key": key, "value": str(value).lower()})


app.add_typer(config_app, name="config")
