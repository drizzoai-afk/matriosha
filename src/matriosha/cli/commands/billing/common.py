"""Managed billing commands (status / subscribe / upgrade / cancel)."""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import click
import httpx
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from matriosha.cli.brand.theme import console as make_console
from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_AUTH, EXIT_MODE, EXIT_NETWORK, EXIT_UNKNOWN, EXIT_USAGE
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.managed.auth import resolve_access_token
from matriosha.core.managed.client import ManagedClient, ManagedClientError
from matriosha.core.managed.secrets import get_stripe_credentials, get_supabase_credentials

PACK_EUR = 9
AGENTS_PER_PACK = 3
BYTES_PER_PACK = 3 * 1024 * 1024 * 1024
SUBSCRIBE_TIMEOUT_SECONDS = 600
SUBSCRIBE_POLL_SECONDS = 5

_ORIGINAL_load_config = load_config
_ORIGINAL_get_active_profile = get_active_profile
_ORIGINAL_ManagedClient = ManagedClient

BASE_PLAN_ID = "matriosha_base_3_agents_eur_900_monthly"
ADDON_PLAN_ID = "matriosha_addon_3_agents_eur_900_monthly"
STRIPE_API_BASE = "https://api.stripe.com"


class BillingError(RuntimeError):
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


def _render_card(title: str, rows: list[tuple[str, str]], *, status_chip: str, style: str) -> None:
    console = make_console()
    width = 88
    inner = width - 2
    header = f" {status_chip} {title} "
    header_pad = max(0, inner - len(header))
    console.print(
        f"[{style}]╭{'─' * (header_pad // 2)}{header}{'─' * (header_pad - (header_pad // 2))}╮[/{style}]"
    )
    for key, value in rows:
        line = f" {key:<14} {value} "
        console.print(f"[{style}]│{line:<{inner}}│[/{style}]")
    console.print(f"[{style}]╰{'─' * inner}╯[/{style}]")


def _emit_error(err: BillingError, *, json_output: bool, plain: bool) -> None:
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
                }
            )
        )
        raise typer.Exit(code=err.exit_code)

    if plain:
        typer.echo(f"✖ {err.title}")
        typer.echo(f"category: {err.category}  code: {err.code}  exit: {err.exit_code}")
        typer.echo(f"fix: {err.fix}")
        typer.echo(f"debug: {err.debug}")
        raise typer.Exit(code=err.exit_code)

    _render_card(
        err.title,
        [
            ("category", f"{err.category}  code: {err.code}  exit: {err.exit_code}"),
            ("fix", err.fix),
            ("debug", err.debug),
        ],
        status_chip="✖ ERROR",
        style="danger",
    )
    raise typer.Exit(code=err.exit_code)


