"""Managed mode HTTP client for Matriosha."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any

import certifi
import httpx

from matriosha.core.config import DEFAULT_MANAGED_ENDPOINT, get_active_profile, load_config
from matriosha.core.managed.auth import TokenRefreshError, TokenStore, TokenStoreError, is_token_stale, refresh_managed_tokens
from matriosha.core.managed.secrets import load_runtime_secrets


def resolve_managed_endpoint(*candidates: str | None) -> str:
    """Resolve the managed API endpoint with the branded public endpoint as fallback."""

    for candidate in candidates:
        value = str(candidate or "").strip().rstrip("/")
        if value:
            return value
    return DEFAULT_MANAGED_ENDPOINT


_REQUIRED_MANAGED_SECRETS = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_ANON_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
)


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


class ScopeError(AuthError):
    """Raised when token scope is insufficient for the requested managed operation."""

    def __init__(self, scope_required: str, scope_provided: str, *, endpoint: str) -> None:
        required = scope_required or "unknown"
        provided = scope_provided or "unknown"
        self.scope_required = required
        self.scope_provided = provided
        super().__init__(
            "Token scope is insufficient for this managed operation",
            category="AUTH",
            code="AUTH-003",
            remediation=(
                f"Use a token with '{required}' scope (or admin), then retry the command. "
                "Run `matriosha token generate --scope admin` if needed."
            ),
            debug_hint=(
                f"http_status=403 endpoint={endpoint} error_code=insufficient_scope "
                f"scope_required={required} scope_provided={provided}"
            ),
        )


class NetworkError(ManagedClientError):
    pass


class RateLimitError(ManagedClientError):
    pass


class StoreError(ManagedClientError):
    pass


class SystemError(ManagedClientError):
    pass


def _extract_error_details(payload: Any) -> tuple[str | None, str | None, str | None]:
    """Extract backend error code and scope hints from response payload."""

    if not isinstance(payload, dict):
        return None, None, None

    error_value = payload.get("error")
    nested_error: dict[str, Any] = error_value if isinstance(error_value, dict) else {}
    error_code = (
        payload.get("code")
        or payload.get("error_code")
        or nested_error.get("code")
        or nested_error.get("error_code")
    )
    scope_required = (
        payload.get("scope_required")
        or payload.get("required_scope")
        or nested_error.get("scope_required")
        or nested_error.get("required_scope")
    )
    scope_provided = (
        payload.get("scope_provided")
        or payload.get("provided_scope")
        or payload.get("scope")
        or nested_error.get("scope_provided")
        or nested_error.get("provided_scope")
        or nested_error.get("scope")
    )

    code = str(error_code).strip().lower() if error_code is not None else None
    required = str(scope_required).strip().lower() if scope_required is not None else None
    provided = str(scope_provided).strip().lower() if scope_provided is not None else None
    return code, required, provided


def _extract_backend_message(payload: Any) -> str | None:
    """Extract a user-safe backend message from common error response shapes."""

    if isinstance(payload, dict):
        candidates = [
            payload.get("detail"),
            payload.get("message"),
            payload.get("error_description"),
            payload.get("error"),
        ]
        error_value = payload.get("error")
        nested_error: dict[str, Any] = error_value if isinstance(error_value, dict) else {}
        candidates.extend([
            nested_error.get("detail"),
            nested_error.get("message"),
            nested_error.get("error_description"),
            nested_error.get("error"),
        ])
        for candidate in candidates:
            text = str(candidate).strip() if candidate is not None else ""
            if text:
                return text

    if isinstance(payload, str):
        text = payload.strip()
        return text or None

    return None


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
        profile_name: str | None = None,
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
        self._timeout_seconds = timeout_seconds
        self._max_retries = 3
        self._owns_client = http_client is None

        resolved_base = resolve_managed_endpoint(base_url)
        self._managed_mode = managed_mode and not resolved_base
        self._secrets = None
        if self._managed_mode:
            self._secrets = load_runtime_secrets(_REQUIRED_MANAGED_SECRETS, allow_env_fallback=True)

        self._validate_runtime_requirements()
        if not resolved_base:
            raise ConfigError(
                "Managed endpoint is not configured",
                category="SYS",
                code="SYS-002",
                remediation="Use the default managed endpoint or set MATRIOSHA_MANAGED_ENDPOINT/profile.managed_endpoint, then retry.",
                debug_hint="missing managed API base URL",
            )
        self._base_url = resolved_base
        self._env_token_override = bool(os.getenv("MATRIOSHA_MANAGED_TOKEN"))
        # An environment token is an explicit stateless override only when no
        # profile was requested. If callers pass profile_name, keep TokenStore
        # refresh/persistence enabled so user sessions survive token rotation.
        inferred_profile = None if self._env_token_override else self._infer_profile_name(token=token, endpoint=resolved_base)
        self._profile_name = profile_name or inferred_profile
        if self._env_token_override and profile_name is None:
            self._profile_name = None
        self._token_store = TokenStore(self._profile_name) if self._profile_name else None
        self._http = http_client or httpx.AsyncClient(
            timeout=timeout_seconds,
            base_url=resolved_base,
            verify=certifi.where(),
        )

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

        if self._secrets is None:
            raise ConfigError(
                "Managed runtime secrets are unavailable",
                category="SYS",
                code="SYS-001",
                remediation="Configure managed runtime secrets before running managed commands.",
                debug_hint="",
            )
        missing = self._secrets.missing(_REQUIRED_MANAGED_SECRETS)
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

    def _infer_profile_name(self, *, token: str, endpoint: str) -> str | None:
        try:
            cfg = load_config()
            profile = get_active_profile(cfg, None)
        except Exception:  # noqa: BLE001
            return None

        try:
            payload = TokenStore(profile.name).load() or {}
        except TokenStoreError:
            return None

        stored_token = str(payload.get("access_token") or "")
        if stored_token and stored_token == token:
            return profile.name
        return None

    def _normalize_token_payload(self, payload: dict[str, Any], *, refreshed: dict[str, Any]) -> dict[str, Any]:
        existing_refresh = str(payload.get("refresh_token") or "").strip() or None
        next_refresh = str(refreshed.get("refresh_token") or "").strip() or existing_refresh
        normalized = dict(payload)
        normalized["access_token"] = str(refreshed.get("access_token") or "")
        normalized["refresh_token"] = next_refresh
        normalized["expires_at"] = refreshed.get("expires_at")
        if refreshed.get("token_type"):
            normalized["token_type"] = refreshed["token_type"]
        if refreshed.get("scope"):
            normalized["scope"] = refreshed["scope"]
        normalized["endpoint"] = str(payload.get("endpoint") or self._base_url).rstrip("/")
        if self._profile_name:
            normalized["profile"] = str(payload.get("profile") or self._profile_name)
        normalized["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return normalized

    async def _refresh_from_store(self, *, force: bool) -> bool:
        if self._token_store is None:
            return False

        try:
            payload = self._token_store.load() or {}
        except TokenStoreError as exc:
            raise AuthError(
                "Managed session cache is unreadable",
                category="AUTH",
                code="AUTH-005",
                remediation="Run `matriosha auth login` to recreate your managed session.",
                debug_hint=f"token_store={exc}",
            ) from exc

        access_token = str(payload.get("access_token") or "").strip()
        refresh_token = str(payload.get("refresh_token") or "").strip()
        expires_at = str(payload.get("expires_at") or "").strip() or None

        token_is_stale = is_token_stale(expires_at)
        if not force and access_token and not token_is_stale:
            if access_token != self._token:
                self._token = access_token
            return False

        if not refresh_token:
            raise AuthError(
                "Managed session expired and cannot be refreshed",
                category="AUTH",
                code="AUTH-002",
                remediation="Run `matriosha auth login` to refresh your session.",
                debug_hint=f"endpoint={self._base_url} reason=missing_refresh_token",
            )

        endpoint = str(payload.get("endpoint") or self._base_url).rstrip("/")
        try:
            refreshed = await refresh_managed_tokens(
                base_url=endpoint,
                refresh_token=refresh_token,
                timeout_seconds=self._timeout_seconds,
            )
        except TokenRefreshError as exc:
            raise AuthError(
                "Managed session refresh failed",
                category="AUTH",
                code="AUTH-002",
                remediation="Run `matriosha auth login` to refresh your session.",
                debug_hint=f"endpoint={endpoint} reason={exc}",
            ) from exc

        refreshed_payload = self._normalize_token_payload(payload, refreshed=refreshed.as_dict())
        try:
            self._token_store.save(refreshed_payload)
        except TokenStoreError as exc:
            raise AuthError(
                "Managed session refresh could not be persisted",
                category="AUTH",
                code="AUTH-005",
                remediation="Run `matriosha auth login` to recreate your managed session.",
                debug_hint=f"token_store={exc}",
            ) from exc
        self._token = str(refreshed_payload.get("access_token") or "")
        return True

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        if self._token_store is not None:
            await self._refresh_from_store(force=False)

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

        content: str | None = None
        if json_payload is not None:
            headers["Content-Type"] = "application/json"
            content = json.dumps(json_payload, sort_keys=True, ensure_ascii=False)

        auth_retry_attempted = False
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            headers["Authorization"] = f"Bearer {self._token}"
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
                if self._token_store is not None and not auth_retry_attempted:
                    auth_retry_attempted = True
                    await self._refresh_from_store(force=True)
                    continue

                raise AuthError(
                    "Session expired or unauthorized",
                    category="AUTH",
                    code="AUTH-002",
                    remediation="Run `matriosha auth login` to refresh your session.",
                    debug_hint=f"http_status={response.status_code} endpoint={path}",
                )

            response_payload: Any = None
            if response.status_code >= 400:
                try:
                    response_payload = response.json()
                except ValueError:
                    response_payload = None

            if response.status_code == 403:
                error_code, scope_required, scope_provided = _extract_error_details(response_payload)
                if error_code == "insufficient_scope":
                    raise ScopeError(scope_required or "unknown", scope_provided or "unknown", endpoint=path)
                backend_message = _extract_backend_message(response_payload)
                raise AuthError(
                    backend_message or "Managed operation forbidden",
                    category="AUTH",
                    code="AUTH-004",
                    remediation="Confirm token permissions and retry with a valid managed session.",
                    debug_hint=(
                        f"http_status=403 endpoint={path} error_code={error_code or 'unknown'} "
                        f"backend_message={backend_message or 'n/a'}"
                    ),
                )

            if response.status_code == 429:
                raise RateLimitError(
                    "Managed operation is rate-limited",
                    category="QUOTA",
                    code="QUOTA-001",
                    remediation="Wait briefly and retry the command.",
                    debug_hint=f"http_status=429 endpoint={path}",
                )

            if 500 <= response.status_code < 600:
                backend_message = _extract_backend_message(response_payload)
                last_error = NetworkError(
                    backend_message or "Managed backend is temporarily unavailable",
                    category="NET",
                    code="NET-003",
                    remediation="Retry shortly; if persistent, run `matriosha doctor`.",
                    debug_hint=(
                        f"http_status={response.status_code} endpoint={path} "
                        f"backend_message={backend_message or 'n/a'}"
                    ),
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                raise last_error

            if response.status_code >= 400:
                backend_message = _extract_backend_message(response_payload)
                error_message = backend_message or "Managed operation failed"
                raise StoreError(
                    error_message,
                    category="STORE",
                    code="STORE-001",
                    remediation="Verify account access and request parameters.",
                    debug_hint=(
                        f"http_status={response.status_code} endpoint={path} "
                        f"backend_message={backend_message or 'n/a'}"
                    ),
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

    async def upload_memory(
        self,
        envelope: dict,
        payload_b64: str,
        metadata_hashes: list[str] | None = None,
    ) -> str:
        json_payload: dict[str, Any] = {
            "envelope": envelope,
            "payload_b64": payload_b64,
        }
        if metadata_hashes is not None:
            json_payload["metadata_hashes"] = metadata_hashes

        data = await self._request(
            "POST",
            "/managed/memories",
            json_payload=json_payload,
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

    async def upload_memories(self, items: list[dict[str, Any]]) -> list[str]:
        json_items: list[dict[str, Any]] = []
        for item in items:
            json_item: dict[str, Any] = {
                "envelope": item["envelope"],
                "payload_b64": item["payload_b64"],
            }
            if item.get("metadata_hashes") is not None:
                json_item["metadata_hashes"] = item.get("metadata_hashes")
            json_items.append(json_item)

        data = await self._request(
            "POST",
            "/managed/memories/bulk",
            json_payload={"items": json_items},
        )
        response_items = data.get("items")
        if not isinstance(response_items, list) or len(response_items) != len(json_items):
            raise SystemError(
                "Managed backend returned malformed bulk upload response",
                category="SYS",
                code="SYS-003",
                remediation="Retry upload and verify backend response contract.",
                debug_hint="response items missing or length mismatch",
            )

        memory_ids: list[str] = []
        for row in response_items:
            if not isinstance(row, dict):
                raise SystemError(
                    "Managed backend returned malformed bulk upload item",
                    category="SYS",
                    code="SYS-003",
                    remediation="Retry upload and verify backend response contract.",
                    debug_hint="bulk response item is not object",
                )
            memory_id = row.get("id") or row.get("memory_id")
            if not isinstance(memory_id, str) or not memory_id:
                raise SystemError(
                    "Managed backend did not return memory id",
                    category="SYS",
                    code="SYS-003",
                    remediation="Retry upload and verify backend response contract.",
                    debug_hint="bulk response item missing id",
                )
            memory_ids.append(memory_id)
        return memory_ids

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
        enriched_envelope = dict(envelope)
        for key in ("tags", "safe_metadata", "search_keywords", "metadata_hashes"):
            if key in data and key not in enriched_envelope:
                enriched_envelope[key] = data[key]
        return enriched_envelope, payload_b64

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

    async def search_candidates(self, metadata_hashes: list[str], *, limit: int = 50) -> list[dict[str, Any]]:
        cleaned_hashes: list[str] = []
        seen_hashes: set[str] = set()
        for value in metadata_hashes:
            if not isinstance(value, str):
                continue
            cleaned = value.strip()
            if not cleaned or cleaned in seen_hashes:
                continue
            cleaned_hashes.append(cleaned)
            seen_hashes.add(cleaned)

        if not cleaned_hashes:
            raise ValueError("metadata_hashes are required for managed candidate search")

        candidate_limit = max(1, min(int(limit or 50), 50))
        data = await self._request(
            "POST",
            "/managed/search",
            json_payload={
                "metadata_hashes": cleaned_hashes,
                "limit": candidate_limit,
                "candidate_only": True,
            },
        )
        items = data.get("items") or data.get("memories") or []
        return list(items)

    async def delete_memory(self, memory_id: str) -> bool:
        await self._request("DELETE", f"/managed/memories/{memory_id}")
        return True

    async def get_subscription(self) -> dict[str, Any]:
        data = await self._request("GET", "/managed/billing/status")
        return dict(data)

    async def start_checkout(self, plan: str = "eur_monthly", quantity: int = 1) -> dict[str, Any]:
        data = await self._request(
            "POST",
            "/managed/billing/checkout",
            json_payload={"plan": plan, "quantity": quantity},
        )
        return dict(data)

    async def create_billing_portal_session(self, return_url: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if return_url:
            payload["return_url"] = return_url
        data = await self._request("POST", "/managed/billing/portal", json_payload=payload or None)
        return dict(data)

    async def cancel_subscription(self) -> dict[str, Any]:
        data = await self._request("POST", "/managed/billing/cancel")
        return dict(data)

    async def upgrade_subscription(self, quantity: int) -> dict[str, Any]:
        data = await self._request("POST", "/managed/billing/upgrade", json_payload={"quantity": int(quantity)})
        return dict(data)

    async def downgrade_subscription(self, quantity: int) -> dict[str, Any]:
        data = await self._request("POST", "/managed/billing/downgrade", json_payload={"quantity": int(quantity)})
        return dict(data)

    async def create_agent_token(
        self,
        name: str,
        scope: str = "write",
        expires_at: str | None = None,
        managed_passphrase: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": name, "scope": scope}
        if expires_at is not None:
            payload["expires_at"] = expires_at
        if managed_passphrase:
            payload["managed_passphrase"] = managed_passphrase

        data = await self._request(
            "POST",
            "/managed/agent-tokens",
            json_payload=payload,
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

    async def upsert_vault_key(
        self,
        kdf_salt_b64: str,
        wrapped_key_b64: str,
        *,
        algo: str = "aes-gcm",
        managed_custody_data_key_b64: str | None = None,
    ) -> None:
        payload = {
            "action": "upsert",
            "kdf_salt_b64": kdf_salt_b64,
            "wrapped_key_b64": wrapped_key_b64,
            "algo": algo,
        }
        if managed_custody_data_key_b64:
            payload["managed_custody_data_key_b64"] = managed_custody_data_key_b64

        await self._request(
            "POST",
            "/functions/v1/vault-custody",
            json_payload=payload,
        )

    async def fetch_vault_key(self) -> dict[str, Any]:
        data = await self._request(
            "POST",
            "/functions/v1/vault-custody",
            json_payload={"action": "fetch"},
        )
        return dict(data)
