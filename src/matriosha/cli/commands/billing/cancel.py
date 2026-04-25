"""Billing cancel command."""

from __future__ import annotations

import asyncio
import json

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_UNKNOWN, EXIT_USAGE
from matriosha.core.managed.client import ManagedClientError

from .common import (
    BillingError,
    _cancel_subscription,
    _emit_error,
    _format_date,
    _render_card,
    _require_managed_mode,
    _resolve_managed_token,
)

def register(app: typer.Typer) -> None:
    @app.command("cancel")
    def cancel(
        ctx: typer.Context,
        yes: bool = typer.Option(False, "--yes", help="Confirm cancellation at period end."),
        json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    ) -> None:
        """Cancel managed subscription at period end."""

        gctx = get_global_context(ctx)
        json_output = gctx.json_output or json_output_flag
        endpoint, profile_name = _require_managed_mode(json_output, gctx.plain)
        token = _resolve_managed_token(profile_name, json_output, gctx.plain)

        if not yes:
            _emit_error(
                BillingError(
                    "Cancellation requires explicit confirmation",
                    category="VAL",
                    code="VAL-402",
                    exit_code=EXIT_USAGE,
                    fix="rerun with `matriosha billing cancel --yes`",
                    debug="missing --yes",
                ),
                json_output=json_output,
                plain=gctx.plain,
            )

        try:
            result = asyncio.run(_cancel_subscription(token, endpoint))
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

        until = _format_date(result.get("current_period_end") or result.get("renews_on") or result.get("effective_date"))
        message = f"Subscription canceled, access until {until}"

        if json_output:
            typer.echo(json.dumps({"status": "ok", "message": message, "access_until": until}, sort_keys=True))
            raise typer.Exit(code=0)

        if gctx.plain:
            typer.echo(message)
            raise typer.Exit(code=0)

        _render_card(
            "SUBSCRIPTION CANCELED",
            [("message", message)],
            status_chip="⚠ PENDING",
            style="warning",
        )
        raise typer.Exit(code=0)

