"""Agent connect command."""

from __future__ import annotations

import asyncio
import json
from getpass import getpass

import typer

from matriosha.cli.utils.errors import EXIT_USAGE

from .common import (
    AgentCommandError,
    _ALLOWED_AGENT_KINDS,
    _connect_agent,
    _emit_error,
    _map_service_error,
    _render_card,
    _resolve_managed_token,
    _resolve_output_mode,
    _resolve_profile_endpoint,
    _validate_backend_credentials,
)

def register(app: typer.Typer) -> None:
    @app.command("connect")
    def connect(
        ctx: typer.Context,
        token: str | None = typer.Option(None, "--token", help="Agent token (if omitted, prompted hidden)."),
        name: str = typer.Option(..., "--name", help="Friendly agent name."),
        kind: str = typer.Option(..., "--kind", help="Agent kind: desktop|server|ci."),
        json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    ) -> None:
        """Connect an agent to managed control plane using an agent token."""

        json_output, plain = _resolve_output_mode(ctx, json_flag)
        _validate_backend_credentials(json_output, plain)

        normalized_kind = kind.strip().lower()
        if normalized_kind not in _ALLOWED_AGENT_KINDS:
            _emit_error(
                AgentCommandError(
                    "Invalid agent kind",
                    category="VAL",
                    code="VAL-803",
                    exit_code=EXIT_USAGE,
                    fix="use --kind desktop|server|ci",
                    debug=f"kind={kind}",
                ),
                json_output=json_output,
                plain=plain,
            )

        token_plaintext = token.strip() if token else getpass("Agent token: ").strip()
        if not token_plaintext:
            _emit_error(
                AgentCommandError(
                    "Agent token is required",
                    category="VAL",
                    code="VAL-804",
                    exit_code=EXIT_USAGE,
                    fix="pass --token or provide token at the hidden prompt",
                    debug="empty agent token",
                ),
                json_output=json_output,
                plain=plain,
            )

        endpoint, profile_name = _resolve_profile_endpoint(ctx)
        managed_token = _resolve_managed_token(profile_name, json_output, plain)

        try:
            result = asyncio.run(
                _connect_agent(
                    endpoint=endpoint,
                    managed_token=managed_token,
                    token_plaintext=token_plaintext,
                    name=name,
                    kind=normalized_kind,
                )
            )
        except Exception as exc:  # noqa: BLE001
            _emit_error(_map_service_error(exc), json_output=json_output, plain=plain)

        payload = {
            "status": "ok",
            "agent_id": result["agent_id"],
            "fingerprint": result["fingerprint"],
            "name": name,
            "kind": normalized_kind,
        }

        if json_output:
            typer.echo(json.dumps(payload, sort_keys=True))
            raise typer.Exit(code=0)

        if plain:
            typer.echo(f"agent_id: {payload['agent_id']}")
            typer.echo(f"fingerprint: {payload['fingerprint']}")
            raise typer.Exit(code=0)

        _render_card(
            "AGENT CONNECTED",
            [
                ("name", payload["name"]),
                ("kind", payload["kind"]),
                ("agent_id", payload["agent_id"]),
                ("fingerprint", payload["fingerprint"]),
            ],
            status_chip="✓ ONLINE",
            style="success",
        )
        raise typer.Exit(code=0)

