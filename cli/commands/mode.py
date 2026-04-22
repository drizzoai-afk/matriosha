"""Mode management commands."""

from __future__ import annotations

from datetime import datetime, timezone
import json

import typer

from cli.utils.context import get_global_context
from cli.utils.errors import EXIT_USAGE
from core.config import MatrioshaConfig, Profile, get_active_profile, load_config, save_config

app = typer.Typer(help="Mode management (local or managed).", no_args_is_help=True)


def _resolve_target_profile(
    cfg: MatrioshaConfig,
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

    gctx = get_global_context(ctx)
    cfg = load_config()
    profile = _resolve_target_profile(cfg, gctx.profile, create_if_missing=False)

    if gctx.json_output:
        typer.echo(
            json.dumps(
                {
                    "status": "ok",
                    "operation": "mode.show",
                    "data": {"active_profile": profile.name, "mode": profile.mode},
                    "error": None,
                }
            )
        )
        return

    typer.echo(f"profile: {profile.name}")
    typer.echo(f"mode: {profile.mode}")


@app.command("set")
def set_mode(ctx: typer.Context, mode_value: str) -> None:
    """Set mode for the selected profile."""

    if mode_value not in {"local", "managed"}:
        raise typer.Exit(code=EXIT_USAGE)

    gctx = get_global_context(ctx)
    cfg = load_config()
    profile = _resolve_target_profile(cfg, gctx.profile, create_if_missing=True)
    profile.mode = mode_value
    cfg.profiles[profile.name] = profile
    cfg.active_profile = profile.name
    save_config(cfg)

    if gctx.json_output:
        typer.echo(
            json.dumps(
                {
                    "status": "ok",
                    "operation": "mode.set",
                    "data": {"active_profile": profile.name, "mode": profile.mode},
                    "error": None,
                }
            )
        )
        return

    typer.echo(f"mode set to {mode_value} for profile '{profile.name}'")
