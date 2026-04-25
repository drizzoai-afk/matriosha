"""Token generate command."""

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
    _SCOPE_CHOICES,
    _console,
    _emit_error,
    _generate_token,
    _map_managed_error,
    _normalize_timestamp,
    _parse_expiration_duration,
    _resolve_managed_token,
    _resolve_output_mode,
    _validate_backend_credentials,
)

def register(app: typer.Typer) -> None:
    @app.command("generate")
    def generate(
        ctx: typer.Context,
        name: str = typer.Argument(..., help="Friendly token name (example: ci-agent, nightly-sync)."),
        scope: str = typer.Option(
            "write",
            "--scope",
            help="Access scope: read | write | admin. Default: write.",
            show_default=True,
        ),
        expires: str | None = typer.Option(
            None,
            "--expires",
            help="Duration until expiry (examples: 30m, 1h, 7d, 30d, 2w).",
        ),
        json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    ) -> None:
        """Generate a managed agent token (token is shown once only)."""

        json_output, plain = _resolve_output_mode(ctx, json_flag)
        _validate_backend_credentials(json_output, plain)

        normalized_scope = scope.strip().lower()
        if normalized_scope not in _SCOPE_CHOICES:
            _emit_error(
                TokenCommandError(
                    "Invalid scope",
                    category="VAL",
                    code="VAL-505",
                    exit_code=EXIT_USAGE,
                    fix="use --scope read|write|admin",
                    debug=f"scope={scope}",
                ),
                json_output=json_output,
                plain=plain,
            )

        try:
            expires_at = _parse_expiration_duration(expires)
            profile = get_active_profile(load_config(), get_global_context(ctx).profile)
            token = _resolve_managed_token(profile.name, json_output, plain)
            endpoint = profile.managed_endpoint
            result = asyncio.run(_generate_token(token=token, endpoint=endpoint, name=name, scope=normalized_scope, expires_at=expires_at))
        except TokenCommandError as exc:
            _emit_error(exc, json_output=json_output, plain=plain)
        except ManagedClientError as exc:
            _emit_error(_map_managed_error(exc), json_output=json_output, plain=plain)

        token_value = str(result.get("token_plaintext") or result.get("token") or "")
        payload = {
            "id": str(result.get("id") or result.get("token_id") or ""),
            "token": token_value,
            "name": str(result.get("name") or name),
            "scope": str(result.get("scope") or normalized_scope),
            "expires_at": _normalize_timestamp(result.get("expires_at") or expires_at),
        }

        if json_output:
            typer.echo(json.dumps(payload, sort_keys=True))
            raise typer.Exit(code=0)

        if plain:
            typer.echo("STORE THIS TOKEN NOW — it will not be shown again.")
            typer.echo(f"id: {payload['id']}")
            typer.echo(f"name: {payload['name']}")
            typer.echo(f"scope: {payload['scope']}")
            typer.echo(f"expires_at: {payload['expires_at']}")
            typer.echo(f"token: {payload['token']}")
            raise typer.Exit(code=0)

        _console().print(
            Panel(
                f"[bold]name[/bold]       {payload['name']}\n"
                f"[bold]scope[/bold]      {payload['scope']}\n"
                f"[bold]expires_at[/bold] {payload['expires_at']}\n"
                f"[bold]token[/bold]      {payload['token']}\n\n"
                "[warning]STORE THIS TOKEN NOW — it will not be shown again.[/warning]",
                title="[bold warning]⚠ TOKEN REVEAL (ONE-TIME)[/bold warning]",
                border_style="warning",
                expand=False,
            )
        )
        raise typer.Exit(code=0)

