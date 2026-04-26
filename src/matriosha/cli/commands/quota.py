"""Managed quota command group."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_AUTH, EXIT_MODE, EXIT_UNKNOWN
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.managed.auth import resolve_access_token
from matriosha.core.managed.client import ManagedClient, ManagedClientError

app = typer.Typer(help="Show storage use and plan limits.", no_args_is_help=True)


def _format_bytes(value: Any) -> str:
    try:
        size = int(value)
    except (TypeError, ValueError):
        size = 0

    units = [
        ("B", 1),
        ("KiB", 1024),
        ("MiB", 1024**2),
        ("GiB", 1024**3),
    ]

    if size < 1024:
        return f"{size}B"
    if size < 1024**2:
        return f"{size / 1024:.2f}KiB"
    if size < 1024**3:
        return f"{size / (1024**2):.2f}MiB"
    return f"{size / (1024**3):.2f}GiB"


def _emit_error(message: str, *, code: int, json_output: bool) -> None:
    if code == EXIT_AUTH:
        category = "AUTH"
        stable_code = "AUTH-QUOTA-001"
        title = "Managed session token missing"
        fix = "run `matriosha auth login`"
        debug = "missing managed access token"
    elif code == EXIT_MODE:
        category = "MODE"
        stable_code = "MODE-QUOTA-001"
        title = "Quota status requires managed mode"
        fix = "run `matriosha mode set managed`"
        debug = "active profile is not managed"
    else:
        category = "SYS"
        stable_code = "SYS-QUOTA-001"
        title = "Quota lookup failed"
        fix = "check managed endpoint, network access, and backend availability"
        debug = message

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "status": "error",
                    "title": title,
                    "category": category,
                    "code": stable_code,
                    "exit": code,
                    "fix": fix,
                    "debug": debug,
                },
                sort_keys=True,
            )
        )
    else:
        typer.echo(f"✖ {title}")
        typer.echo(f"fix: {fix}")
        typer.echo(f"debug: {debug}")
    raise typer.Exit(code=code)


@app.command("status")
def status(
    ctx: typer.Context,
    json_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
) -> None:
    """Show storage use, agent use, and plan limits."""

    gctx = get_global_context(ctx)
    json_output = gctx.json_output or json_flag

    cfg = load_config()
    profile = get_active_profile(cfg, gctx.profile)
    if profile.mode != "managed":
        _emit_error("this command requires managed mode; run `matriosha mode set managed`", code=EXIT_MODE, json_output=json_output)

    token = resolve_access_token(profile.name)
    if not token:
        _emit_error("managed session token missing; run `matriosha auth login`", code=EXIT_AUTH, json_output=json_output)

    endpoint = profile.managed_endpoint or os.getenv("MATRIOSHA_MANAGED_ENDPOINT")

    async def _fetch() -> dict[str, Any]:
        async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
            return await client.get_subscription()

    try:
        subscription = asyncio.run(_fetch())
    except ManagedClientError as exc:
        _emit_error(f"quota lookup failed: {exc.message}", code=EXIT_UNKNOWN, json_output=json_output)

    agent_quota = int(subscription.get("agent_quota") or 0)
    agent_in_use = int(subscription.get("agent_in_use") or 0)
    storage_cap_bytes = int(subscription.get("storage_cap_bytes") or 0)
    storage_used_bytes = int(subscription.get("storage_used_bytes") or 0)
    pct = (storage_used_bytes / storage_cap_bytes * 100.0) if storage_cap_bytes > 0 else 0.0

    payload = {
        "status": "ok",
        "operation": "quota.status",
        "agent_quota": agent_quota,
        "agent_in_use": agent_in_use,
        "agent_available": max(0, agent_quota - agent_in_use),
        "storage_cap_bytes": storage_cap_bytes,
        "storage_used_bytes": storage_used_bytes,
        "storage_used_percent": round(pct, 2),
    }

    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True))
    else:
        typer.echo(f"agents: {agent_in_use}/{agent_quota} in use")
        typer.echo(
            f"storage: {_format_bytes(storage_used_bytes)}/{_format_bytes(storage_cap_bytes)} ({payload['storage_used_percent']:.2f}%)"
        )
    raise typer.Exit(code=0)
