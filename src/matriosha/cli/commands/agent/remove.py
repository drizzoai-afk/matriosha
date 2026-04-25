"""Agent remove command."""

from __future__ import annotations

import asyncio
import json

import typer

from matriosha.cli.utils.errors import EXIT_USAGE

from .common import (
    AgentCommandError,
    _emit_error,
    _list_agents,
    _map_service_error,
    _remove_agent,
    _render_card,
    _resolve_agent_by_prefix,
    _resolve_managed_token,
    _resolve_output_mode,
    _resolve_profile_endpoint,
    _validate_backend_credentials,
)

def register(app: typer.Typer) -> None:
    @app.command("remove")
    def remove(
        ctx: typer.Context,
        id_or_prefix: str = typer.Argument(..., help="Full agent id or unique UUID prefix (8+ chars)."),
        yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt and remove immediately."),
        json_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Remove a connected agent."""

        json_output, plain = _resolve_output_mode(ctx, json_flag)
        _validate_backend_credentials(json_output, plain)

        endpoint, profile_name = _resolve_profile_endpoint(ctx)
        managed_token = _resolve_managed_token(profile_name, json_output, plain)

        try:
            agents = asyncio.run(_list_agents(endpoint=endpoint, managed_token=managed_token))
            selected = _resolve_agent_by_prefix(agents, id_or_prefix)
        except AgentCommandError as exc:
            _emit_error(exc, json_output=json_output, plain=plain)
        except Exception as exc:  # noqa: BLE001
            _emit_error(_map_service_error(exc), json_output=json_output, plain=plain)

        if selected is None:
            payload = {"status": "ok", "removed": False, "reason": "already_absent", "agent_id": id_or_prefix}
            if json_output:
                typer.echo(json.dumps(payload, sort_keys=True))
            elif plain:
                typer.echo(f"already removed: {id_or_prefix}")
            else:
                _render_card(
                    "AGENT ALREADY ABSENT",
                    [("agent", id_or_prefix), ("result", "no-op")],
                    status_chip="✓ IDEMPOTENT",
                    style="accent",
                )
            raise typer.Exit(code=0)

        agent_id = str(selected.get("id") or selected.get("agent_id") or "")
        if not yes:
            typer.echo("Agent selected for removal:")
            typer.echo(f"  id: {agent_id}")
            typer.echo(f"  name: {selected.get('name', '-')}")
            typer.echo(f"  kind: {selected.get('agent_kind') or selected.get('kind') or '-'}")
            confirmed = typer.confirm("Proceed with agent removal?", default=False)
            if not confirmed:
                _emit_error(
                    AgentCommandError(
                        "Agent removal canceled by user",
                        category="VAL",
                        code="VAL-805",
                        exit_code=EXIT_USAGE,
                        fix="rerun with --yes to skip confirmation",
                        debug="confirmation declined",
                    ),
                    json_output=json_output,
                    plain=plain,
                )

        try:
            removed = asyncio.run(_remove_agent(endpoint=endpoint, managed_token=managed_token, agent_id=agent_id))
        except Exception as exc:  # noqa: BLE001
            _emit_error(_map_service_error(exc), json_output=json_output, plain=plain)

        payload = {"status": "ok", "removed": bool(removed), "agent_id": agent_id}
        if json_output:
            typer.echo(json.dumps(payload, sort_keys=True))
            raise typer.Exit(code=0)

        if plain:
            typer.echo(f"removed: {agent_id}" if removed else f"already removed: {agent_id}")
            raise typer.Exit(code=0)

        _render_card(
            "AGENT REMOVED" if removed else "AGENT ALREADY ABSENT",
            [("agent_id", agent_id), ("result", "removed" if removed else "no-op")],
            status_chip="✓ DONE",
            style="success" if removed else "cyan",
        )
        raise typer.Exit(code=0)

