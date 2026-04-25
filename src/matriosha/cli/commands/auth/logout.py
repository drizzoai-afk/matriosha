"""Auth logout command."""

from __future__ import annotations

import asyncio
import json
import os

import typer

from matriosha.cli.utils.context import get_global_context

from .common import AuthCommandError, ManagedClient, TokenStore, _emit_error, _profile_and_endpoint

def register(app: typer.Typer) -> None:
    @app.command("logout")
    def logout(
        ctx: typer.Context,
        json_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Log out of managed mode on this device."""

        gctx = get_global_context(ctx)
        json_output = gctx.json_output or json_flag

        try:
            profile, endpoint = _profile_and_endpoint(ctx)
            store = TokenStore(profile.name)
            payload = store.load() or {}
            token = str(payload.get("access_token") or os.getenv("MATRIOSHA_MANAGED_TOKEN") or "")

            if token:
                async def _best_effort_revoke() -> None:
                    try:
                        async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
                            await client._request("POST", "/managed/auth/logout")
                    except Exception:  # noqa: BLE001
                        return

                asyncio.run(_best_effort_revoke())

            store.clear()

            if json_output:
                typer.echo(json.dumps({"status": "ok", "operation": "auth.logout"}, sort_keys=True))
            else:
                typer.echo("✓ managed session cleared")
            raise typer.Exit(code=0)

        except AuthCommandError as exc:
            _emit_error(exc, json_output=json_output, plain=gctx.plain)

