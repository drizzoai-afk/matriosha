"""Managed authentication commands (device flow, session store, whoami, logout)."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

import typer

from cli.utils.context import get_global_context
from cli.utils.errors import EXIT_AUTH, EXIT_MODE, EXIT_NETWORK, EXIT_UNKNOWN, EXIT_USAGE
from cli.utils.mode_guard import require_mode
from core.config import Profile, get_active_profile, load_config, save_config
from core.managed.auth import (
    DeviceCodeFlow,
    DeviceFlowError,
    LoginRateLimiter,
    TokenStore,
    TokenStoreError,
    ensure_managed_key_bootstrap,
    ensure_managed_passphrase_in_payload,
    resolve_access_token,
)
from core.managed.client import ManagedClient, ManagedClientError

app = typer.Typer(
    help=(
        "Authentication commands for managed mode.\n\n"
        "`auth login` uses OAuth device authorization and auto-generates managed key custody on first use."
    ),
    no_args_is_help=True,
)


class AuthCommandError(RuntimeError):
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
    """Enforce managed mode for auth commands."""

    require_mode("managed")(ctx)


def _emit_error(err: AuthCommandError, *, json_output: bool, plain: bool) -> None:
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

    typer.echo(f"✖ {err.title}")
    typer.echo(f"category: {err.category}  code: {err.code}  exit: {err.exit_code}")
    typer.echo(f"fix: {err.fix}")
    if not plain:
        typer.echo(f"debug: {err.debug}")
    raise typer.Exit(code=err.exit_code)


def _profile_and_endpoint(ctx: typer.Context) -> tuple[Profile, str]:
    cfg = load_config()
    gctx = get_global_context(ctx)
    profile = get_active_profile(cfg, gctx.profile)
    endpoint = (
        profile.managed_endpoint
        or os.getenv("MATRIOSHA_MANAGED_ENDPOINT")
        or os.getenv("SUPABASE_URL")
        or ""
    ).rstrip("/")

    if not endpoint:
        raise AuthCommandError(
            "Managed endpoint is not configured",
            category="SYS",
            code="SYS-601",
            exit_code=EXIT_UNKNOWN,
            fix="set profile.managed_endpoint, MATRIOSHA_MANAGED_ENDPOINT, or SUPABASE_URL",
            debug="missing endpoint",
        )
    return profile, endpoint


def _map_managed_error(exc: ManagedClientError) -> AuthCommandError:
    exit_code = EXIT_AUTH if exc.category == "AUTH" else EXIT_NETWORK if exc.category == "NET" else EXIT_UNKNOWN
    return AuthCommandError(
        exc.message,
        category=exc.category,
        code=exc.code,
        exit_code=exit_code,
        fix=exc.remediation,
        debug=exc.debug_hint,
    )


@app.command("login")
def login(
    ctx: typer.Context,
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Authenticate managed session via device flow and auto-bootstrap managed key custody."""

    gctx = get_global_context(ctx)
    json_output = gctx.json_output or json_flag

    try:
        profile, endpoint = _profile_and_endpoint(ctx)
        limiter = LoginRateLimiter(profile.name)
        limiter.apply_backoff_if_needed()
        limiter.record_attempt()

        flow = DeviceCodeFlow(endpoint)
        authz = asyncio.run(flow.start())

        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "status": "pending",
                        "operation": "auth.login",
                        "user_code": authz.user_code,
                        "verification_uri": authz.verification_uri,
                        "verification_uri_complete": authz.verification_uri_complete,
                        "interval": authz.interval,
                        "expires_in": authz.expires_in,
                    },
                    sort_keys=True,
                )
            )
        else:
            typer.echo("╭──────────── DEVICE AUTH REQUIRED ────────────╮")
            typer.echo(f"│ Code:      {authz.user_code:<34}│")
            typer.echo(f"│ Verify at: {authz.verification_uri:<33}│")
            typer.echo("╰───────────────────────────────────────────────╯")
            if authz.verification_uri_complete:
                typer.echo(f"Open directly: {authz.verification_uri_complete}")

        tokens = asyncio.run(flow.poll(authz))
        token_payload = ensure_managed_passphrase_in_payload(tokens.as_dict())

        async def _bootstrap() -> dict[str, str]:
            async with ManagedClient(token=tokens.access_token, base_url=endpoint, managed_mode=False) as client:
                result = await ensure_managed_key_bootstrap(
                    client,
                    profile_name=profile.name,
                    managed_passphrase=str(token_payload["managed_passphrase"]),
                )
                who = await client.whoami()
                return {
                    "bootstrap": str(result.get("status") or "existing"),
                    "user_id": str(who.get("user_id") or who.get("id") or ""),
                    "email": str(who.get("email") or ""),
                }

        bootstrap = asyncio.run(_bootstrap())
        token_payload["endpoint"] = endpoint
        token_payload["profile"] = profile.name
        token_payload["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        TokenStore(profile.name).save(token_payload)

        limiter.clear()

        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "status": "authenticated",
                        "operation": "auth.login",
                        "managed_key_bootstrap": bootstrap["bootstrap"],
                        "user_id": bootstrap["user_id"],
                        "email": bootstrap["email"],
                        "profile": profile.name,
                    },
                    sort_keys=True,
                )
            )
            raise typer.Exit(code=0)

        typer.echo("✓ Managed session authenticated")
        typer.echo(f"profile: {profile.name}")
        typer.echo(f"managed key bootstrap: {bootstrap['bootstrap']}")
        raise typer.Exit(code=0)

    except AuthCommandError as exc:
        _emit_error(exc, json_output=json_output, plain=gctx.plain)
    except DeviceFlowError as exc:
        _emit_error(
            AuthCommandError(
                str(exc),
                category="AUTH",
                code="AUTH-601",
                exit_code=EXIT_AUTH,
                fix="rerun `matriosha auth login` and complete verification in browser",
                debug="device-flow",
            ),
            json_output=json_output,
            plain=gctx.plain,
        )
    except ManagedClientError as exc:
        _emit_error(_map_managed_error(exc), json_output=json_output, plain=gctx.plain)
    except TokenStoreError as exc:
        _emit_error(
            AuthCommandError(
                "Failed to persist managed session",
                category="SYS",
                code="SYS-602",
                exit_code=EXIT_UNKNOWN,
                fix="fix local filesystem permissions and retry login",
                debug=str(exc),
            ),
            json_output=json_output,
            plain=gctx.plain,
        )


