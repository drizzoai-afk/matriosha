"""Managed-mode credential resolution via Google Secret Manager (GSM).

This module is intentionally read-only and keeps resolved credentials in memory only.
No credential values are written to disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping

from matriosha.core.secrets import SecretManager

_REQUIRED_MANAGED_SECRETS = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_ANON_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
)

_SUPABASE_SECRET_NAMES = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_ANON_KEY",
    "SUPABASE_JWT_SECRET",
    "SUPABASE_PASSWORD",
)

_STRIPE_SECRET_NAMES = (
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_PUBLISHABLE_KEY",
)


class ManagedSecretError(RuntimeError):
    """Raised for managed credential resolution issues."""


@dataclass(frozen=True)
class SecretValue:
    name: str
    value: str
    source: str


@dataclass(frozen=True)
class RuntimeSecrets:
    values: dict[str, SecretValue]

    def get(self, name: str) -> SecretValue:
        return self.values.get(name, SecretValue(name=name, value="", source="missing"))

    def missing(self, required_names: tuple[str, ...] | list[str] | None = None) -> list[str]:
        names = tuple(required_names or _REQUIRED_MANAGED_SECRETS)
        return [name for name in names if not self.get(name).value]


@dataclass(frozen=True)
class SupabaseCredentials:
    url: str
    service_role_key: str
    anon_key: str
    jwt_secret: str = ""
    password: str = ""


@dataclass(frozen=True)
class StripeCredentials:
    secret_key: str
    webhook_secret: str
    publishable_key: str = ""


def _resolve_from_gsm(gsm: SecretManager, name: str) -> SecretValue | None:
    try:
        value = gsm.get_secret(name)
    except Exception:  # noqa: BLE001
        value = None
    if value:
        return SecretValue(name=name, value=value, source="gsm")
    return None


def _resolve_secret(
    name: str,
    *,
    gsm: SecretManager,
    allow_env_fallback: bool,
    fallback_values: Mapping[str, str] | None,
) -> SecretValue:
    gsm_secret = _resolve_from_gsm(gsm, name)
    if gsm_secret:
        return gsm_secret

    if allow_env_fallback:
        env_value = os.getenv(name)
        if env_value:
            return SecretValue(name=name, value=env_value, source="env")

    if fallback_values and fallback_values.get(name):
        return SecretValue(name=name, value=str(fallback_values[name]), source="fallback")

    return SecretValue(name=name, value="", source="missing")


@lru_cache(maxsize=32)
def _cached_runtime_secrets(
    names: tuple[str, ...],
    allow_env_fallback: bool,
    project_id: str,
    env_signature: tuple[tuple[str, str], ...],
) -> RuntimeSecrets:
    _ = env_signature  # Cache-key only, ensures env changes invalidate cached credentials.
    gsm = SecretManager(project_id=project_id or None)
    values = {
        name: _resolve_secret(
            name,
            gsm=gsm,
            allow_env_fallback=allow_env_fallback,
            fallback_values=None,
        )
        for name in names
    }
    return RuntimeSecrets(values=values)


def clear_secret_cache() -> None:
    """Clear in-memory managed secret cache."""

    _cached_runtime_secrets.cache_clear()


def load_runtime_secrets(
    names: tuple[str, ...] | list[str] | None = None,
    *,
    allow_env_fallback: bool = True,
    project_id: str | None = None,
    force_refresh: bool = False,
) -> RuntimeSecrets:
    """Load managed runtime secrets with GSM-first lookup.

    Lookup order:
    1) Google Secret Manager
    2) Environment variable fallback (optional)
    """

    if force_refresh:
        clear_secret_cache()

    resolved_project_id = (
        project_id
        or os.getenv("GCP_PROJECT_ID")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCLOUD_PROJECT")
        or ""
    )
    target_names = tuple(names or _REQUIRED_MANAGED_SECRETS)
    env_signature = (
        tuple((name, os.getenv(name) or "") for name in target_names) if allow_env_fallback else ()
    )
    return _cached_runtime_secrets(
        target_names, allow_env_fallback, resolved_project_id, env_signature
    )


def get_secret_value(
    name: str,
    *,
    allow_env_fallback: bool = True,
    project_id: str | None = None,
    force_refresh: bool = False,
) -> SecretValue:
    secrets = load_runtime_secrets(
        [name],
        allow_env_fallback=allow_env_fallback,
        project_id=project_id,
        force_refresh=force_refresh,
    )
    return secrets.get(name)


def get_required_secret(
    name: str,
    *,
    allow_env_fallback: bool = True,
    project_id: str | None = None,
) -> str:
    secret = get_secret_value(name, allow_env_fallback=allow_env_fallback, project_id=project_id)
    if secret.value:
        return secret.value
    raise ManagedSecretError(
        f"Missing required secret '{name}'. Add it to Google Secret Manager"
        " (preferred) or set it as an environment variable for local development."
    )


def get_supabase_credentials(
    *, allow_env_fallback: bool = True, project_id: str | None = None
) -> SupabaseCredentials:
    secrets = load_runtime_secrets(
        _SUPABASE_SECRET_NAMES, allow_env_fallback=allow_env_fallback, project_id=project_id
    )
    return SupabaseCredentials(
        url=secrets.get("SUPABASE_URL").value,
        service_role_key=secrets.get("SUPABASE_SERVICE_ROLE_KEY").value,
        anon_key=secrets.get("SUPABASE_ANON_KEY").value,
        jwt_secret=secrets.get("SUPABASE_JWT_SECRET").value,
        password=secrets.get("SUPABASE_PASSWORD").value,
    )


def get_stripe_credentials(
    *, allow_env_fallback: bool = True, project_id: str | None = None
) -> StripeCredentials:
    secrets = load_runtime_secrets(
        _STRIPE_SECRET_NAMES, allow_env_fallback=allow_env_fallback, project_id=project_id
    )
    return StripeCredentials(
        secret_key=secrets.get("STRIPE_SECRET_KEY").value,
        webhook_secret=secrets.get("STRIPE_WEBHOOK_SECRET").value,
        publishable_key=secrets.get("STRIPE_PUBLISHABLE_KEY").value,
    )
