"""Auth whoami/status commands."""

from __future__ import annotations

import asyncio
import json

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_AUTH, EXIT_MODE

from . import common
from .common import AuthCommandError, ManagedClient, ManagedClientError, _emit_error, _map_managed_error


def _run_whoami(ctx: typer.Context, *, json_flag: bool, operation: str) -> None:
    gctx = get_global_context(ctx)
    json_output = gctx.json_output or json_flag

    try:
        profile, endpoint = common._profile_and_endpoint(ctx)
        if profile.mode != "managed":
            raise AuthCommandError(
                "Auth commands require managed mode",
                category="MODE",
                code="MODE-601",
                exit_code=EXIT_MODE,
                fix="run `matriosha mode set managed`",
                debug=f"active mode={profile.mode}",
            )

        token = common.resolve_access_token(profile.name)
        if not token:
            raise AuthCommandError(
                "Managed session token missing",
                category="AUTH",
                code="AUTH-602",
                exit_code=EXIT_AUTH,
                fix="run `matriosha auth login`",
                debug="no token in env or token store",
            )

        async def _who() -> dict[str, str]:
            async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
                payload = await client.whoami()
                return {
                    "user_id": str(payload.get("user_id") or payload.get("id") or ""),
                    "email": str(payload.get("email") or ""),
                    "subscription": str(payload.get("subscription_status") or payload.get("subscription") or "unknown"),
                }

        data = asyncio.run(_who())

        payload = {
            "status": "ok",
            "operation": operation,
            "profile": profile.name,
            "mode": profile.mode,
            **data,
        }

        if json_output:
            typer.echo(json.dumps(payload, sort_keys=True))
        else:
            typer.echo(f"profile: {profile.name}")
            typer.echo(f"user_id: {data['user_id']}")
            typer.echo(f"email: {data['email'] or '-'}")
            typer.echo(f"subscription: {data['subscription']}")
        raise typer.Exit(code=0)

    except AuthCommandError as exc:
        _emit_error(exc, json_output=json_output, plain=gctx.plain)
    except ManagedClientError as exc:
        _emit_error(_map_managed_error(exc), json_output=json_output, plain=gctx.plain)


def register(app: typer.Typer) -> None:
    @app.command("whoami")
    def whoami(
        ctx: typer.Context,
        json_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Show which managed account is logged in."""

        _run_whoami(ctx, json_flag=json_flag, operation="auth.whoami")