@app.command("logout")
def logout(
    ctx: typer.Context,
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Clear local managed session token cache."""

    gctx = get_global_context(ctx)
    json_output = gctx.json_output or json_flag

    try:
        profile, endpoint = _profile_and_endpoint(ctx)
        store = TokenStore(profile.name)
        payload = store.load() or {}
        token = str(payload.get("access_token") or os.getenv("MATRIOSHA_MANAGED_TOKEN") or "")

        if token:
            async def _best_effort_revoke() -> None:
                try:
                    async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
                        await client._request("POST", "/managed/auth/logout")
                except Exception:  # noqa: BLE001
                    return

            asyncio.run(_best_effort_revoke())

        store.clear()

        if json_output:
            typer.echo(json.dumps({"status": "ok", "operation": "auth.logout"}, sort_keys=True))
        else:
            typer.echo("✓ managed session cleared")
        raise typer.Exit(code=0)

    except AuthCommandError as exc:
        _emit_error(exc, json_output=json_output, plain=gctx.plain)


@app.command("whoami")
def whoami(
    ctx: typer.Context,
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Show current managed identity from remote backend."""

    gctx = get_global_context(ctx)
    json_output = gctx.json_output or json_flag

    try:
        profile, endpoint = _profile_and_endpoint(ctx)
        token = resolve_access_token(profile.name)
        if not token:
            raise AuthCommandError(
                "Managed session token missing",
                category="AUTH",
                code="AUTH-602",
                exit_code=EXIT_AUTH,
                fix="run `matriosha auth login`",
                debug="no token in env or token store",
            )

        async def _who() -> dict[str, str]:
            async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
                payload = await client.whoami()
                return {
                    "user_id": str(payload.get("user_id") or payload.get("id") or ""),
                    "email": str(payload.get("email") or ""),
                    "subscription": str(payload.get("subscription_status") or payload.get("subscription") or "unknown"),
                }

        data = asyncio.run(_who())

        payload = {
            "status": "ok",
            "operation": "auth.whoami",
            "profile": profile.name,
            "mode": profile.mode,
            **data,
        }

        if json_output:
            typer.echo(json.dumps(payload, sort_keys=True))
        else:
            typer.echo(f"profile: {profile.name}")
            typer.echo(f"user_id: {data['user_id']}")
            typer.echo(f"email: {data['email'] or '-'}")
            typer.echo(f"subscription: {data['subscription']}")
        raise typer.Exit(code=0)

    except AuthCommandError as exc:
        _emit_error(exc, json_output=json_output, plain=gctx.plain)
    except ManagedClientError as exc:
        _emit_error(_map_managed_error(exc), json_output=json_output, plain=gctx.plain)


@app.command("switch")
def switch(
    ctx: typer.Context,
    profile_name: str = typer.Argument(..., help="Managed profile name to activate."),
    endpoint: str | None = typer.Option(None, "--endpoint", help="Managed endpoint override for this profile."),
) -> None:
    """Switch active profile (creates it if missing) and force managed mode."""

    cfg = load_config()
    profile = cfg.profiles.get(profile_name)
    if profile is None:
        profile = Profile(name=profile_name, mode="managed", managed_endpoint=endpoint)
    else:
        profile.mode = "managed"
        if endpoint:
            profile.managed_endpoint = endpoint

    cfg.profiles[profile_name] = profile
    cfg.active_profile = profile_name
    save_config(cfg)

    typer.echo(json.dumps({"status": "ok", "active_profile": profile_name, "mode": "managed"}, sort_keys=True))
    raise typer.Exit(code=0)
