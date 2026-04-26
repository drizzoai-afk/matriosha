"""Token revoke command."""

from __future__ import annotations

import asyncio
import json

import typer
from rich.panel import Panel

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_USAGE
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.managed.client import ManagedClientError

from .common import (
    TokenCommandError,
    _console,
    _emit_error,
    _list_tokens,
    _map_managed_error,
    _resolve_managed_token,
    _resolve_output_mode,
    _resolve_token_by_prefix,
    _revoke_token,
    _validate_backend_credentials,
)


def _profile_from_package_patch(ctx: typer.Context):
    import sys

    package = sys.modules.get("matriosha.cli.commands.token")
    patched_load_config = getattr(package, "load_config", load_config) if package is not None else load_config
    patched_get_active_profile = getattr(package, "get_active_profile", get_active_profile) if package is not None else get_active_profile
    return patched_get_active_profile(patched_load_config(), get_global_context(ctx).profile)


def register(app: typer.Typer) -> None:
    @app.command("revoke")
    def revoke(
        ctx: typer.Context,
        id_or_prefix: str = typer.Argument(..., help="Full token id or unique UUID prefix."),
        yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt and revoke immediately."),
        json_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Disable an agent access token."""

        json_output, plain = _resolve_output_mode(ctx, json_flag)
        _validate_backend_credentials(json_output, plain)

        try:
            profile = _profile_from_package_patch(ctx)
            token = _resolve_managed_token(profile.name, json_output, plain)
            endpoint = profile.managed_endpoint
            tokens = asyncio.run(_list_tokens(token=token, endpoint=endpoint))
            selected = _resolve_token_by_prefix(tokens, id_or_prefix)
            token_id = str(selected.get("id") or "")

            if not yes:
                confirmed = typer.confirm(f"Revoke token '{selected.get('name', token_id)}' ({token_id})?", default=False)
                typer.echo()
                if not confirmed:
                    raise TokenCommandError(
                        "Revocation canceled by user",
                        category="VAL",
                        code="VAL-506",
                        exit_code=EXIT_USAGE,
                        fix="rerun with --yes to skip confirmation",
                        debug="confirmation declined",
                    )

            asyncio.run(_revoke_token(token=token, endpoint=endpoint, token_id=token_id))
        except TokenCommandError as exc:
            _emit_error(exc, json_output=json_output, plain=plain)
        except ManagedClientError as exc:
            _emit_error(_map_managed_error(exc), json_output=json_output, plain=plain)

        payload = {"status": "ok", "id": token_id, "revoked": True}
        if json_output:
            typer.echo(json.dumps(payload, sort_keys=True))
            raise typer.Exit(code=0)

        if plain:
            typer.echo(f"revoked token {token_id}")
            raise typer.Exit(code=0)

        _console().print(
            Panel(
                f"Token revoked successfully.\n\n[bold]id[/bold]: {token_id}",
                title="[bold success]✓ TOKEN REVOKED[/bold success]",
                border_style="success",
                expand=False,
            )
        )
        raise typer.Exit(code=0)

