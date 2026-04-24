"""Managed agent connectivity helpers.

These helpers are intentionally lightweight adapters around managed HTTP endpoints
for agent enrollment/list/removal.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from matriosha.core.managed.secrets import get_secret_value, load_runtime_secrets

_REQUIRED_MANAGED_SECRETS = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_ANON_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
)


class AgentServiceError(RuntimeError):
    """Structured error with actionable remediation for agent commands."""

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


class AgentAuthError(AgentServiceError):
    """Authentication-specific agent service error."""


class AgentNetworkError(AgentServiceError):
    """Network-specific agent service error."""


class AgentStoreError(AgentServiceError):
    """Storage/backend-specific agent service error."""


class AgentConfigError(AgentServiceError):
    """Configuration-specific agent service error."""


def _validate_runtime_secrets() -> None:
    secrets = load_runtime_secrets(_REQUIRED_MANAGED_SECRETS, allow_env_fallback=True)
    missing = secrets.missing(_REQUIRED_MANAGED_SECRETS)
    if missing:
        joined = ", ".join(missing)
        raise AgentConfigError(
            "Managed runtime secrets are incomplete",
            category="SYS",
            code="SYS-701",
            remediation=(
                "Set missing secrets in Google Secret Manager (preferred) or environment, then retry. "
                "Managed secret lookup needs GCP_PROJECT_ID and Google credentials permissions."
            ),
            debug_hint=f"missing={joined}",
        )


def _resolve_base_url(remote: Any) -> str:
    base_url = ""

    if hasattr(remote, "_http") and getattr(remote, "_http") is not None:
        raw = getattr(getattr(remote, "_http"), "base_url", None)
        if raw:
            base_url = str(raw)

    if not base_url and hasattr(remote, "base_url"):
        raw = getattr(remote, "base_url")
        if raw:
            base_url = str(raw)

    if not base_url:
        base_url = get_secret_value("SUPABASE_URL", allow_env_fallback=True).value

    base_url = base_url.rstrip("/")
    if not base_url:
        raise AgentConfigError(
            "Managed endpoint is not configured",
            category="SYS",
            code="SYS-702",
            remediation="Configure managed endpoint in profile or set SUPABASE_URL, then retry.",
            debug_hint="empty managed base_url",
        )
    return base_url


async def _request_with_bearer(
    *,
    remote: Any,
    method: str,
    path: str,
    bearer: str,
    json_payload: dict[str, Any] | None = None,
) -> Any:
    _validate_runtime_secrets()

    if not bearer:
        raise AgentAuthError(
            "Bearer token is missing",
            category="AUTH",
            code="AUTH-701",
            remediation="Provide a valid token and retry the command.",
            debug_hint="missing bearer token",
        )

    base_url = _resolve_base_url(remote)
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Accept": "application/json",
    }

    content = None
    if json_payload is not None:
        headers["Content-Type"] = "application/json"
        content = json.dumps(json_payload, sort_keys=True, ensure_ascii=False)

    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=15.0) as client:
            response = await client.request(method, path, headers=headers, content=content)
    except httpx.TimeoutException as exc:
        raise AgentNetworkError(
            "Managed agent request timed out",
            category="NET",
            code="NET-701",
            remediation="Check network connectivity and retry.",
            debug_hint=f"method={method} path={path} timeout=15s",
        ) from exc
    except httpx.HTTPError as exc:
        raise AgentNetworkError(
            "Could not reach managed backend",
            category="NET",
            code="NET-702",
            remediation="Check endpoint/network configuration and retry.",
            debug_hint=f"method={method} path={path} transport_error={exc.__class__.__name__}",
        ) from exc

    if response.status_code in {401, 403}:
        raise AgentAuthError(
            "Invalid or unauthorized agent token",
            category="AUTH",
            code="AUTH-702",
            remediation="Generate a valid token with `matriosha token generate` and retry.",
            debug_hint=f"http_status={response.status_code} path={path}",
        )

    if response.status_code == 404:
        return {"status": "not_found"}

    if response.status_code == 429:
        raise AgentStoreError(
            "Agent operation was rate-limited",
            category="QUOTA",
            code="QUOTA-701",
            remediation="Wait briefly and retry the command.",
            debug_hint=f"http_status=429 path={path}",
        )

    if response.status_code >= 400:
        raise AgentStoreError(
            "Managed agent operation failed",
            category="STORE",
            code="STORE-701",
            remediation="Verify parameters and backend health, then retry.",
            debug_hint=f"http_status={response.status_code} path={path}",
        )

    if response.status_code == 204:
        return {"status": "ok"}

    try:
        return response.json()
    except ValueError as exc:
        raise AgentStoreError(
            "Managed backend returned non-JSON response",
            category="SYS",
            code="SYS-703",
            remediation="Retry command; if persistent, run `matriosha doctor`.",
            debug_hint=f"path={path} expected=json",
        ) from exc


async def connect(remote: Any, token_plaintext: str, name: str, agent_kind: str) -> dict[str, str]:
    """Connect an agent by presenting an agent token to managed backend.

    Uses the provided token as Bearer for POST /agents/connect.
    Returns a normalized dict containing fingerprint and agent_id.
    """

    data = await _request_with_bearer(
        remote=remote,
        method="POST",
        path="/agents/connect",
        bearer=token_plaintext,
        json_payload={"name": name, "agent_kind": agent_kind},
    )

    fingerprint = data.get("fingerprint")
    agent_id = data.get("agent_id") or data.get("id")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise AgentStoreError(
            "Managed response missing agent fingerprint",
            category="SYS",
            code="SYS-704",
            remediation="Retry connect; if issue persists, check backend /agents/connect contract.",
            debug_hint="missing fingerprint",
        )
    if not isinstance(agent_id, str) or not agent_id:
        raise AgentStoreError(
            "Managed response missing agent id",
            category="SYS",
            code="SYS-705",
            remediation="Retry connect; if issue persists, check backend /agents/connect contract.",
            debug_hint="missing agent_id",
        )

    return {"fingerprint": fingerprint, "agent_id": agent_id}


async def list_agents(remote: Any) -> list[dict[str, Any]]:
    """List agents for the currently authenticated managed user."""

    _validate_runtime_secrets()

    if hasattr(remote, "_request"):
        try:
            data = await remote._request("GET", "/agents")
        except Exception as exc:  # noqa: BLE001
            raise AgentStoreError(
                "Failed to list managed agents",
                category="STORE",
                code="STORE-702",
                remediation="Retry `matriosha agent list` after verifying managed session.",
                debug_hint=f"path=/agents error={exc.__class__.__name__}",
            ) from exc
    else:
        raise AgentConfigError(
            "Remote client does not support managed list operation",
            category="SYS",
            code="SYS-706",
            remediation="Use a ManagedClient-compatible remote adapter.",
            debug_hint="remote missing _request",
        )

    if isinstance(data, dict):
        agents = data.get("items") or data.get("agents") or []
    else:
        agents = data

    if not isinstance(agents, list):
        raise AgentStoreError(
            "Managed response for agents list is malformed",
            category="SYS",
            code="SYS-707",
            remediation="Retry command; if persistent, verify backend list contract.",
            debug_hint=f"type={type(agents).__name__}",
        )

    return [dict(item) for item in agents if isinstance(item, dict)]


async def remove_agent(remote: Any, agent_id: str) -> bool:
    """Remove an agent by id. Returns True if deleted, False if already absent."""

    _validate_runtime_secrets()

    if not agent_id:
        raise AgentConfigError(
            "Agent id is required for removal",
            category="VAL",
            code="VAL-701",
            remediation="Provide a valid agent id and retry.",
            debug_hint="empty agent_id",
        )

    if hasattr(remote, "_request"):
        try:
            await remote._request("DELETE", f"/agents/{agent_id}")
            return True
        except Exception as exc:  # noqa: BLE001
            text = str(exc).lower()
            if "http_status=404" in text or "not found" in text:
                return False
            raise AgentStoreError(
                "Failed to remove managed agent",
                category="STORE",
                code="STORE-703",
                remediation="Retry `matriosha agent remove` after validating the agent id.",
                debug_hint=f"path=/agents/{agent_id} error={exc.__class__.__name__}",
            ) from exc

    raise AgentConfigError(
        "Remote client does not support managed remove operation",
        category="SYS",
        code="SYS-708",
        remediation="Use a ManagedClient-compatible remote adapter.",
        debug_hint="remote missing _request",
    )
