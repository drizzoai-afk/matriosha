#!/usr/bin/env python3
"""Verify Google Secret Manager setup for Matriosha managed backend.

Checks:
1) Required secrets are present (and indicates source: gsm/env/missing)
2) Supabase connectivity with managed credentials
3) Stripe connectivity with managed credentials

This script never prints raw secret values.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from matriosha.core.managed.secrets import (  # noqa: E402
    get_stripe_credentials,
    get_supabase_credentials,
    load_runtime_secrets,
)

REQUIRED_SECRETS = (
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_JWT_SECRET",
    "SUPABASE_PASSWORD",
    "STRIPE_SECRET_KEY",
    "STRIPE_PUBLISHABLE_KEY",
    "STRIPE_WEBHOOK_SECRET",
)

OPTIONAL_SECRETS = ("MATRIOSHA_VAULT_SERVER_PUBKEY",)


@dataclass
class CheckResult:
    ok: bool
    message: str


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def _mask(value: str) -> str:
    if not value:
        return "<missing>"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]} (len={len(value)})"


def check_secret_presence() -> CheckResult:
    _print_header("1) Checking secrets in GSM")
    runtime = load_runtime_secrets(
        REQUIRED_SECRETS + OPTIONAL_SECRETS, allow_env_fallback=True, force_refresh=True
    )

    missing_required: list[str] = []
    non_gsm_required: list[str] = []

    for name in REQUIRED_SECRETS:
        sv = runtime.get(name)
        if not sv.value:
            missing_required.append(name)
            print(f"❌ {name}: missing")
            continue

        source_label = sv.source.upper()
        if sv.source != "gsm":
            non_gsm_required.append(name)
            print(f"⚠️  {name}: found from {source_label} (recommended: GSM)")
        else:
            print(f"✅ {name}: found in GSM")

    for name in OPTIONAL_SECRETS:
        sv = runtime.get(name)
        if sv.value:
            print(f"✅ Optional secret present ({sv.source.upper()})")
        else:
            print("ℹ️  Optional secret not set")

    if missing_required:
        return CheckResult(False, f"Missing required secrets: {', '.join(missing_required)}")

    if non_gsm_required:
        return CheckResult(
            True,
            "All required secrets are available, but some are not coming from GSM: "
            + ", ".join(non_gsm_required),
        )

    return CheckResult(True, "All required secrets are present in GSM.")


def check_supabase() -> CheckResult:
    _print_header("2) Testing Supabase connectivity")
    supabase = get_supabase_credentials(allow_env_fallback=True)

    if not supabase.url or not supabase.service_role_key:
        return CheckResult(False, "Supabase URL or service role key is missing.")

    endpoint = f"{supabase.url.rstrip('/')}/auth/v1/admin/users?page=1&per_page=1"
    headers = {
        "apikey": supabase.service_role_key,
        "Authorization": f"Bearer {supabase.service_role_key}",
    }

    try:
        response = httpx.get(endpoint, headers=headers, timeout=15.0)
    except httpx.HTTPError as exc:
        return CheckResult(False, f"Could not connect to Supabase: {exc.__class__.__name__}")

    if response.status_code == 200:
        return CheckResult(True, "Supabase admin API reachable with configured credentials.")

    if response.status_code in {401, 403}:
        return CheckResult(False, "Supabase credentials are invalid or missing permissions.")

    return CheckResult(False, f"Unexpected Supabase response: HTTP {response.status_code}")


def check_stripe() -> CheckResult:
    _print_header("3) Testing Stripe connectivity")
    stripe = get_stripe_credentials(allow_env_fallback=True)

    if not stripe.secret_key:
        return CheckResult(False, "Stripe secret key is missing.")

    headers = {"Authorization": f"Bearer {stripe.secret_key}"}
    try:
        response = httpx.get("https://api.stripe.com/v1/account", headers=headers, timeout=15.0)
    except httpx.HTTPError as exc:
        return CheckResult(False, f"Could not connect to Stripe: {exc.__class__.__name__}")

    if response.status_code == 200:
        return CheckResult(True, "Stripe API reachable with configured credentials.")

    if response.status_code == 401:
        return CheckResult(False, "Stripe secret key is invalid.")

    return CheckResult(False, f"Unexpected Stripe response: HTTP {response.status_code}")


def main() -> int:
    print("Matriosha setup verification started")
    print("(No secret values will be printed)")

    checks = [check_secret_presence(), check_supabase(), check_stripe()]

    failures = [c for c in checks if not c.ok]
    warnings = [c for c in checks if c.ok and "not coming from GSM" in c.message]

    _print_header("Summary")
    for check in checks:
        icon = "✅" if check.ok else "❌"
        print(f"{icon} {check.message}")

    if warnings:
        print("\n⚠️  Recommendation: move all required secrets into GSM for best security.")

    if failures:
        print("\nSetup verification failed.")
        return 1

    print("\nSetup verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
