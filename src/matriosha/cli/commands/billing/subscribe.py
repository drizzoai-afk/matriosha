"""Billing subscribe command."""

from __future__ import annotations

import asyncio
import json

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_UNKNOWN, EXIT_USAGE
from matriosha.core.managed.client import ManagedClientError

from .common import (
    ADDON_PLAN_ID,
    AGENTS_PER_PACK,
    BASE_PLAN_ID,
    BYTES_PER_PACK,
    PACK_EUR,
    SUBSCRIBE_POLL_SECONDS,
    SUBSCRIBE_TIMEOUT_SECONDS,
    BillingError,
    _bytes_to_gb_text,
    _emit_error,
    _parse_checkout_url,
    _poll_subscription_until_active,
    _print_checkout_url_with_qr,
    _render_card,
    _require_managed_mode,
    _resolve_billing_secrets,
    _resolve_managed_token,
    _safe_int,
    _start_checkout,
)

def register(app: typer.Typer) -> None:
    @app.command("subscribe")
    def subscribe(
        ctx: typer.Context,
        agent_pack_count: int = typer.Option(1, "--agent-pack-count", help="Number of 3-agent billing packs."),
        json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    ) -> None:
        """Start checkout for a managed subscription."""

        gctx = get_global_context(ctx)
        json_output = gctx.json_output or json_output_flag
        endpoint, profile_name = _require_managed_mode(json_output, gctx.plain)
        token = _resolve_managed_token(profile_name, json_output, gctx.plain)
        _resolve_billing_secrets(json_output, gctx.plain)

        if agent_pack_count <= 0:
            _emit_error(
                BillingError(
                    "Invalid agent pack count",
                    category="VAL",
                    code="VAL-401",
                    exit_code=EXIT_USAGE,
                    fix="use --agent-pack-count with a positive integer (1, 2, 3, ...)",
                    debug=f"agent_pack_count={agent_pack_count}",
                ),
                json_output=json_output,
                plain=gctx.plain,
            )

        quota = AGENTS_PER_PACK * agent_pack_count
        storage_cap_bytes = BYTES_PER_PACK * agent_pack_count
        monthly_price_eur = PACK_EUR * agent_pack_count

        try:
            checkout = asyncio.run(_start_checkout(token, endpoint, quantity=agent_pack_count))
            checkout_url = _parse_checkout_url(checkout)
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
        except BillingError as exc:
            _emit_error(exc, json_output=json_output, plain=gctx.plain)

        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "status": "pending",
                        "checkout_url": checkout_url,
                        "agent_pack_count": agent_pack_count,
                    },
                    sort_keys=True,
                )
            )
        else:
            _render_card(
                "CHECKOUT STARTED",
                [
                    ("monthly", f"€{monthly_price_eur}/month"),
                    ("agents", str(quota)),
                    ("storage_cap", _bytes_to_gb_text(storage_cap_bytes)),
                    ("catalog", f"base={BASE_PLAN_ID} addon={ADDON_PLAN_ID}"),
                ],
                status_chip="ℹ PENDING",
                style="accent",
            )
            _print_checkout_url_with_qr(checkout_url, plain=gctx.plain)

        try:
            subscription = _poll_subscription_until_active(
                token,
                endpoint,
                timeout_seconds=SUBSCRIBE_TIMEOUT_SECONDS,
                poll_seconds=SUBSCRIBE_POLL_SECONDS,
                show_progress=not (json_output or gctx.plain),
            )
        except BillingError as exc:
            _emit_error(exc, json_output=json_output, plain=gctx.plain)

        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "status": "active",
                        "agent_quota": _safe_int(subscription.get("agent_quota"), quota),
                        "storage_cap_bytes": _safe_int(subscription.get("storage_cap_bytes"), storage_cap_bytes),
                        "monthly_price_eur": monthly_price_eur,
                    },
                    sort_keys=True,
                )
            )
            raise typer.Exit(code=0)

        _render_card(
            "SUBSCRIPTION ACTIVE",
            [
                ("status", str(subscription.get("status", "active"))),
                ("monthly", f"€{monthly_price_eur}/month"),
                ("agents", str(_safe_int(subscription.get("agent_quota"), quota))),
                ("storage_cap", _bytes_to_gb_text(_safe_int(subscription.get("storage_cap_bytes"), storage_cap_bytes))),
            ],
            status_chip="✓ ACTIVE",
            style="success",
        )
        raise typer.Exit(code=0)

