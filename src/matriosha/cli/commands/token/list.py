"""Token list command."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.local_tokens import list_local_agent_tokens
from matriosha.core.managed.client import ManagedClientError

from .common import (
    _console,
    _emit_error,
    _enforce_token_mode,
    _list_tokens,
    _map_managed_error,
    _normalize_timestamp,
    _resolve_managed_token,
    _resolve_output_mode,
)


def _profile_from_package_patch(ctx: typer.Context):
    import sys

    package = sys.modules.get("matriosha.cli.commands.token")
    patched_load_config = (
        getattr(package, "load_config", load_config) if package is not None else load_config
    )
    patched_get_active_profile = (
        getattr(package, "get_active_profile", get_active_profile)
        if package is not None
        else get_active_profile
    )
    return patched_get_active_profile(patched_load_config(), get_global_context(ctx).profile)


def register(app: typer.Typer) -> None:
    @app.command("list")
    def list_tokens(
        ctx: typer.Context,
        json_flag: bool = typer.Option(
            False, "--json", help="Show JSON output for scripts and automation."
        ),
        local: bool = typer.Option(False, "--local", help="List local-only agent tokens."),
    ) -> None:
        """List existing agent access tokens."""

        json_output, plain = _resolve_output_mode(ctx, json_flag)

        try:
            profile = _profile_from_package_patch(ctx)
            use_local = local or profile.mode == "local"
            if use_local:
                tokens = list_local_agent_tokens(profile.name)
            else:
                _enforce_token_mode(ctx)
                token = _resolve_managed_token(profile.name, json_output, plain)
                endpoint = profile.managed_endpoint
                tokens = asyncio.run(_list_tokens(token=token, endpoint=endpoint))
        except ManagedClientError as exc:
            _emit_error(_map_managed_error(exc), json_output=json_output, plain=plain)

        normalized: list[dict[str, Any]] = [
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

        if not normalized:
            typer.echo(
                "No local agent tokens found." if use_local else "No managed agent tokens found."
            )
            raise typer.Exit(code=0)

        console = _console()
        console.print(
            "[accent]Local Agent Tokens[/accent]"
            if use_local
            else "[accent]Managed Agent Tokens[/accent]"
        )
        console.print()
        for index, item in enumerate(normalized, start=1):
            if index > 1:
                console.print()
            scope = str(item["scope"])
            scope_style = {
                "read": "accent",
                "write": "warning",
                "admin": "integrity",
            }.get(scope, "")
            revoked_style = "danger" if item["revoked"] else "success"
            revoked_text = "yes" if item["revoked"] else "no"
            scope_text = (
                "[{}]{}[/{}]".format(scope_style, scope, scope_style) if scope_style else scope
            )
            console.print(f"[accent]token {index}:[/accent]")
            console.print(
                "  [muted]id:        [/muted] [integrity]{}[/integrity]".format(item["id"])
            )
            console.print("  [muted]name:      [/muted] {}".format(item["name"]))
            console.print("  [muted]scope:     [/muted] {}".format(scope_text))
            console.print("  [muted]created_at:[/muted] {}".format(item["created_at"]))
            console.print("  [muted]last_used: [/muted] {}".format(item["last_used"]))
            console.print("  [muted]expires_at:[/muted] {}".format(item["expires_at"]))
            console.print(
                "  [muted]revoked:   [/muted] [{}]{}[/{}]".format(
                    revoked_style, revoked_text, revoked_style
                )
            )
        raise typer.Exit(code=0)