def _bytes_to_gb_text(value: int | None) -> str:
    if value is None:
        return "n/a"
    return f"{(value / (1024**3)):.1f} GB"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_pack_count(subscription: dict[str, Any]) -> int:
    if "agent_pack_count" in subscription:
        return max(1, _safe_int(subscription.get("agent_pack_count"), 1))

    quantity = _safe_int(subscription.get("quantity"), 0)
    if quantity > 0:
        return quantity

    agent_quota = _safe_int(subscription.get("agent_quota"), 0)
    if agent_quota > 0:
        return max(1, agent_quota // AGENTS_PER_PACK)

    return 1


def _format_date(value: Any) -> str:
    if not value:
        return "n/a"
    if isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        return dt.date().isoformat()
    text = str(value)
    if "T" in text:
        return text.split("T", 1)[0]
    return text


def _package_patchable(name: str, fallback: Any) -> Any:
    package = sys.modules.get("matriosha.cli.commands.billing")
    if package is None:
        return fallback
    value = getattr(package, name, fallback)
    original = globals().get(f"_ORIGINAL_{name}", None)
    if original is not None and value is original:
        return fallback
    return value


def _resolve_profile_mode() -> tuple[str, str | None, str]:
    gctx_profile = get_global_context(click.get_current_context()).profile
    patched_load_config = _package_patchable("load_config", load_config)
    patched_get_active_profile = _package_patchable("get_active_profile", get_active_profile)
    cfg = patched_load_config()
    profile = patched_get_active_profile(cfg, gctx_profile)
    return profile.mode, profile.managed_endpoint, profile.name


def _require_managed_mode(json_output: bool, plain: bool) -> tuple[str | None, str]:
    mode, endpoint, profile_name = _resolve_profile_mode()
    if mode != "managed":
        _ = json_output
        _ = plain
        typer.echo("this command requires managed mode; run `matriosha mode set managed`")
        raise typer.Exit(code=EXIT_MODE)
    return endpoint, profile_name


def _resolve_managed_token(profile_name: str, json_output: bool, plain: bool) -> str:
    token = resolve_access_token(profile_name)
    if token:
        return token
    _emit_error(
        BillingError(
            "Managed session token missing",
            category="AUTH",
            code="AUTH-301",
            exit_code=EXIT_AUTH,
            fix="set MATRIOSHA_MANAGED_TOKEN or run `matriosha auth login`",
            debug="missing MATRIOSHA_MANAGED_TOKEN",
        ),
        json_output=json_output,
        plain=plain,
    )
    return ""


def _resolve_billing_secrets(json_output: bool, plain: bool) -> dict[str, str]:
    stripe = get_stripe_credentials(allow_env_fallback=True)
    supabase = get_supabase_credentials(allow_env_fallback=True)

    if not stripe.secret_key or not stripe.webhook_secret:
        _emit_error(
            BillingError(
                "Billing configuration is incomplete",
                category="PAY",
                code="PAY-001",
                exit_code=EXIT_UNKNOWN,
                fix="add Stripe secrets in Google Secret Manager, then rerun this command",
                debug="missing STRIPE_SECRET_KEY or STRIPE_WEBHOOK_SECRET",
            ),
            json_output=json_output,
            plain=plain,
        )

    return {
        "STRIPE_SECRET_KEY": stripe.secret_key,
        "STRIPE_WEBHOOK_SECRET": stripe.webhook_secret,
        "STRIPE_PUBLISHABLE_KEY": stripe.publishable_key,
        "SUPABASE_URL": supabase.url,
        "SUPABASE_SERVICE_ROLE_KEY": supabase.service_role_key,
        "SUPABASE_ANON_KEY": supabase.anon_key,
    }


async def _get_subscription(token: str, endpoint: str | None) -> dict[str, Any]:
    client_cls = _package_patchable("ManagedClient", ManagedClient)
    async with client_cls(token=token, base_url=endpoint, managed_mode=False) as client:
        return await client.get_subscription()


async def _start_checkout(token: str, endpoint: str | None, quantity: int) -> dict[str, Any]:
    client_cls = _package_patchable("ManagedClient", ManagedClient)
    async with client_cls(token=token, base_url=endpoint, managed_mode=False) as client:
        return await client.start_checkout(plan="eur_monthly", quantity=quantity)


async def _cancel_subscription(token: str, endpoint: str | None) -> dict[str, Any]:
    client_cls = _package_patchable("ManagedClient", ManagedClient)
    async with client_cls(token=token, base_url=endpoint, managed_mode=False) as client:
        return await client.cancel_subscription()


def _parse_checkout_url(payload: dict[str, Any]) -> str:
    for key in ("checkout_url", "url", "checkoutUrl"):
        url = payload.get(key)
        if isinstance(url, str) and url:
            return url
    raise BillingError(
        "Checkout session response is missing URL",
        category="PAY",
        code="PAY-002",
        exit_code=EXIT_UNKNOWN,
        fix="retry subscribe; if issue persists, contact support",
        debug="stripe checkout url missing from managed response",
    )


def _print_checkout_url_with_qr(url: str, *, plain: bool) -> None:
    typer.echo(f"Checkout URL: {url}")
    if plain:
        return
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        out = io.StringIO()
        qr.print_ascii(out=out, invert=True)
        typer.echo(out.getvalue())
    except Exception:
        typer.echo("(QR rendering unavailable; open the checkout URL above)")


def _poll_subscription_until_active(
    token: str,
    endpoint: str | None,
    *,
    timeout_seconds: int,
    poll_seconds: int,
    show_progress: bool,
) -> dict[str, Any]:
    started = time.monotonic()
    attempts = 0

    progress_ctx = (
        Progress(
            SpinnerColumn(),
            TextColumn("[bold accent]{task.description}"),
            TimeElapsedColumn(),
            transient=True,
        )
        if show_progress
        else None
    )

    if progress_ctx:
        progress_ctx.__enter__()
        task = progress_ctx.add_task("Waiting for checkout completion", total=None)
    else:
        task = None

    try:
        while time.monotonic() - started <= timeout_seconds:
            attempts += 1
            subscription = asyncio.run(_get_subscription(token, endpoint))
            status = str(subscription.get("status", "")).lower()
            if status in {"active", "trialing"}:
                return subscription
            if status in {"canceled", "incomplete_expired", "unpaid"}:
                raise BillingError(
                    "Subscription entered an unexpected terminal state",
                    category="PAY",
                    code="PAY-004",
                    exit_code=EXIT_UNKNOWN,
                    fix="restart checkout or contact support",
                    debug=f"subscription_status={status} attempts={attempts}",
                )
            if progress_ctx and task is not None:
                progress_ctx.update(task, description=f"Waiting for checkout completion (attempt {attempts})")
            time.sleep(poll_seconds)
    finally:
        if progress_ctx:
            progress_ctx.__exit__(None, None, None)

    raise BillingError(
        "Checkout confirmation timed out",
        category="PAY",
        code="PAY-003",
        exit_code=EXIT_NETWORK,
        fix="complete checkout and rerun `matriosha billing status`",
        debug=f"timeout={timeout_seconds}s",
    )


def _status_rows(subscription: dict[str, Any]) -> list[tuple[str, str]]:
    pack_count = _parse_pack_count(subscription)
    monthly_price = PACK_EUR * pack_count
    agent_quota = _safe_int(subscription.get("agent_quota"), AGENTS_PER_PACK * pack_count)
    agent_in_use = _safe_int(subscription.get("agent_in_use"), 0)
    storage_cap = _safe_int(subscription.get("storage_cap_bytes"), BYTES_PER_PACK * pack_count)
    storage_used = _safe_int(subscription.get("storage_used_bytes"), 0)

    return [
        ("plan", str(subscription.get("plan") or subscription.get("plan_code") or "eur_monthly")),
        ("status", str(subscription.get("status") or "unknown")),
        ("monthly", f"€{monthly_price}/month ({pack_count} packs × €9)"),
        ("dates", f"period_end={_format_date(subscription.get('current_period_end') or subscription.get('renews_on'))}"),
        ("agents", f"{agent_quota} total / {agent_in_use} in use"),
        ("storage", f"{_bytes_to_gb_text(storage_cap)} cap / {_bytes_to_gb_text(storage_used)} used"),
    ]


def _extract_stripe_ids(subscription: dict[str, Any]) -> tuple[str, str | None]:
    sub_id = str(subscription.get("stripe_subscription_id") or "")
    item_id = subscription.get("stripe_subscription_item_id")

    if not sub_id and isinstance(subscription.get("stripe"), dict):
        stripe_data = subscription["stripe"]
        sub_id = str(stripe_data.get("subscription_id") or "")
        item_id = item_id or stripe_data.get("subscription_item_id")

    if not sub_id:
        raise BillingError(
            "Subscription state drift detected",
            category="PAY",
            code="PAY-020",
            exit_code=EXIT_UNKNOWN,
            fix="run `matriosha billing status` and contact support if Stripe IDs are missing",
            debug="stripe_subscription_id missing",
        )

    return sub_id, str(item_id) if item_id else None


def _fetch_subscription_item_id(stripe_key: str, stripe_subscription_id: str) -> str:
    headers = {"Authorization": f"Bearer {stripe_key}"}
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(f"{STRIPE_API_BASE}/v1/subscriptions/{stripe_subscription_id}", headers=headers)
    except httpx.HTTPError as exc:
        raise BillingError(
            "Could not reach Stripe API",
            category="NET",
            code="NET-500",
            exit_code=EXIT_NETWORK,
            fix="check network and retry upgrade",
            debug=f"endpoint=/v1/subscriptions timeout=15s error={exc.__class__.__name__}",
        ) from exc

    if response.status_code >= 400:
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        err = body.get("error", {}) if isinstance(body, dict) else {}
        raise BillingError(
            "Stripe rejected subscription lookup",
            category="PAY",
            code="PAY-021",
            exit_code=EXIT_UNKNOWN,
            fix="retry upgrade or contact support",
            debug=(
                f"stripe_code={err.get('code')} request_id={response.headers.get('request-id')} "
                f"http_status={response.status_code}"
            ),
        )

    payload = response.json()
    items = payload.get("items", {}).get("data", []) if isinstance(payload, dict) else []
    if not items:
        raise BillingError(
            "Stripe subscription has no billable items",
            category="PAY",
            code="PAY-022",
            exit_code=EXIT_UNKNOWN,
            fix="contact support to repair your subscription catalog",
            debug=f"subscription_id={stripe_subscription_id}",
        )

    item_id = items[0].get("id")
    if not item_id:
        raise BillingError(
            "Stripe subscription item missing",
            category="PAY",
            code="PAY-023",
            exit_code=EXIT_UNKNOWN,
            fix="contact support to repair your subscription item",
            debug=f"subscription_id={stripe_subscription_id}",
        )
    return str(item_id)


def _update_stripe_quantity(stripe_key: str, stripe_subscription_id: str, item_id: str, quantity: int) -> None:
    headers = {"Authorization": f"Bearer {stripe_key}"}
    form = {
        "items[0][id]": item_id,
        "items[0][quantity]": str(quantity),
        "proration_behavior": "create_prorations",
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(f"{STRIPE_API_BASE}/v1/subscriptions/{stripe_subscription_id}", headers=headers, data=form)
    except httpx.HTTPError as exc:
        raise BillingError(
            "Could not reach Stripe API",
            category="NET",
            code="NET-501",
            exit_code=EXIT_NETWORK,
            fix="check network and retry upgrade",
            debug=f"endpoint=/v1/subscriptions/{stripe_subscription_id} timeout=15s error={exc.__class__.__name__}",
        ) from exc

    if response.status_code >= 400:
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        err = body.get("error", {}) if isinstance(body, dict) else {}
        raise BillingError(
            "Stripe rejected subscription update",
            category="PAY",
            code="PAY-024",
            exit_code=EXIT_UNKNOWN,
            fix="verify payment method and retry upgrade",
            debug=(
                f"stripe_code={err.get('code')} request_id={response.headers.get('request-id')} "
                f"http_status={response.status_code}"
            ),
        )

    payload = response.json()
    updated_items = payload.get("items", {}).get("data", []) if isinstance(payload, dict) else []
    updated_quantity = _safe_int(updated_items[0].get("quantity") if updated_items else None, -1)
    if updated_quantity != quantity:
        raise BillingError(
            "Subscription quantity update drift detected",
            category="PAY",
            code="PAY-025",
            exit_code=EXIT_UNKNOWN,
            fix="run `matriosha billing status` and retry; contact support if mismatch persists",
            debug=f"expected_quantity={quantity} actual_quantity={updated_quantity}",
        )



__all__ = [
    name
    for name in globals()
    if not name.startswith("__")
]
