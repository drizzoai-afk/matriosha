"""Profile discovery command group."""

from __future__ import annotations

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.output import resolve_output
from matriosha.core.config import load_config

app = typer.Typer(
    help=(
        "Show saved workspaces/profiles. "
        "Use global --profile NAME with `mode set local|managed` to create or switch profiles."
    ),
    no_args_is_help=True,
)


@app.command("show")
def show(ctx: typer.Context) -> None:
    """Show the selected profile and mode."""

    out = resolve_output(ctx)
    gctx = get_global_context(ctx)
    cfg = load_config()
    profile_name = gctx.profile or cfg.active_profile
    profile = cfg.profiles.get(profile_name)

    data = {
        "active_profile": cfg.active_profile,
        "selected_profile": profile_name,
        "mode": profile.mode if profile is not None else None,
        "exists": profile is not None,
    }
    payload = {"status": "ok", "operation": "profile.show", "data": data, "error": None}

    if out.ctx.json_output:
        out.json(payload)
        return

    if profile is None:
        out.warn(f"profile not found: {profile_name}. Next: matriosha --profile {profile_name} mode set local")
        return

    out.ok(
        "profile",
        {
            "active": cfg.active_profile,
            "selected": profile.name,
            "mode": profile.mode,
        },
    )


@app.command("list")
def list_profiles(ctx: typer.Context) -> None:
    """List saved profiles."""

    out = resolve_output(ctx)
    cfg = load_config()
    rows = [
        {
            "name": profile.name,
            "mode": profile.mode,
            "active": profile.name == cfg.active_profile,
            "managed_endpoint": profile.managed_endpoint,
        }
        for profile in sorted(cfg.profiles.values(), key=lambda p: p.name)
    ]
    payload = {
        "status": "ok",
        "operation": "profile.list",
        "data": {"active_profile": cfg.active_profile, "profiles": rows},
        "error": None,
    }

    if out.ctx.json_output:
        out.json(payload)
        return

    if not rows:
        out.warn("no profiles found. Next: matriosha mode set local")
        return

    lines = {}
    for row in rows:
        marker = "*" if row["active"] else " "
        lines[f"{marker} {row['name']}"] = row["mode"]

    out.ok("profiles", lines)
