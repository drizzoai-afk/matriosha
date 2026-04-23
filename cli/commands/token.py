"""Managed agent-token lifecycle commands (generate/list/revoke/inspect)."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cli.brand.theme import console as make_console
from cli.utils.context import get_global_context
from cli.utils.errors import EXIT_AUTH, EXIT_NETWORK, EXIT_UNKNOWN, EXIT_USAGE
from cli.utils.mode_guard import require_mode
from core.config import get_active_profile, load_config
from core.managed.auth import resolve_access_token
from core.managed.client import AuthError, ManagedClient, ManagedClientError, NetworkError, RateLimitError
from core.managed.secrets import load_runtime_secrets

app = typer.Typer(
    help=(
        "Agent token lifecycle commands for managed mode.\n\n"
        "Scopes:\n"
        "  - read  : recall/search/list only\n"
        "  - write : read + remember/delete/sync operations\n"
        "  - admin : full managed workspace access for automation\n\n"
        "Expiration format for --expires:\n"
        "  <number><unit> where unit is m, h, d, or w (examples: 30m, 1h, 7d, 2w)."
    ),
    no_args_is_help=True,
)

_SCOPE_CHOICES = ("read", "write", "admin")
_DURATION_PATTERN = re.compile(r"^(?P<value>\d+)(?P<unit>[mhdw])$")


class TokenCommandError(RuntimeError):
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


def _console() -> Console:
    return make_console()


def _resolve_output_mode(ctx: typer.Context, json_flag: bool) -> tuple[bool, bool]:
    gctx = get_global_context(ctx)
    return gctx.json_output or json_flag, gctx.plain


def _emit_error(err: TokenCommandError, *, json_output: bool, plain: bool) -> None:
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

    _console().print(
        Panel(
            f"[white]{err.title}[/white]\n"
            f"\n[bold]category[/bold]: {err.category}  [bold]code[/bold]: {err.code}  [bold]exit[/bold]: {err.exit_code}"
            f"\n[bold]fix[/bold]: {err.fix}"
            f"\n[bold]debug[/bold]: {err.debug}",
            title="[bold danger]✖ ERROR[/bold danger]",
            border_style="danger",
            expand=False,
        )
    )
    raise typer.Exit(code=err.exit_code)


def _validate_backend_credentials(json_output: bool, plain: bool) -> None:
    runtime = load_runtime_secrets(("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"), allow_env_fallback=True)
    missing = runtime.missing(("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"))

    if missing:
        joined = ", ".join(missing)
        _emit_error(
            TokenCommandError(
                "Managed backend credentials are incomplete",
                category="SYS",
                code="SYS-501",
                exit_code=EXIT_UNKNOWN,
                fix=(
                    "set missing secrets in env or GSM, then retry token command "
                    "(requires GCP_PROJECT_ID + GOOGLE_APPLICATION_CREDENTIALS for GSM lookup)."
                ),
                debug=f"missing={joined}",
            ),
            json_output=json_output,
            plain=plain,
        )


def _resolve_managed_token(profile_name: str, json_output: bool, plain: bool) -> str:
    token = resolve_access_token(profile_name)
    if token:
        return token

    _emit_error(
        TokenCommandError(
            "Managed session token missing",
            category="AUTH",
            code="AUTH-501",
            exit_code=EXIT_AUTH,
            fix="run `matriosha auth login` or set MATRIOSHA_MANAGED_TOKEN and retry",
            debug="missing MATRIOSHA_MANAGED_TOKEN",
        ),
        json_output=json_output,
        plain=plain,
    )
    return ""


def _normalize_timestamp(value: Any) -> str:
    if value in (None, ""):
        return "-"
    text = str(value)
    if text.endswith("+00:00"):
        return text.replace("+00:00", "Z")
    return text


def _parse_expiration_duration(duration: str | None) -> str | None:
    if duration is None:
        return None

    raw = duration.strip().lower()
    if not raw:
        return None

    match = _DURATION_PATTERN.fullmatch(raw)
    if not match:
        raise TokenCommandError(
            "Invalid --expires value",
            category="VAL",
            code="VAL-501",
            exit_code=EXIT_USAGE,
            fix="use duration format like 30m, 1h, 7d, or 2w",
            debug=f"expires={duration}",
        )

    amount = int(match.group("value"))
    unit = match.group("unit")
    if amount <= 0:
        raise TokenCommandError(
            "Invalid --expires value",
            category="VAL",
            code="VAL-502",
            exit_code=EXIT_USAGE,
            fix="duration must be greater than zero",
            debug=f"expires={duration}",
        )

    delta_map = {
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
        "w": timedelta(weeks=amount),
    }
    expires_at = datetime.now(timezone.utc) + delta_map[unit]
    return expires_at.isoformat().replace("+00:00", "Z")


def _map_managed_error(exc: ManagedClientError) -> TokenCommandError:
    if isinstance(exc, RateLimitError):
        return TokenCommandError(
            "Token rate limit reached",
            category="QUOTA",
            code="QUOTA-429",
            exit_code=EXIT_NETWORK,
            fix="wait and retry later (limit is 10 token operations/hour per user)",
            debug=exc.debug_hint,
        )

    if isinstance(exc, AuthError):
        return TokenCommandError(
            exc.message,
            category=exc.category,
            code=exc.code,
            exit_code=EXIT_AUTH,
            fix=exc.remediation,
            debug=exc.debug_hint,
        )

    if isinstance(exc, NetworkError):
        return TokenCommandError(
            exc.message,
            category=exc.category,
            code=exc.code,
            exit_code=EXIT_NETWORK,
            fix=exc.remediation,
            debug=exc.debug_hint,
        )

    exit_code = EXIT_NETWORK if "http_status=429" in exc.debug_hint else EXIT_UNKNOWN
    return TokenCommandError(
        exc.message,
        category=exc.category,
        code=exc.code,
        exit_code=exit_code,
        fix=exc.remediation,
        debug=exc.debug_hint,
    )


def _resolve_token_by_prefix(tokens: list[dict[str, Any]], id_or_prefix: str) -> dict[str, Any]:
    direct = [t for t in tokens if str(t.get("id", "")) == id_or_prefix]
    if len(direct) == 1:
        return direct[0]

    prefix_matches = [t for t in tokens if str(t.get("id", "")).startswith(id_or_prefix)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]

    if not prefix_matches:
        raise TokenCommandError(
            "No token matches the provided id/prefix",
            category="VAL",
            code="VAL-503",
            exit_code=EXIT_USAGE,
            fix="run `matriosha token list` and provide a valid id prefix",
            debug=f"id_or_prefix={id_or_prefix}",
        )

    collisions = ", ".join(str(t.get("id", ""))[:12] for t in prefix_matches[:5])
    raise TokenCommandError(
        "Token id prefix is ambiguous",
        category="VAL",
        code="VAL-504",
        exit_code=EXIT_USAGE,
        fix="use a longer UUID prefix to uniquely identify one token",
        debug=f"matches={len(prefix_matches)} sample={collisions}",
    )


@app.callback()
def callback(ctx: typer.Context) -> None:
    """Enforce managed mode for all token commands."""

    require_mode("managed")(ctx)


@app.command("generate")
def generate(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Friendly token name (example: ci-agent, nightly-sync)."),
    scope: str = typer.Option(
        "write",
        "--scope",
        help="Access scope: read | write | admin. Default: write.",
        show_default=True,
    ),
    expires: str | None = typer.Option(
        None,
        "--expires",
        help="Duration until expiry (examples: 30m, 1h, 7d, 30d, 2w).",
    ),
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Generate a managed agent token (token is shown once only)."""

    json_output, plain = _resolve_output_mode(ctx, json_flag)
    _validate_backend_credentials(json_output, plain)

    normalized_scope = scope.strip().lower()
    if normalized_scope not in _SCOPE_CHOICES:
        _emit_error(
            TokenCommandError(
                "Invalid scope",
                category="VAL",
                code="VAL-505",
                exit_code=EXIT_USAGE,
                fix="use --scope read|write|admin",
                debug=f"scope={scope}",
            ),
            json_output=json_output,
            plain=plain,
        )

    try:
        expires_at = _parse_expiration_duration(expires)
        profile = get_active_profile(load_config(), get_global_context(ctx).profile)
        token = _resolve_managed_token(profile.name, json_output, plain)
        endpoint = profile.managed_endpoint
        result = asyncio.run(_generate_token(token=token, endpoint=endpoint, name=name, scope=normalized_scope, expires_at=expires_at))
    except TokenCommandError as exc:
        _emit_error(exc, json_output=json_output, plain=plain)
    except ManagedClientError as exc:
        _emit_error(_map_managed_error(exc), json_output=json_output, plain=plain)

    token_value = str(result.get("token_plaintext") or result.get("token") or "")
    payload = {
        "id": str(result.get("id") or result.get("token_id") or ""),
        "token": token_value,
        "name": str(result.get("name") or name),
        "scope": str(result.get("scope") or normalized_scope),
        "expires_at": _normalize_timestamp(result.get("expires_at") or expires_at),
    }

    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True))
        raise typer.Exit(code=0)

    if plain:
        typer.echo("STORE THIS TOKEN NOW — it will not be shown again.")
        typer.echo(f"id: {payload['id']}")
        typer.echo(f"name: {payload['name']}")
        typer.echo(f"scope: {payload['scope']}")
        typer.echo(f"expires_at: {payload['expires_at']}")
        typer.echo(f"token: {payload['token']}")
        raise typer.Exit(code=0)

    _console().print(
        Panel(
            f"[bold]name[/bold]       {payload['name']}\n"
            f"[bold]scope[/bold]      {payload['scope']}\n"
            f"[bold]expires_at[/bold] {payload['expires_at']}\n"
            f"[bold]token[/bold]      {payload['token']}\n\n"
            "[warning]STORE THIS TOKEN NOW — it will not be shown again.[/warning]",
            title="[bold warning]⚠ TOKEN REVEAL (ONE-TIME)[/bold warning]",
            border_style="warning",
            expand=False,
        )
    )
    raise typer.Exit(code=0)


