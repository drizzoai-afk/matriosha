"""Auth refresh command."""

from __future__ import annotations

import json

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_AUTH
from matriosha.core.managed.auth import TokenRefreshError, refresh_profile_tokens

from .common import AuthCommandError, _emit_error, _profile_and_endpoint


def register(app: typer.Typer) -> None:
    @app.command("refresh")
    def refresh(
        ctx: typer.Context,
        json_flag: bool = typer.Option(
            False, "--json", help="Show JSON output for scripts and automation."
        ),
    ) -> None:
        """Refresh managed session tokens using the stored refresh token."""

        gctx = get_global_context(ctx)
        json_output = gctx.json_output or json_flag

        try:
            profile, endpoint = _profile_and_endpoint(ctx)
            payload = refresh_profile_tokens(profile.name, force=True, endpoint=endpoint)
            response = {
                "status": "ok",
                "operation": "auth.refresh",
                "profile": profile.name,
                "expires_at": payload.get("expires_at"),
                "token_type": payload.get("token_type") or "bearer",
            }
            if json_output:
                typer.echo(json.dumps(response, sort_keys=True))
            else:
                typer.echo("✓ managed session refreshed")
                typer.echo(f"profile: {profile.name}")
                typer.echo(f"expires_at: {response['expires_at'] or '-'}")
            raise typer.Exit(code=0)
        except TokenRefreshError as exc:
            _emit_error(
                AuthCommandError(
                    str(exc),
                    category="AUTH",
                    code="AUTH-604",
                    exit_code=EXIT_AUTH,
                    fix="run `matriosha auth login` if refresh token is expired or missing",
                    debug="managed-token-refresh",
                ),
                json_output=json_output,
                plain=gctx.plain,
            )
