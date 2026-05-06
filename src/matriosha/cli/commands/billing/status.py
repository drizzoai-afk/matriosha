"""Billing status command."""

from __future__ import annotations

import asyncio
import json

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_UNKNOWN
from matriosha.core.managed.client import ManagedClientError

from .common import (
    BillingError,
    _emit_error,
    _get_subscription,
    _render_card,
    _require_managed_mode,
    _resolve_managed_token,
    _status_rows,
)


def register(app: typer.Typer) -> None:
    @app.command("status")
    def status(
        ctx: typer.Context,
        json_output_flag: bool = typer.Option(
            False, "--json", help="Show JSON output for scripts and automation."
        ),
    ) -> None:
        """Show subscription, agent limit, and storage limit."""

        gctx = get_global_context(ctx)
        json_output = gctx.json_output or json_output_flag
        endpoint, profile_name = _require_managed_mode(json_output, gctx.plain)
        token = _resolve_managed_token(profile_name, json_output, gctx.plain)

        try:
            subscription = asyncio.run(_get_subscription(token, endpoint))
        except ManagedClientError as exc:
            _emit_error(
                BillingError(
                    exc.message,
                    category=exc.category,
                    code=exc.code,
                    exit_code=EXIT_UNKNOWN,
                    fix=exc.remediation,
                    debug=exc.debug_hint,
                ),
                json_output=json_output,
                plain=gctx.plain,
            )

        if json_output:
            typer.echo(json.dumps(subscription, sort_keys=True))
            raise typer.Exit(code=0)

        if gctx.plain:
            for key, value in _status_rows(subscription):
                typer.echo(f"{key}: {value}")
            raise typer.Exit(code=0)

        sub_status = str(subscription.get("status", "unknown")).upper()
        chip = "✓ ACTIVE" if sub_status in {"ACTIVE", "TRIALING"} else "⚠ STATUS"
        style = "green" if chip.startswith("✓") else "yellow"
        _render_card("BILLING STATUS", _status_rows(subscription), status_chip=chip, style=style)
        raise typer.Exit(code=0)
