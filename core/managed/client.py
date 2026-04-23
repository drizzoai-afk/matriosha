"""Managed mode HTTP client for Matriosha."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from core.secrets import SecretManager, get_secret

_REQUIRED_MANAGED_SECRETS = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_ANON_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
)

_TRACKED_SECRETS = _REQUIRED_MANAGED_SECRETS


@dataclass(frozen=True)
class SecretValue:
    name: str
    value: str
    source: str


@dataclass(frozen=True)
class RuntimeSecrets:
    values: dict[str, SecretValue]

    def get(self, name: str) -> SecretValue:
        return self.values[name]

    def missing_managed(self) -> list[str]:
        missing: list[str] = []
        for name in _REQUIRED_MANAGED_SECRETS:
            if not self.get(name).value:
                missing.append(name)
        return missing


def _resolve_secret(name: str, gsm: SecretManager) -> SecretValue:
    env_value = os.getenv(name)
    if env_value:
        return SecretValue(name=name, value=env_value, source="env")

    gsm_value = gsm.get_secret(name)
    if gsm_value:
        return SecretValue(name=name, value=gsm_value, source="gsm")

    fallback = get_secret(name, default=None)
    if fallback:
        return SecretValue(name=name, value=fallback, source="default")

    return SecretValue(name=name, value="", source="missing")


def _load_runtime_secrets() -> RuntimeSecrets:
    gsm = SecretManager()
    return RuntimeSecrets(values={name: _resolve_secret(name, gsm) for name in _TRACKED_SECRETS})


_RUNTIME_SECRETS = _load_runtime_secrets()


class ManagedClientError(RuntimeError):
    """Base exception for managed client failures."""

    def __init__(
        self,
        message: str,
        *,
        category: str,
        code: str,
        remediation: str,
        debug_hint: str,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.category = category
        self.code = code
        self.remediation = remediation
        self.debug_hint = debug_hint

    def __str__(self) -> str:
        return (
            f"✖ {self.message}\n"
            f"  category: {self.category}  code: {self.code}\n"
            f"  fix: {self.remediation}\n"
            f"  debug: {self.debug_hint}"
        )


class ConfigError(ManagedClientError):
    pass


class AuthError(ManagedClientError):
    pass


class NetworkError(ManagedClientError):
    pass


class StoreError(ManagedClientError):
    pass


class SystemError(ManagedClientError):
    pass


class ManagedClient:
    """Async API client for managed-mode Matriosha operations."""

    def __init__(
        self,
        *,
        token: str,
        base_url: str | None = None,
        timeout_seconds: float = 10.0,
        managed_mode: bool = True,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not token:
            raise ConfigError(
                "Managed token is missing",
                category="AUTH",
                code="AUTH-001",
                remediation="Run `matriosha auth login` and retry.",
                debug_hint="missing bearer token",
            )

        self._token = token
        self._managed_mode = managed_mode
        self._timeout_seconds = timeout_seconds
        self._max_retries = 3
        self._owns_client = http_client is None
        self._secrets = _RUNTIME_SECRETS

        self._validate_runtime_requirements()

        resolved_base = (base_url or self._secrets.get("SUPABASE_URL").value).rstrip("/")
        self._http = http_client or httpx.AsyncClient(timeout=timeout_seconds, base_url=resolved_base)

    async def __aenter__(self) -> ManagedClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    def _validate_runtime_requirements(self) -> None:
        if not self._managed_mode:
            return

        missing = self._secrets.missing_managed()
        if missing:
            joined = ", ".join(missing)
            raise ConfigError(
                "Managed runtime secrets are incomplete",
                category="SYS",
                code="SYS-001",
                remediation=(
                    "Set required secrets in env or GSM, then rerun managed command. "
                    "Required: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_ANON_KEY, "
                    "STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET."
                ),
                debug_hint=(
                    f"missing={joined}; requires GCP_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS for GSM"
                ),
            )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

        content: str | None = None
        if json_payload is not None:
            headers["Content-Type"] = "application/json"
            content = json.dumps(json_payload, sort_keys=True, ensure_ascii=False)

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._http.request(
                    method,
                    path,
                    headers=headers,
                    content=content,
                    params=params,
                )
            except httpx.TimeoutException as exc:
                raise NetworkError(
                    "Request timed out",
                    category="NET",
                    code="NET-001",
                    remediation="Check connectivity and retry.",
                    debug_hint=f"endpoint={path} timeout={self._timeout_seconds}s",
                ) from exc
            except httpx.HTTPError as exc:
                raise NetworkError(
                    "Could not reach managed backend",
                    category="NET",
                    code="NET-002",
                    remediation="Check network/DNS/VPN and retry.",
                    debug_hint=f"endpoint={path} transport_error={exc.__class__.__name__}",
                ) from exc

            if response.status_code == 401:
                raise AuthError(
                    "Session expired or unauthorized",
                    category="AUTH",
                    code="AUTH-002",
                    remediation="Run `matriosha auth login` to refresh your session.",
                    debug_hint=f"http_status={response.status_code} endpoint={path}",
                )

            if 500 <= response.status_code < 600:
                last_error = NetworkError(
                    "Managed backend is temporarily unavailable",
                    category="NET",
                    code="NET-003",
                    remediation="Retry shortly; if persistent, run `matriosha doctor`.",
                    debug_hint=f"http_status={response.status_code} endpoint={path}",
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                raise last_error

            if response.status_code >= 400:
                raise StoreError(
                    "Managed operation failed",
                    category="STORE",
                    code="STORE-001",
                    remediation="Verify account access and request parameters.",
                    debug_hint=f"http_status={response.status_code} endpoint={path}",
                )

            if response.status_code == 204:
                return {}

            try:
                return response.json()
            except ValueError as exc:
                raise SystemError(
                    "Managed backend returned invalid response",
                    category="SYS",
                    code="SYS-002",
                    remediation="Retry the command. If issue persists, contact support.",
                    debug_hint=f"endpoint={path} expected=json",
                ) from exc

        if last_error:
            raise last_error
        raise SystemError(
            "Unknown managed client failure",
            category="SYS",
            code="SYS-999",
            remediation="Retry command or run `matriosha doctor`.",
            debug_hint=f"endpoint={path}",
        )

    async def whoami(self) -> dict[str, Any]:
        data = await self._request("GET", "/managed/whoami")
        return dict(data)

    async def upload_memory(self, envelope: dict, payload_b64: str, embedding: list[float]) -> str:
        data = await self._request(
            "POST",
            "/managed/memories",
            json_payload={
                "envelope": envelope,
                "payload_b64": payload_b64,
                "embedding": embedding,
            },
        )
        memory_id = data.get("id") or data.get("memory_id")
        if not isinstance(memory_id, str) or not memory_id:
            raise SystemError(
                "Managed backend did not return memory id",
                category="SYS",
                code="SYS-003",
                remediation="Retry upload and verify backend response contract.",
                debug_hint="response missing id",
            )
        return memory_id

    async def fetch_memory(self, memory_id: str) -> tuple[dict[str, Any], str]:
        data = await self._request("GET", f"/managed/memories/{memory_id}")
        envelope = data.get("envelope")
        payload_b64 = data.get("payload_b64")
        if not isinstance(envelope, dict) or not isinstance(payload_b64, str):
            raise SystemError(
                "Managed backend returned malformed memory payload",
                category="SYS",
                code="SYS-004",
                remediation="Retry fetch and verify memory exists.",
                debug_hint=f"memory_id={memory_id}",
            )
        return envelope, payload_b64

    async def list_memories(self, *, tag: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if tag:
            params["tag"] = tag
        data = await self._request("GET", "/managed/memories", params=params)
        if isinstance(data, dict):
            items = data.get("items") or data.get("memories") or []
        else:
            items = data
        return list(items)

    async def delete_memory(self, memory_id: str) -> bool:
        await self._request("DELETE", f"/managed/memories/{memory_id}")
        return True

    async def search(self, embedding: list[float], k: int = 10) -> list[dict[str, Any]]:
        data = await self._request(
            "POST",
            "/managed/search",
            json_payload={"embedding": embedding, "k": k},
        )
        if isinstance(data, dict):
            return list(data.get("items") or data.get("results") or [])
        return list(data)

    async def get_subscription(self) -> dict[str, Any]:
        data = await self._request("GET", "/managed/subscription")
        return dict(data)

    async def start_checkout(self, plan: str = "eur_monthly", quantity: int = 1) -> dict[str, Any]:
        data = await self._request(
            "POST",
            "/managed/billing/checkout",
            json_payload={"plan": plan, "quantity": quantity},
        )
        return dict(data)

    async def cancel_subscription(self) -> dict[str, Any]:
        data = await self._request("POST", "/managed/subscription/cancel")
        return dict(data)

    async def create_agent_token(self, name: str) -> dict[str, Any]:
        data = await self._request(
            "POST",
            "/managed/agent-tokens",
            json_payload={"name": name},
        )
        return dict(data)

    async def revoke_agent_token(self, token_id: str) -> bool:
        await self._request("DELETE", f"/managed/agent-tokens/{token_id}")
        return True

    async def list_agent_tokens(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/managed/agent-tokens")
        if isinstance(data, dict):
            return list(data.get("items") or data.get("tokens") or [])
        return list(data)

    async def upsert_vault_key(self, kdf_salt_b64: str, wrapped_key_b64: str, *, algo: str = "aes-gcm") -> None:
        await self._request(
            "POST",
            "/functions/v1/vault-custody",
            json_payload={
                "action": "upsert",
                "kdf_salt_b64": kdf_salt_b64,
                "wrapped_key_b64": wrapped_key_b64,
                "algo": algo,
            },
        )

    async def fetch_vault_key(self) -> dict[str, Any]:
        data = await self._request(
            "POST",
            "/functions/v1/vault-custody",
            json_payload={"action": "fetch"},
        )
        return dict(data)
