"""Managed authentication commands (email OTP, session store, whoami, logout)."""

from __future__ import annotations

from matriosha.cli.utils.mode_guard import require_mode

import json
import os
from dataclasses import dataclass

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_AUTH, EXIT_NETWORK, EXIT_UNKNOWN
from matriosha.core.config import Profile, get_active_profile, load_config, save_config
from matriosha.core.managed.auth import (
    ensure_managed_key_bootstrap,
    ensure_managed_passphrase_in_payload,
    resolve_access_token,
)
from matriosha.core.managed.client import (
    ManagedClient,
    ManagedClientError,
    resolve_managed_endpoint,
)
from matriosha.core.managed.email_otp import EmailOtpFlow, EmailOtpFlowError
from matriosha.core.managed.rate_limit import LoginRateLimiter
from matriosha.core.managed.token_store import TokenStore, TokenStoreError


__all__ = [
    "AuthCommandError",
    "EmailOtpFlow",
    "EmailOtpFlowError",
    "LoginRateLimiter",
    "ManagedClient",
    "ManagedClientError",
    "Profile",
    "TokenStore",
    "TokenStoreError",
    "_emit_error",
    "_map_managed_error",
    "_profile_and_endpoint",
    "ensure_managed_key_bootstrap",
    "ensure_managed_passphrase_in_payload",
    "get_active_profile",
    "load_config",
    "require_mode",
    "resolve_access_token",
    "resolve_managed_endpoint",
    "save_config",
]


@dataclass
class AuthCommandError(Exception):
    title: str
    category: str
    code: str
    exit_code: int
    fix: str
    debug: str


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
    profile_name = gctx.profile or cfg.active_profile

    profile = cfg.profiles.get(profile_name)
    if profile is None:
        profile = Profile(name=profile_name, mode="managed")
        cfg.profiles[profile_name] = profile
        cfg.active_profile = profile_name
        save_config(cfg)
    elif profile.mode != "managed":
        profile.mode = "managed"
        cfg.profiles[profile_name] = profile
        cfg.active_profile = profile_name
        save_config(cfg)

    endpoint = resolve_managed_endpoint(
        profile.managed_endpoint,
        os.getenv("MATRIOSHA_MANAGED_ENDPOINT"),
    )

    if not endpoint:
        raise AuthCommandError(
            "Managed endpoint is not configured",
            category="SYS",
            code="SYS-601",
            exit_code=EXIT_UNKNOWN,
            fix="set profile.managed_endpoint or MATRIOSHA_MANAGED_ENDPOINT",
            debug="missing endpoint",
        )
    return profile, endpoint


def _map_managed_error(exc: ManagedClientError) -> AuthCommandError:
    exit_code = (
        EXIT_AUTH
        if exc.category == "AUTH"
        else EXIT_NETWORK
        if exc.category == "NET"
        else EXIT_UNKNOWN
    )
    return AuthCommandError(
        exc.message,
        category=exc.category,
        code=exc.code,
        exit_code=exit_code,
        fix=exc.remediation,
        debug=exc.debug_hint,
    )
