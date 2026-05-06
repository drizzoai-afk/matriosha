"""Agent remove command."""

from __future__ import annotations

import asyncio
import json

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_USAGE
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.local_tokens import list_local_agent_connections, remove_local_agent_connection

from .common import (
    AgentCommandError,
    _emit_error,
    _enforce_agent_managed_mode,
    _list_agents,
    _map_service_error,
    _remove_agent,
    _render_card,
    _resolve_agent_by_prefix,
    _resolve_managed_token,
    _resolve_output_mode,
    _resolve_profile_endpoint,
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
    @app.command("remove")
    def remove(
        ctx: typer.Context,
        id_or_prefix: str = typer.Argument(
            ..., help="Full agent id or unique UUID prefix (8+ chars)."
        ),
        yes: bool = typer.Option(
            False, "--yes", help="Skip confirmation prompt and remove immediately."
        ),
        json_flag: bool = typer.Option(
            False, "--json", help="Show JSON output for scripts and automation."
        ),
        local: bool = typer.Option(False, "--local", help="Remove a local-only connected agent."),
    ) -> None:
        """Remove a connected agent."""

        json_output, plain = _resolve_output_mode(ctx, json_flag)
        endpoint, profile_name = _resolve_profile_endpoint(ctx)
        profile = _profile_from_package_patch(ctx)
        use_local = local or profile.mode == "local"

        if use_local:
            try:
                selected = _resolve_agent_by_prefix(
                    list_local_agent_connections(profile_name), id_or_prefix
                )
            except AgentCommandError as exc:
                _emit_error(exc, json_output=json_output, plain=plain)
        else:
            _enforce_agent_managed_mode(ctx)
            managed_token = _resolve_managed_token(profile_name, json_output, plain)

            try:
                agents = asyncio.run(_list_agents(endpoint=endpoint, managed_token=managed_token))
                selected = _resolve_agent_by_prefix(agents, id_or_prefix)
            except AgentCommandError as exc:
                _emit_error(exc, json_output=json_output, plain=plain)
            except Exception as exc:  # noqa: BLE001
                _emit_error(_map_service_error(exc), json_output=json_output, plain=plain)

        if selected is None:
            payload = {
                "status": "ok",
                "removed": False,
                "reason": "already_absent",
                "agent_id": id_or_prefix,
            }
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

        if use_local:
            removed_result = remove_local_agent_connection(profile_name, agent_id)
            removed = bool(removed_result)
        else:
            try:
                removed = asyncio.run(
                    _remove_agent(endpoint=endpoint, managed_token=managed_token, agent_id=agent_id)
                )
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
