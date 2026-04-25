"""Billing upgrade command."""

from __future__ import annotations

from .common import *

def register(app: typer.Typer) -> None:
    @app.command("upgrade")
    def upgrade(
        ctx: typer.Context,
        json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    ) -> None:
        """Upgrade managed subscription by one 3-agent pack via Stripe quantity update."""

        gctx = get_global_context(ctx)
        json_output = gctx.json_output or json_output_flag
        endpoint, profile_name = _require_managed_mode(json_output, gctx.plain)
        token = _resolve_managed_token(profile_name, json_output, gctx.plain)
        secrets = _resolve_billing_secrets(json_output, gctx.plain)
        stripe_key = secrets["STRIPE_SECRET_KEY"]

        try:
            subscription = asyncio.run(_get_subscription(token, endpoint))
            current_packs = _parse_pack_count(subscription)
            target_packs = current_packs + 1
            stripe_subscription_id, stripe_item_id = _extract_stripe_ids(subscription)
            resolved_item_id = stripe_item_id or _fetch_subscription_item_id(stripe_key, stripe_subscription_id)
            _update_stripe_quantity(stripe_key, stripe_subscription_id, resolved_item_id, target_packs)
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
                        "delta": {
                            "monthly_price_eur": 9,
                            "agent_quota": 3,
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
                ("delta", "+€9/month, +3 agents, +3 GB"),
                ("catalog", f"base={BASE_PLAN_ID} addon={ADDON_PLAN_ID}"),
            ],
            status_chip="✓ ACTIVE",
            style="success",
        )
        raise typer.Exit(code=0)

