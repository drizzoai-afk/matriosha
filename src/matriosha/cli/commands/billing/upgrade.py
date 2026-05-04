"""Billing upgrade command."""

from __future__ import annotations

import asyncio
import json

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_UNKNOWN, EXIT_USAGE
from matriosha.core.managed.client import ManagedClientError

from .common import (
    BYTES_PER_PACK,
    AGENTS_PER_PACK,
    BillingError,
    PACK_EUR,
    _bytes_to_gb_text,
    _emit_error,
    _get_subscription,
    _parse_pack_count,
    _render_card,
    _require_managed_mode,
    _resolve_managed_token,
    _safe_int,
    _upgrade_subscription,
)

def register(app: typer.Typer) -> None:
    @app.command("upgrade")
    def upgrade(
        ctx: typer.Context,
        yes: bool = typer.Option(False, "--yes", help="Confirm the paid subscription upgrade."),
        json_output_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Add 3 more agents and 3 GB more storage."""

        gctx = get_global_context(ctx)
        json_output = gctx.json_output or json_output_flag
        endpoint, profile_name = _require_managed_mode(json_output, gctx.plain)
        token = _resolve_managed_token(profile_name, json_output, gctx.plain)

        if not yes:
            _emit_error(
                BillingError(
                    "Upgrade requires explicit confirmation",
                    category="VAL",
                    code="VAL-403",
                    exit_code=EXIT_USAGE,
                    fix="rerun with `matriosha billing upgrade --yes`",
                    debug="missing --yes",
                ),
                json_output=json_output,
                plain=gctx.plain,
            )

        try:
            subscription = asyncio.run(_get_subscription(token, endpoint))
            current_packs = _parse_pack_count(subscription)
            target_packs = current_packs + 1
            result = asyncio.run(_upgrade_subscription(token, endpoint, quantity=target_packs))
            result_subscription = result.get("subscription")
            updated_subscription: dict[str, object]
            if isinstance(result_subscription, dict):
                updated_subscription = result_subscription
            else:
                updated_subscription = result
            subscription = updated_subscription
            reactivating = bool(subscription.get("cancel_at_period_end") is False and result.get("reactivated"))
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
                        "status": "ok",
                        "current_pack_count": current_packs,
                        "target_pack_count": target_packs,
                        "reactivated": reactivating,
                        "delta": {
                            "monthly_price_eur": PACK_EUR,
                            "agent_quota": AGENTS_PER_PACK,
                            "storage_cap_bytes": BYTES_PER_PACK,
                        },
                    },
                    sort_keys=True,
                )
            )
            raise typer.Exit(code=0)

        _render_card(
            "SUBSCRIPTION UPGRADED",
            [
                ("packs", f"{current_packs} → {target_packs}"),
                ("reactivated", "yes" if reactivating else "no"),
                ("delta", f"+€{PACK_EUR}/month, +{AGENTS_PER_PACK} agents, +3 GB"),
                ("agents", str(_safe_int(subscription.get("agent_quota"), AGENTS_PER_PACK * target_packs))),
                ("storage_cap", _bytes_to_gb_text(_safe_int(subscription.get("storage_cap_bytes"), BYTES_PER_PACK * target_packs))),
            ],
            status_chip="✓ ACTIVE",
            style="success",
        )
        raise typer.Exit(code=0)

