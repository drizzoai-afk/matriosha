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




__all__ = [
    name
    for name in globals()
    if not name.startswith("__")
]