@app.command("list")
def list_tokens(
    ctx: typer.Context,
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """List managed agent tokens and their lifecycle metadata."""

    json_output, plain = _resolve_output_mode(ctx, json_flag)
    _validate_backend_credentials(json_output, plain)

    try:
        profile = get_active_profile(load_config(), get_global_context(ctx).profile)
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


@app.command("revoke")
def revoke(
    ctx: typer.Context,
    id_or_prefix: str = typer.Argument(..., help="Full token id or unique UUID prefix."),
    yes: bool = typer.Option(False, "--yes", help="Skip confirmation prompt and revoke immediately."),
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Revoke a managed token using full id or UUID prefix."""

    json_output, plain = _resolve_output_mode(ctx, json_flag)
    _validate_backend_credentials(json_output, plain)

    try:
        profile = get_active_profile(load_config(), get_global_context(ctx).profile)
        token = _resolve_managed_token(profile.name, json_output, plain)
        endpoint = profile.managed_endpoint
        tokens = asyncio.run(_list_tokens(token=token, endpoint=endpoint))
        selected = _resolve_token_by_prefix(tokens, id_or_prefix)
        token_id = str(selected.get("id") or "")

        if not yes:
            confirmed = typer.confirm(f"Revoke token '{selected.get('name', token_id)}' ({token_id})?", default=False)
            if not confirmed:
                raise TokenCommandError(
                    "Revocation canceled by user",
                    category="VAL",
                    code="VAL-506",
                    exit_code=EXIT_USAGE,
                    fix="rerun with --yes to skip confirmation",
                    debug="confirmation declined",
                )

        asyncio.run(_revoke_token(token=token, endpoint=endpoint, token_id=token_id))
    except TokenCommandError as exc:
        _emit_error(exc, json_output=json_output, plain=plain)
    except ManagedClientError as exc:
        _emit_error(_map_managed_error(exc), json_output=json_output, plain=plain)

    payload = {"status": "ok", "id": token_id, "revoked": True}
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True))
        raise typer.Exit(code=0)

    if plain:
        typer.echo(f"revoked token {token_id}")
        raise typer.Exit(code=0)

    _console().print(
        Panel(
            f"Token revoked successfully.\n\n[bold]id[/bold]: {token_id}",
            title="[bold success]✓ TOKEN REVOKED[/bold success]",
            border_style="success",
            expand=False,
        )
    )
    raise typer.Exit(code=0)


@app.command("inspect")
def inspect(
    ctx: typer.Context,
    id_or_prefix: str = typer.Argument(..., help="Full token id or unique UUID prefix."),
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Inspect full token metadata (plaintext token is never shown)."""

    json_output, plain = _resolve_output_mode(ctx, json_flag)
    _validate_backend_credentials(json_output, plain)

    try:
        profile = get_active_profile(load_config(), get_global_context(ctx).profile)
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


async def _generate_token(
    *, token: str, endpoint: str | None, name: str, scope: str, expires_at: str | None
) -> dict[str, Any]:
    async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
        return await client.create_agent_token(name=name, scope=scope, expires_at=expires_at)


async def _list_tokens(*, token: str, endpoint: str | None) -> list[dict[str, Any]]:
    async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
        return await client.list_agent_tokens()


async def _revoke_token(*, token: str, endpoint: str | None, token_id: str) -> bool:
    async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
        return await client.revoke_agent_token(token_id)
