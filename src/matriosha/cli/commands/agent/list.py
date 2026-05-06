"""Agent list command."""

from __future__ import annotations

import asyncio
import json

import typer
from rich.table import Table

from matriosha.cli.utils.context import get_global_context
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.local_tokens import list_local_agent_connections

from .common import (
    _console,
    _emit_error,
    _enforce_agent_managed_mode,
    _list_agents,
    _map_service_error,
    _normalize_timestamp,
    _resolve_managed_token,
    _resolve_output_mode,
    _resolve_profile_endpoint,
    _status_from_last_seen,
    _truncate_id,
)


def _profile_from_package_patch(ctx: typer.Context):
    import sys

    package = sys.modules.get("matriosha.cli.commands.agent.common")
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
    def list_cmd(
        ctx: typer.Context,
        json_flag: bool = typer.Option(
            False, "--json", help="Show JSON output for scripts and automation."
        ),
        local: bool = typer.Option(False, "--local", help="List local-only agents."),
    ) -> None:
        """List connected agents."""

        json_output, plain = _resolve_output_mode(ctx, json_flag)
        endpoint, profile_name = _resolve_profile_endpoint(ctx)

        profile = _profile_from_package_patch(ctx)
        use_local = local or profile.mode == "local"

        if use_local:
            agents = list_local_agent_connections(profile_name)
        else:
            _enforce_agent_managed_mode(ctx)
            managed_token = _resolve_managed_token(profile_name, json_output, plain)

            try:
                agents = asyncio.run(_list_agents(endpoint=endpoint, managed_token=managed_token))
            except Exception as exc:  # noqa: BLE001
                _emit_error(_map_service_error(exc), json_output=json_output, plain=plain)

        normalized = []
        for item in agents:
            agent_id = str(item.get("id") or item.get("agent_id") or "")
            status = (
                "revoked"
                if bool(item.get("revoked", False))
                else _status_from_last_seen(item.get("last_seen"))
            )
            normalized.append(
                {
                    "id": agent_id,
                    "name": str(item.get("name") or "-"),
                    "kind": str(item.get("agent_kind") or item.get("kind") or "local"),
                    "connected_at": _normalize_timestamp(
                        item.get("connected_at") or item.get("created_at")
                    ),
                    "last_seen": _normalize_timestamp(
                        item.get("last_seen") or item.get("last_used")
                    ),
                    "status": status,
                }
            )

        if json_output:
            typer.echo(json.dumps(normalized, sort_keys=True))
            raise typer.Exit(code=0)

        if plain:
            typer.echo("ID | Name | Kind | Connected At | Last Seen | Status")
            for row in normalized:
                typer.echo(
                    " | ".join(
                        [
                            _truncate_id(row["id"]),
                            row["name"],
                            row["kind"],
                            row["connected_at"],
                            row["last_seen"],
                            row["status"],
                        ]
                    )
                )
            raise typer.Exit(code=0)

        table = Table(title="Connected Agents", show_header=True, header_style="bold cyan")
        table.add_column("ID", style="bold")
        table.add_column("Name")
        table.add_column("Kind")
        table.add_column("Connected At")
        table.add_column("Last Seen")
        table.add_column("Status")

        for row in normalized:
            status_chip = (
                "[success]online[/success]"
                if row["status"] == "online"
                else "[warning]offline[/warning]"
            )
            table.add_row(
                _truncate_id(row["id"]),
                row["name"],
                row["kind"],
                row["connected_at"],
                row["last_seen"],
                status_chip,
            )

        _console().print(table)
        raise typer.Exit(code=0)
