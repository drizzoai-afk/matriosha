"""Managed agent-token lifecycle commands (generate/list/revoke/inspect)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel

from matriosha.cli.brand.theme import console as make_console
from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_AUTH, EXIT_MODE, EXIT_NETWORK, EXIT_UNKNOWN, EXIT_USAGE
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.managed.auth import resolve_access_token
from matriosha.core.managed.client import AuthError, ManagedClient, ManagedClientError, NetworkError, RateLimitError
from matriosha.core.managed.secrets import load_runtime_secrets

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


def _enforce_token_mode(ctx: typer.Context, *, allow_local: bool = False) -> None:
    gctx = get_global_context(ctx)
    cfg = load_config()
    profile = get_active_profile(cfg, gctx.profile)

    if profile.mode == "managed":
        return
    if allow_local and profile.mode == "local":
        return

    typer.echo("this command requires managed mode; run `matriosha mode set managed`")
    raise typer.Exit(code=EXIT_MODE)


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


async def _generate_token(
    *,
    token: str,
    endpoint: str | None,
    name: str,
    scope: str,
    expires_at: str | None,
    managed_passphrase: str | None = None,
) -> dict[str, Any]:
    async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
        return await client.create_agent_token(
            name=name,
            scope=scope,
            expires_at=expires_at,
            managed_passphrase=managed_passphrase,
        )


async def _list_tokens(*, token: str, endpoint: str | None) -> list[dict[str, Any]]:
    async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
        return await client.list_agent_tokens()


async def _revoke_token(*, token: str, endpoint: str | None, token_id: str) -> bool:
    async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
        return await client.revoke_agent_token(token_id)


__all__ = [
    name
    for name in globals()
    if not name.startswith("__")
]
