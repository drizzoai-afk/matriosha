"""Token inspect command."""

from __future__ import annotations

import asyncio
import json

import typer
from rich.table import Table

from matriosha.cli.utils.context import get_global_context
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.managed.client import ManagedClientError

from .common import (
    TokenCommandError,
    _console,
    _emit_error,
    _list_tokens,
    _map_managed_error,
    _normalize_timestamp,
    _resolve_managed_token,
    _resolve_output_mode,
    _resolve_token_by_prefix,
    _validate_backend_credentials,
)


def _profile_from_package_patch(ctx: typer.Context):
    import sys

    package = sys.modules.get("matriosha.cli.commands.token")
    patched_load_config = getattr(package, "load_config", load_config) if package is not None else load_config
    patched_get_active_profile = getattr(package, "get_active_profile", get_active_profile) if package is not None else get_active_profile
    return patched_get_active_profile(patched_load_config(), get_global_context(ctx).profile)


def register(app: typer.Typer) -> None:
    @app.command("inspect")
    def inspect(
        ctx: typer.Context,
        id_or_prefix: str = typer.Argument(..., help="Full token id or unique UUID prefix."),
        json_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Show safe details for one access token."""

        json_output, plain = _resolve_output_mode(ctx, json_flag)
        _validate_backend_credentials(json_output, plain)

        try:
            profile = _profile_from_package_patch(ctx)
            token = _resolve_managed_token(profile.name, json_output, plain)
            endpoint = profile.managed_endpoint
            tokens = asyncio.run(_list_tokens(token=token, endpoint=endpoint))
            selected = _resolve_token_by_prefix(tokens, id_or_prefix)
        except TokenCommandError as exc:
            _emit_error(exc, json_output=json_output, plain=plain)
        except ManagedClientError as exc:
            _emit_error(_map_managed_error(exc), json_output=json_output, plain=plain)

        payload = {
            "id": str(selected.get("id") or ""),
            "name": str(selected.get("name") or "-"),
            "scope": str(selected.get("scope") or "write"),
            "created_at": _normalize_timestamp(selected.get("created_at")),
            "last_used": _normalize_timestamp(selected.get("last_used")),
            "expires_at": _normalize_timestamp(selected.get("expires_at")),
            "revoked": bool(selected.get("revoked", False)),
            "token_hash": str(selected.get("token_hash") or "-"),
            "salt": str(selected.get("salt") or "-"),
        }

        if json_output:
            typer.echo(json.dumps(payload, sort_keys=True))
            raise typer.Exit(code=0)

        if plain:
            for key, value in payload.items():
                typer.echo(f"{key}: {value}")
            raise typer.Exit(code=0)

        table = Table(title="Token Metadata", show_header=True, header_style="bold accent")
        table.add_column("field", style="bold")
        table.add_column("value")
        for key, value in payload.items():
            table.add_row(key, str(value))
        _console().print(table)
        raise typer.Exit(code=0)

