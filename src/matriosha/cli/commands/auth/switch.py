"""Auth switch command."""

from __future__ import annotations

import json

import typer

from .common import Profile, load_config, save_config

def register(app: typer.Typer) -> None:
    @app.command("switch")
    def switch(
        ctx: typer.Context,
        profile_name: str = typer.Argument(..., help="Managed profile name to activate."),
        endpoint: str | None = typer.Option(None, "--endpoint", help="Managed endpoint override for this profile."),
    ) -> None:
        """Switch active profile (creates it if missing) and force managed mode."""

        cfg = load_config()
        profile = cfg.profiles.get(profile_name)
        if profile is None:
            profile = Profile(name=profile_name, mode="managed", managed_endpoint=endpoint)
        else:
            profile.mode = "managed"
            if endpoint:
                profile.managed_endpoint = endpoint

        cfg.profiles[profile_name] = profile
        cfg.active_profile = profile_name
        save_config(cfg)

        typer.echo(json.dumps({"status": "ok", "active_profile": profile_name, "mode": "managed"}, sort_keys=True))
        raise typer.Exit(code=0)

