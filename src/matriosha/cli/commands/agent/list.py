"""Agent list command."""

from __future__ import annotations

import asyncio
import json

import typer
from rich.table import Table

from .common import (
    _console,
    _emit_error,
    _list_agents,
    _map_service_error,
    _normalize_timestamp,
    _resolve_managed_token,
    _resolve_output_mode,
    _resolve_profile_endpoint,
    _status_from_last_seen,
    _truncate_id,
    _validate_backend_credentials,
)

def register(app: typer.Typer) -> None:
    @app.command("list")
    def list_cmd(
        ctx: typer.Context,
        json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    ) -> None:
        """List agents connected to the current managed user."""

        json_output, plain = _resolve_output_mode(ctx, json_flag)
        _validate_backend_credentials(json_output, plain)

        endpoint, profile_name = _resolve_profile_endpoint(ctx)
        managed_token = _resolve_managed_token(profile_name, json_output, plain)

        try:
            agents = asyncio.run(_list_agents(endpoint=endpoint, managed_token=managed_token))
        except Exception as exc:  # noqa: BLE001
            _emit_error(_map_service_error(exc), json_output=json_output, plain=plain)

        normalized = []
        for item in agents:
            agent_id = str(item.get("id") or item.get("agent_id") or "")
            status = _status_from_last_seen(item.get("last_seen"))
            normalized.append(
                {
                    "id": agent_id,
                    "name": str(item.get("name") or "-"),
                    "kind": str(item.get("agent_kind") or item.get("kind") or "-"),
                    "connected_at": _normalize_timestamp(item.get("connected_at")),
                    "last_seen": _normalize_timestamp(item.get("last_seen")),
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

        table = Table(title="Connected Agents", show_header=True, header_style="bold accent")
        table.add_column("ID", style="bold")
        table.add_column("Name")
        table.add_column("Kind")
        table.add_column("Connected At")
        table.add_column("Last Seen")
        table.add_column("Status")

        for row in normalized:
            status_chip = "[success]online[/success]" if row["status"] == "online" else "[warning]offline[/warning]"
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

