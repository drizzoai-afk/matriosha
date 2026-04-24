"""Managed connected-agent lifecycle commands (connect/list/remove)."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from getpass import getpass
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from matriosha.cli.brand.theme import console as make_console
from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_AUTH, EXIT_NETWORK, EXIT_UNKNOWN, EXIT_USAGE
from matriosha.cli.utils.mode_guard import require_mode
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.managed.auth import resolve_access_token
from matriosha.core.managed.agents import (
    AgentAuthError,
    AgentConfigError,
    AgentNetworkError,
    AgentStoreError,
    connect as managed_connect,
    list_agents as managed_list_agents,
    remove_agent as managed_remove_agent,
)
from matriosha.core.managed.client import ManagedClient, ManagedClientError
from matriosha.core.managed.secrets import load_runtime_secrets

app = typer.Typer(help="Connected agent management commands.", no_args_is_help=True)

_ALLOWED_AGENT_KINDS = {"desktop", "server", "ci"}
_ONLINE_THRESHOLD = timedelta(minutes=5)


class AgentCommandError(RuntimeError):
    """Structured command error for deterministic UX and exit mapping."""

    def __init__(
        self,
        title: str,
        *,
        category: str,
        code: str,
        exit_code: int,
        fix: str,
        debug: str,
    ) -> None:
        super().__init__(title)
        self.title = title
        self.category = category
        self.code = code
        self.exit_code = exit_code
        self.fix = fix
        self.debug = debug


@app.callback()
def callback(ctx: typer.Context) -> None:
    """Enforce managed mode for all agent commands."""

    require_mode("managed")(ctx)


def _console() -> Console:
    return make_console()


def _resolve_output_mode(ctx: typer.Context, json_flag: bool) -> tuple[bool, bool]:
    gctx = get_global_context(ctx)
    return gctx.json_output or json_flag, gctx.plain


def _render_card(title: str, rows: list[tuple[str, str]], *, status_chip: str, style: str) -> None:
    console = _console()
    width = 88
    inner = width - 2
    header = f" {status_chip} {title} "
    header_pad = max(0, inner - len(header))
    console.print(
        f"[{style}]╭{'─' * (header_pad // 2)}{header}{'─' * (header_pad - (header_pad // 2))}╮[/{style}]"
    )
    for key, value in rows:
        line = f" {key:<14} {value} "
        console.print(f"[{style}]│{line:<{inner}}│[/{style}]")
    console.print(f"[{style}]╰{'─' * inner}╯[/{style}]")


def _emit_error(err: AgentCommandError, *, json_output: bool, plain: bool) -> None:
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "status": "error",
                    "title": err.title,
                    "category": err.category,
                    "code": err.code,
                    "exit": err.exit_code,
                    "fix": err.fix,
                    "debug": err.debug,
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=err.exit_code)

    if plain:
        typer.echo(f"✖ {err.title}")
        typer.echo(f"category: {err.category}  code: {err.code}  exit: {err.exit_code}")
        typer.echo(f"fix: {err.fix}")
        typer.echo(f"debug: {err.debug}")
        raise typer.Exit(code=err.exit_code)

    _render_card(
        err.title,
        [
            ("category", f"{err.category}  code: {err.code}  exit: {err.exit_code}"),
            ("fix", err.fix),
            ("debug", err.debug),
        ],
        status_chip="✖ ERROR",
        style="danger",
    )
    raise typer.Exit(code=err.exit_code)


def _validate_backend_credentials(json_output: bool, plain: bool) -> None:
    required = (
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_ANON_KEY",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
    )
    runtime = load_runtime_secrets(required, allow_env_fallback=True)
    missing = runtime.missing(required)
    if missing:
        _emit_error(
            AgentCommandError(
                "Managed backend credentials are incomplete",
                category="SYS",
                code="SYS-801",
                exit_code=EXIT_UNKNOWN,
                fix=(
                    "set missing secrets in env or GSM and retry "
                    "(requires GCP_PROJECT_ID + GOOGLE_APPLICATION_CREDENTIALS for GSM)."
                ),
                debug=f"missing={', '.join(missing)}",
            ),
            json_output=json_output,
            plain=plain,
        )


def _resolve_managed_token(profile_name: str, json_output: bool, plain: bool) -> str:
    token = resolve_access_token(profile_name)
    if token:
        return token

    _emit_error(
        AgentCommandError(
            "Managed session token missing",
            category="AUTH",
            code="AUTH-801",
            exit_code=EXIT_AUTH,
            fix="run `matriosha auth login` or set MATRIOSHA_MANAGED_TOKEN and retry",
            debug="missing MATRIOSHA_MANAGED_TOKEN",
        ),
        json_output=json_output,
        plain=plain,
    )
    return ""


def _resolve_profile_endpoint(ctx: typer.Context) -> tuple[str | None, str]:
    cfg = load_config()
    gctx = get_global_context(ctx)
    profile = get_active_profile(cfg, gctx.profile)
    return profile.managed_endpoint, profile.name


def _map_service_error(exc: Exception) -> AgentCommandError:
    if isinstance(exc, AgentAuthError):
        return AgentCommandError(
            exc.message,
            category=exc.category,
            code=exc.code,
            exit_code=EXIT_AUTH,
            fix=exc.remediation,
            debug=exc.debug_hint,
        )
    if isinstance(exc, AgentNetworkError):
        return AgentCommandError(
            exc.message,
            category=exc.category,
            code=exc.code,
            exit_code=EXIT_NETWORK,
            fix=exc.remediation,
            debug=exc.debug_hint,
        )
    if isinstance(exc, AgentStoreError):
        exit_code = EXIT_NETWORK if exc.category in {"NET", "QUOTA"} else EXIT_UNKNOWN
        return AgentCommandError(
            exc.message,
            category=exc.category,
            code=exc.code,
            exit_code=exit_code,
            fix=exc.remediation,
            debug=exc.debug_hint,
        )
    if isinstance(exc, AgentConfigError):
        return AgentCommandError(
            exc.message,
            category=exc.category,
            code=exc.code,
            exit_code=EXIT_UNKNOWN,
            fix=exc.remediation,
            debug=exc.debug_hint,
        )
    if isinstance(exc, ManagedClientError):
        exit_code = EXIT_AUTH if exc.category == "AUTH" else EXIT_NETWORK if exc.category == "NET" else EXIT_UNKNOWN
        return AgentCommandError(
            exc.message,
            category=exc.category,
            code=exc.code,
            exit_code=exit_code,
            fix=exc.remediation,
            debug=exc.debug_hint,
        )

    return AgentCommandError(
        "Unexpected agent command failure",
        category="SYS",
        code="SYS-899",
        exit_code=EXIT_UNKNOWN,
        fix="retry command with --debug and inspect logs",
        debug=f"error={exc.__class__.__name__}",
    )


def _normalize_timestamp(value: Any) -> str:
    if value in (None, ""):
        return "-"
    text = str(value)
    if text.endswith("+00:00"):
        return text.replace("+00:00", "Z")
    return text


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _status_from_last_seen(last_seen: Any) -> str:
    ts = _parse_timestamp(last_seen)
    if ts is None:
        return "offline"
    if datetime.now(timezone.utc) - ts <= _ONLINE_THRESHOLD:
        return "online"
    return "offline"


def _truncate_id(value: str, *, width: int = 12) -> str:
    return value if len(value) <= width else f"{value[:width]}…"


def _resolve_agent_by_prefix(agents: list[dict[str, Any]], id_or_prefix: str) -> dict[str, Any] | None:
    if len(id_or_prefix) < 8:
        raise AgentCommandError(
            "Agent id prefix too short",
            category="VAL",
            code="VAL-801",
            exit_code=EXIT_USAGE,
            fix="provide at least the first 8 characters of the agent id",
            debug=f"id_or_prefix={id_or_prefix}",
        )

    direct = [item for item in agents if str(item.get("id") or "") == id_or_prefix]
    if len(direct) == 1:
        return direct[0]

    prefix_matches = [item for item in agents if str(item.get("id") or "").startswith(id_or_prefix)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]

    if not prefix_matches:
        return None

    sample = ", ".join(str(item.get("id") or "")[:12] for item in prefix_matches[:5])
    raise AgentCommandError(
        "Agent id prefix is ambiguous",
        category="VAL",
        code="VAL-802",
        exit_code=EXIT_USAGE,
        fix="use a longer UUID prefix to identify a single agent",
        debug=f"matches={len(prefix_matches)} sample={sample}",
    )


async def _connect_agent(*, endpoint: str | None, managed_token: str, token_plaintext: str, name: str, kind: str) -> dict[str, str]:
    async with ManagedClient(token=managed_token, base_url=endpoint, managed_mode=False) as client:
        return await managed_connect(client, token_plaintext=token_plaintext, name=name, agent_kind=kind)


async def _list_agents(*, endpoint: str | None, managed_token: str) -> list[dict[str, Any]]:
    async with ManagedClient(token=managed_token, base_url=endpoint, managed_mode=False) as client:
        return await managed_list_agents(client)


async def _remove_agent(*, endpoint: str | None, managed_token: str, agent_id: str) -> bool:
    async with ManagedClient(token=managed_token, base_url=endpoint, managed_mode=False) as client:
        return await managed_remove_agent(client, agent_id)


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


@app.command("remove")
def remove(
    ctx: typer.Context,
    id_or_prefix: str = typer.Argument(..., help="Full agent id or unique UUID prefix (8+ chars)."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt and remove immediately."),
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Remove a connected agent by id/prefix (idempotent operation)."""

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
