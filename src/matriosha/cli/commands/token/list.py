"""Token list command."""

from __future__ import annotations

import asyncio
import json

import typer
from rich.table import Table

from matriosha.cli.utils.context import get_global_context
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.managed.client import ManagedClientError

from .common import (
    _console,
    _emit_error,
    _list_tokens,
    _map_managed_error,
    _normalize_timestamp,
    _resolve_managed_token,
    _resolve_output_mode,
    _validate_backend_credentials,
)


def _profile_from_package_patch(ctx: typer.Context):
    import sys

    package = sys.modules.get("matriosha.cli.commands.token")
    patched_load_config = getattr(package, "load_config", load_config) if package is not None else load_config
    patched_get_active_profile = getattr(package, "get_active_profile", get_active_profile) if package is not None else get_active_profile
    return patched_get_active_profile(patched_load_config(), get_global_context(ctx).profile)


def register(app: typer.Typer) -> None:
    @app.command("list")
    def list_tokens(
        ctx: typer.Context,
        json_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """List existing agent access tokens."""

        json_output, plain = _resolve_output_mode(ctx, json_flag)
        _validate_backend_credentials(json_output, plain)

        try:
            profile = _profile_from_package_patch(ctx)
            token = _resolve_managed_token(profile.name, json_output, plain)
            endpoint = profile.managed_endpoint
            tokens = asyncio.run(_list_tokens(token=token, endpoint=endpoint))
        except ManagedClientError as exc:
            _emit_error(_map_managed_error(exc), json_output=json_output, plain=plain)

        normalized = [
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or "-"),
                "scope": str(item.get("scope") or "write"),
                "created_at": _normalize_timestamp(item.get("created_at")),
                "last_used": _normalize_timestamp(item.get("last_used")),
                "expires_at": _normalize_timestamp(item.get("expires_at")),
                "revoked": bool(item.get("revoked", False)),
            }
            for item in tokens
        ]

        if json_output:
            typer.echo(json.dumps(normalized, sort_keys=True))
            raise typer.Exit(code=0)

        if plain:
            for item in normalized:
                typer.echo(
                    " | ".join(
                        [
                            item["id"],
                            item["name"],
                            item["scope"],
                            item["created_at"],
                            item["last_used"],
                            item["expires_at"],
                            str(item["revoked"]).lower(),
                        ]
                    )
                )
            raise typer.Exit(code=0)

        table = Table(title="Managed Agent Tokens", show_header=True, header_style="bold accent")
        table.add_column("id", style="bold")
        table.add_column("name")
        table.add_column("scope")
        table.add_column("created_at")
        table.add_column("last_used")
        table.add_column("expires_at")
        table.add_column("revoked")

        for item in normalized:
            status_chip = "[danger]yes[/danger]" if item["revoked"] else "[success]no[/success]"
            scope_chip = {
                "read": "[accent]read[/accent]",
                "write": "[warning]write[/warning]",
                "admin": "[integrity]admin[/integrity]",
            }.get(item["scope"], item["scope"])
            table.add_row(
                item["id"],
                item["name"],
                scope_chip,
                item["created_at"],
                item["last_used"],
                item["expires_at"],
                status_chip,
            )

        _console().print(table)
        raise typer.Exit(code=0)

