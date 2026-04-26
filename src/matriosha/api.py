from datetime import datetime, timezone
from typing import Any

import base64
import hashlib
import os
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

app = FastAPI()

AGENTS_PER_PACK = 3
BYTES_PER_GB = 1024**3
STORAGE_GB_PER_PACK = 3
VECTOR_DIM = 384
ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}

# Required billing environment variables for managed mode routes:
# - STRIPE_PRICE_ID_BASE: Stripe recurring price id for the base €9/month plan.
# - STRIPE_SUCCESS_URL: Redirect URL after successful Stripe checkout.
# - STRIPE_CANCEL_URL: Redirect URL after canceled Stripe checkout.
# Existing required Stripe env vars:
# - STRIPE_SECRET_KEY
# - STRIPE_WEBHOOK_SECRET


class OtpStartRequest(BaseModel):
    email: str


class OtpVerifyRequest(BaseModel):
    email: str
    code: str


class RefreshRequest(BaseModel):
    refresh_token: str


class VaultCustodyRequest(BaseModel):
    action: str
    kdf_salt_b64: str | None = None
    wrapped_key_b64: str | None = None
    algo: str | None = None


class BillingCheckoutRequest(BaseModel):
    plan: str = "eur_monthly"
    quantity: int = 1


class ManagedMemoryCreateRequest(BaseModel):
    envelope: dict[str, Any]
    payload_b64: str
    embedding: list[float] | None = None


class ManagedSearchRequest(BaseModel):
    query: str | None = None
    embedding: list[float] | None = None
    limit: int | None = Field(default=None, ge=1, le=200)
    k: int | None = Field(default=None, ge=1, le=200)


class ManagedAgentTokenCreateRequest(BaseModel):
    name: str
    scope: str = "write"
    expires_at: str | None = None


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized or "." not in normalized.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=400, detail="valid email is required")
    return normalized


def _bytea_to_bytes(value) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, str):
        if value.startswith("\\x"):
            return bytes.fromhex(value[2:])
        return value.encode("utf-8")
    raise HTTPException(status_code=500, detail="stored key material has unsupported shape")


def _require_env(name: str, *, purpose: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    raise HTTPException(
        status_code=503,
        detail=f"{name} is not configured. {purpose}",
    )


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    expected = os.getenv("ADMIN_DIAGNOSTICS_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="admin diagnostics token not configured")
    if x_admin_token != expected:
        raise HTTPException(status_code=404, detail="not found")


def _supabase_anon_client():
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise HTTPException(status_code=503, detail="supabase auth is not configured")
    return create_client(url, key)


def _supabase_service_client():
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise HTTPException(status_code=503, detail="supabase service role is not configured")
    return create_client(url, key)


def _ensure_public_user(user_id: str) -> None:
    db = _supabase_service_client()
    db.table("users").upsert({"id": user_id}, on_conflict="id").execute()


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="missing authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="invalid authorization header")
    return token.strip()


def _get_authenticated_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = _bearer_token(authorization)
    client = _supabase_anon_client()
    try:
        result = client.auth.get_user(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"invalid session: {exc.__class__.__name__}") from exc

    user = getattr(result, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="invalid session")

    user_id = getattr(user, "id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid session")

    user_id = str(user_id)
    _ensure_public_user(user_id)
    return {
        "user_id": user_id,
        "email": getattr(user, "email", None),
        "aud": getattr(user, "aud", None),
        "role": getattr(user, "role", None),
    }


def _quantity_to_agent_quota(quantity: int | None) -> int:
    try:
        q = int(quantity or 1)
    except Exception:
        q = 1
    if q <= 0:
        q = 1
    return AGENTS_PER_PACK * q


def _quantity_to_storage_cap_bytes(quantity: int | None) -> int:
    try:
        q = int(quantity or 1)
    except Exception:
        q = 1
    if q <= 0:
        q = 1
    return STORAGE_GB_PER_PACK * BYTES_PER_GB * q


def _storage_quota_gb_from_bytes(storage_cap_bytes: int | None) -> float:
    cap = int(storage_cap_bytes or 0)
    if cap <= 0:
        return 0.0
    return round(cap / BYTES_PER_GB, 2)


def _timestamp_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return None


def _get_subscription_row_for_user(user_id: str) -> dict[str, Any] | None:
    db = _supabase_service_client()
    result = db.table("subscriptions").select("*").eq("user_id", user_id).limit(1).execute()
    rows = getattr(result, "data", None) or []
    return rows[0] if rows else None


def _normalize_subscription_status(status: Any) -> str:
    value = str(status or "inactive").strip().lower()
    return value or "inactive"


def _subscription_row_to_entitlement(user_id: str, row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "user_id": user_id,
            "status": "inactive",
            "plan": "eur_monthly",
            "agent_quota": 0,
            "storage_cap_bytes": 0,
            "storage_quota_gb": 0.0,
            "current_period_end": None,
            "stripe_customer_id": None,
            "stripe_subscription_id": None,
            "stripe_subscription_item_id": None,
            "is_active": False,
        }

    storage_cap_bytes = int(row.get("storage_cap_bytes") or 0)
    status = _normalize_subscription_status(row.get("status"))
    return {
        "user_id": user_id,
        "status": status,
        "plan": row.get("plan_code") or "eur_monthly",
        "agent_quota": int(row.get("agent_quota") or 0),
        "storage_cap_bytes": storage_cap_bytes,
        "storage_quota_gb": _storage_quota_gb_from_bytes(storage_cap_bytes),
        "current_period_end": _timestamp_to_iso(row.get("current_period_end")),
        "stripe_customer_id": row.get("stripe_customer_id"),
        "stripe_subscription_id": row.get("stripe_subscription_id"),
        "stripe_subscription_item_id": row.get("stripe_subscription_item_id"),
        "is_active": status in ACTIVE_SUBSCRIPTION_STATUSES,
    }


def get_subscription_entitlement(auth_user: dict[str, Any] = Depends(_get_authenticated_user)) -> dict[str, Any]:
    row = _get_subscription_row_for_user(auth_user["user_id"])
    entitlement = _subscription_row_to_entitlement(auth_user["user_id"], row)
    entitlement["email"] = auth_user.get("email")
    entitlement["aud"] = auth_user.get("aud")
    entitlement["role"] = auth_user.get("role")
    return entitlement


def require_active_subscription(entitlement: dict[str, Any] = Depends(get_subscription_entitlement)) -> dict[str, Any]:
    if entitlement["status"] not in ACTIVE_SUBSCRIPTION_STATUSES:
        raise HTTPException(
            status_code=403,
            detail="Managed mode requires an active subscription. Run 'matriosha billing subscribe' to get started.",
        )
    return entitlement


def _require_active_subscription_for_user(user_id: str) -> None:
    row = _get_subscription_row_for_user(user_id)
    status = _normalize_subscription_status(row.get("status") if row else "inactive")
    if status not in ACTIVE_SUBSCRIPTION_STATUSES:
        raise HTTPException(
            status_code=403,
            detail="Managed mode requires an active subscription. Run 'matriosha billing subscribe' to get started.",
        )


def _get_stripe_module():
    import stripe

    stripe.api_key = _require_env(
        "STRIPE_SECRET_KEY",
        purpose="Set your Stripe secret key to enable billing and webhook processing.",
    )
    return stripe


def _extract_user_id_from_subscription_object(subscription: dict[str, Any]) -> str | None:
    metadata = subscription.get("metadata") if isinstance(subscription, dict) else None
    if isinstance(metadata, dict):
        for key in ("user_id", "userId", "matriosha_user_id"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return None


def _find_user_id_by_stripe_refs(*, stripe_customer_id: str | None, stripe_subscription_id: str | None) -> str | None:
    db = _supabase_service_client()
    if stripe_subscription_id:
        result = (
            db.table("subscriptions")
            .select("user_id")
            .eq("stripe_subscription_id", stripe_subscription_id)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        if rows:
            return str(rows[0].get("user_id"))

    if stripe_customer_id:
        result = (
            db.table("subscriptions")
            .select("user_id")
            .eq("stripe_customer_id", stripe_customer_id)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        if rows:
            return str(rows[0].get("user_id"))

    return None


def _upsert_subscription_snapshot_from_stripe(subscription: dict[str, Any], *, override_status: str | None = None) -> bool:
    if not isinstance(subscription, dict):
        return False

    stripe_subscription_id = subscription.get("id")
    stripe_customer_id = subscription.get("customer")

    user_id = _extract_user_id_from_subscription_object(subscription) or _find_user_id_by_stripe_refs(
        stripe_customer_id=str(stripe_customer_id) if stripe_customer_id else None,
        stripe_subscription_id=str(stripe_subscription_id) if stripe_subscription_id else None,
    )
    if not user_id:
        return False

    items = (((subscription.get("items") or {}).get("data")) or []) if isinstance(subscription.get("items"), dict) else []
    first_item = items[0] if items else {}
    quantity = first_item.get("quantity") if isinstance(first_item, dict) else 1
    price = first_item.get("price") if isinstance(first_item, dict) else {}

    agent_quota = _quantity_to_agent_quota(quantity)
    storage_cap_bytes = _quantity_to_storage_cap_bytes(quantity)

    status = _normalize_subscription_status(override_status or subscription.get("status"))
    current_period_end = _timestamp_to_iso(subscription.get("current_period_end"))

    row = {
        "user_id": user_id,
        "status": status,
        "current_period_end": current_period_end,
        "stripe_customer_id": str(stripe_customer_id) if stripe_customer_id else None,
        "stripe_subscription_id": str(stripe_subscription_id) if stripe_subscription_id else None,
        "stripe_subscription_item_id": (first_item.get("id") if isinstance(first_item, dict) else None),
        "plan_code": "eur_monthly",
        "unit_price_cents": int((price or {}).get("unit_amount") or 900),
        "agent_quota": agent_quota,
        "storage_cap_bytes": storage_cap_bytes,
    }

    _ensure_public_user(user_id)
    db = _supabase_service_client()
    db.table("subscriptions").upsert(row, on_conflict="user_id").execute()
    return True


def _update_subscription_status_by_refs(*, status: str, stripe_customer_id: str | None, stripe_subscription_id: str | None) -> bool:
    user_id = _find_user_id_by_stripe_refs(
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id,
    )
    if not user_id:
        return False

    db = _supabase_service_client()
    db.table("subscriptions").update({"status": _normalize_subscription_status(status)}).eq("user_id", user_id).execute()
    return True


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bytes_to_gb(value: int) -> float:
    return float(value) / float(BYTES_PER_GB)


def _format_storage_used_vs_cap(used_bytes: int, cap_bytes: int) -> str:
    return f"{_bytes_to_gb(used_bytes):.2f}/{_bytes_to_gb(cap_bytes):.2f} GB"


def _normalize_scope(scope: str) -> str:
    normalized = str(scope or "write").strip().lower()
    if normalized not in {"read", "write", "admin"}:
        raise HTTPException(status_code=400, detail="scope must be one of: read, write, admin")
    return normalized


def _extract_tags(envelope: dict[str, Any]) -> list[str]:
    tags = envelope.get("tags")
    if not isinstance(tags, list):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in tags:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _validate_embedding(embedding: list[float] | None) -> list[float] | None:
    if embedding is None:
        return None
    if len(embedding) != VECTOR_DIM:
        raise HTTPException(status_code=400, detail=f"embedding must contain exactly {VECTOR_DIM} float values")

    normalized: list[float] = []
    for value in embedding:
        try:
            normalized.append(float(value))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="embedding must be a numeric float array") from exc
    return normalized


def _decoded_payload_size_bytes(payload_b64: str) -> int:
    if not isinstance(payload_b64, str) or not payload_b64.strip():
        raise HTTPException(status_code=400, detail="payload_b64 is required")
    try:
        decoded = base64.b64decode(payload_b64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="payload_b64 must be valid base64") from exc
    return len(decoded)


def _recompute_storage_usage_bytes(user_id: str) -> int:
    db = _supabase_service_client()
    total = 0
    offset = 0
    page_size = 500

    while True:
        result = (
            db.table("memories")
            .select("payload_b64")
            .eq("user_id", user_id)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        if not rows:
            break

        for row in rows:
            payload_b64 = row.get("payload_b64") or ""
            try:
                total += len(base64.b64decode(payload_b64, validate=True))
            except Exception:
                # Corrupt rows should not crash quota calculations.
                continue

        if len(rows) < page_size:
            break
        offset += page_size

    return total


def _sync_quota_usage_for_user(user_id: str, *, storage_used_bytes: int | None = None) -> int:
    used = _safe_int(storage_used_bytes, default=-1)
    if used < 0:
        used = _recompute_storage_usage_bytes(user_id)

    db = _supabase_service_client()
    quota_row = {
        "user_id": user_id,
        "storage_used_bytes": used,
        "raw_storage_bytes": used,
        "compressed_storage_bytes": 0,
        "index_storage_bytes": 0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    db.table("quota_usage").upsert(quota_row, on_conflict="user_id").execute()
    db.table("subscriptions").update({"storage_used_bytes": used, "updated_at": datetime.now(timezone.utc).isoformat()}).eq(
        "user_id", user_id
    ).execute()
    return used


def _count_active_agent_tokens(user_id: str) -> int:
    db = _supabase_service_client()
    try:
        result = (
            db.table("agent_tokens")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .is_("revoked_at", "null")
            .execute()
        )
    except Exception:
        result = db.table("agent_tokens").select("id", count="exact").eq("user_id", user_id).execute()
    return _safe_int(getattr(result, "count", None), 0)


def _count_connected_agents(user_id: str) -> int:
    db = _supabase_service_client()
    try:
        result = db.table("agents").select("id", count="exact").eq("user_id", user_id).execute()
    except Exception:
        return 0
    return _safe_int(getattr(result, "count", None), 0)


def _resolve_agent_in_use(user_id: str) -> int:
    token_count = _count_active_agent_tokens(user_id)
    connected_agents = _count_connected_agents(user_id)
    # Defensive posture against abuse: enforce whichever count is higher.
    return max(token_count, connected_agents)


def _build_quota_status(entitlement: dict[str, Any]) -> dict[str, Any]:
    user_id = entitlement["user_id"]
    storage_cap_bytes = _safe_int(entitlement.get("storage_cap_bytes"), 0)
    if storage_cap_bytes <= 0:
        storage_cap_bytes = int(float(entitlement.get("storage_quota_gb") or 0) * BYTES_PER_GB)
    storage_used_bytes = _sync_quota_usage_for_user(user_id)
    pct = (float(storage_used_bytes) / float(storage_cap_bytes) * 100.0) if storage_cap_bytes > 0 else 0.0

    agent_quota = _safe_int(entitlement.get("agent_quota"), 0)
    agent_in_use = _resolve_agent_in_use(user_id)

    warnings: list[str] = []
    if storage_cap_bytes > 0 and pct >= 80.0:
        warnings.append(
            "Storage usage is above 80%. Run 'matriosha memory compress' or upgrade with 'matriosha billing upgrade'."
        )

    return {
        "status": "ok",
        "operation": "quota.status",
        "storage_used_bytes": storage_used_bytes,
        "storage_cap_bytes": storage_cap_bytes,
        "storage_used_percent": round(pct, 2),
        "agent_quota": agent_quota,
        "agent_in_use": agent_in_use,
        "agent_available": max(0, agent_quota - agent_in_use),
        "warnings": warnings,
    }


def _enforce_storage_quota_before_upload(entitlement: dict[str, Any], *, payload_size_bytes: int) -> dict[str, Any]:
    snapshot = _build_quota_status(entitlement)
    storage_cap_bytes = snapshot["storage_cap_bytes"]
    storage_used_bytes = snapshot["storage_used_bytes"]

    if storage_cap_bytes <= 0:
        raise HTTPException(
            status_code=413,
            detail="Storage quota exceeded (0.00/0.00 GB used). Upgrade your plan with 'matriosha billing upgrade'",
        )

    projected_used = storage_used_bytes + max(payload_size_bytes, 0)
    if projected_used > storage_cap_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Storage quota exceeded ({_format_storage_used_vs_cap(storage_used_bytes, storage_cap_bytes)} used). "
                "Upgrade your plan with 'matriosha billing upgrade'"
            ),
        )

    return snapshot


def _enforce_agent_quota(entitlement: dict[str, Any]) -> dict[str, Any]:
    snapshot = _build_quota_status(entitlement)
    if snapshot["agent_quota"] > 0 and snapshot["agent_in_use"] >= snapshot["agent_quota"]:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Agent limit reached ({snapshot['agent_in_use']}/{snapshot['agent_quota']} agents). "
                "Upgrade for more agents."
            ),
        )
    return snapshot


def _memory_not_found_error() -> HTTPException:
    return HTTPException(status_code=404, detail="Memory not found or access denied")


def _vector_from_db(value: Any) -> list[float] | None:
    if isinstance(value, list):
        try:
            return [float(x) for x in value]
        except (TypeError, ValueError):
            return None

    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            body = text[1:-1].strip()
            if not body:
                return []
            parts = [p.strip() for p in body.split(",")]
            try:
                return [float(p) for p in parts]
            except (TypeError, ValueError):
                return None
    return None


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0

    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for lval, rval in zip(left, right):
        dot += lval * rval
        left_norm += lval * lval
        right_norm += rval * rval

    if left_norm <= 0.0 or right_norm <= 0.0:
        return -1.0
    return dot / ((left_norm ** 0.5) * (right_norm ** 0.5))


@app.post("/managed/auth/otp/start")
def managed_auth_otp_start(req: OtpStartRequest):
    client = _supabase_anon_client()
    try:
        result = client.auth.sign_in_with_otp(
            {
                "email": _normalize_email(req.email),
                "options": {
                    "should_create_user": True,
                },
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"could not send login code: {exc.__class__.__name__}") from exc

    return {
        "status": "ok",
        "message": "login code sent",
        "message_id": getattr(result, "message_id", None),
    }


@app.post("/managed/auth/otp/verify")
def managed_auth_otp_verify(req: OtpVerifyRequest):
    code = req.code.strip().replace(" ", "")
    if not code:
        raise HTTPException(status_code=400, detail="code is required")

    client = _supabase_anon_client()
    try:
        result = client.auth.verify_otp(
            {
                "email": _normalize_email(req.email),
                "token": code,
                "type": "email",
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"invalid or expired login code: {exc.__class__.__name__}") from exc

    session = getattr(result, "session", None)
    user = getattr(result, "user", None)
    access_token = getattr(session, "access_token", None) if session else None
    refresh_token = getattr(session, "refresh_token", None) if session else None
    expires_in = getattr(session, "expires_in", None) if session else None
    token_type = getattr(session, "token_type", None) if session else "bearer"

    if not access_token:
        raise HTTPException(status_code=401, detail="login verification did not return a session")

    user_id = getattr(user, "id", None) if user else None
    if user_id:
        _ensure_public_user(str(user_id))
        _require_active_subscription_for_user(str(user_id))

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
        "token_type": token_type or "bearer",
        "scope": "openid profile email offline_access",
        "user": {
            "id": getattr(user, "id", None) if user else None,
            "email": getattr(user, "email", None) if user else _normalize_email(req.email),
        },
    }


@app.post("/managed/auth/refresh")
def managed_auth_refresh(req: RefreshRequest):
    refresh_token = req.refresh_token.strip()
    if not refresh_token:
        raise HTTPException(status_code=400, detail="refresh_token is required")

    client = _supabase_anon_client()
    try:
        result = client.auth.refresh_session(refresh_token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"invalid or expired refresh token: {exc.__class__.__name__}") from exc

    session = getattr(result, "session", None)
    user = getattr(result, "user", None)
    access_token = getattr(session, "access_token", None) if session else None
    rotated_refresh = getattr(session, "refresh_token", None) if session else None
    expires_in = getattr(session, "expires_in", None) if session else None
    token_type = getattr(session, "token_type", None) if session else "bearer"

    if not access_token:
        raise HTTPException(status_code=401, detail="token refresh did not return an access token")

    return {
        "access_token": access_token,
        "refresh_token": rotated_refresh or refresh_token,
        "expires_in": expires_in,
        "token_type": token_type or "bearer",
        "scope": "openid profile email offline_access",
        "user": {
            "id": getattr(user, "id", None) if user else None,
            "email": getattr(user, "email", None) if user else None,
        },
    }


@app.get("/managed/whoami")
def managed_whoami(entitlement: dict[str, Any] = Depends(require_active_subscription)):
    return {
        "user_id": entitlement["user_id"],
        "id": entitlement["user_id"],
        "email": entitlement.get("email"),
        "aud": entitlement.get("aud"),
        "role": entitlement.get("role"),
        "subscription_status": entitlement["status"],
        "agent_quota": entitlement["agent_quota"],
        "storage_quota_gb": entitlement["storage_quota_gb"],
    }


@app.post("/functions/v1/vault-custody")
def vault_custody(req: VaultCustodyRequest, entitlement: dict[str, Any] = Depends(require_active_subscription)):
    user_id = entitlement["user_id"]
    db = _supabase_service_client()

    if req.action == "fetch":
        result = (
            db.table("vault_keys")
            .select("kdf_salt,wrapped_key,algo")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = getattr(result, "data", None) or []
        if not rows:
            raise HTTPException(status_code=404, detail="managed vault key not found")

        row = rows[0]
        return {
            "kdf_salt_b64": base64.b64encode(_bytea_to_bytes(row["kdf_salt"])).decode("ascii"),
            "wrapped_key_b64": base64.b64encode(_bytea_to_bytes(row["wrapped_key"])).decode("ascii"),
            "algo": row.get("algo") or "aes-gcm",
        }

    if req.action == "upsert":
        if not req.kdf_salt_b64 or not req.wrapped_key_b64:
            raise HTTPException(status_code=400, detail="kdf_salt_b64 and wrapped_key_b64 are required")
        try:
            kdf_salt = base64.b64decode(req.kdf_salt_b64, validate=True)
            wrapped_key = base64.b64decode(req.wrapped_key_b64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid base64 key material") from exc

        row = {
            "user_id": user_id,
            "kdf_salt": "\\x" + kdf_salt.hex(),
            "wrapped_key": "\\x" + wrapped_key.hex(),
            "algo": req.algo or "aes-gcm",
        }
        db.table("vault_keys").upsert(row, on_conflict="user_id").execute()
        return {"status": "ok"}

    raise HTTPException(status_code=400, detail="unsupported vault custody action")


@app.post("/managed/billing/checkout")
def managed_billing_checkout(req: BillingCheckoutRequest, entitlement: dict[str, Any] = Depends(get_subscription_entitlement)):
    if req.plan != "eur_monthly":
        raise HTTPException(status_code=400, detail="Only the eur_monthly plan is currently supported.")
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be a positive integer")

    stripe = _get_stripe_module()
    price_id = _require_env(
        "STRIPE_PRICE_ID_BASE",
        purpose="Set the Stripe base price ID in Cloud Run to enable checkout.",
    )
    success_url = _require_env(
        "STRIPE_SUCCESS_URL",
        purpose="Set STRIPE_SUCCESS_URL (e.g. https://matriosha.in/billing/success).",
    )
    cancel_url = _require_env(
        "STRIPE_CANCEL_URL",
        purpose="Set STRIPE_CANCEL_URL (e.g. https://matriosha.in/billing/cancel).",
    )

    checkout_payload: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": req.quantity}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "allow_promotion_codes": True,
        "client_reference_id": entitlement["user_id"],
        "metadata": {
            "user_id": entitlement["user_id"],
            "plan": req.plan,
        },
        "subscription_data": {
            "metadata": {
                "user_id": entitlement["user_id"],
                "plan": req.plan,
            }
        },
    }

    if entitlement.get("stripe_customer_id"):
        checkout_payload["customer"] = entitlement["stripe_customer_id"]
    elif entitlement.get("email"):
        checkout_payload["customer_email"] = entitlement["email"]

    try:
        session = stripe.checkout.Session.create(**checkout_payload)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not create Stripe checkout session ({exc.__class__.__name__}).") from exc

    return {
        "status": "pending",
        "checkout_url": getattr(session, "url", None),
        "session_id": getattr(session, "id", None),
    }


@app.get("/managed/billing/status")
def managed_billing_status(entitlement: dict[str, Any] = Depends(get_subscription_entitlement)):
    quota = _build_quota_status(entitlement)
    return {
        "status": entitlement["status"],
        "plan": entitlement["plan"],
        "plan_code": entitlement["plan"],
        "agent_quota": entitlement["agent_quota"],
        "agent_in_use": quota["agent_in_use"],
        "storage_cap_bytes": entitlement["storage_cap_bytes"],
        "storage_used_bytes": quota["storage_used_bytes"],
        "storage_used_percent": quota["storage_used_percent"],
        "storage_quota_gb": entitlement["storage_quota_gb"],
        "current_period_end": entitlement["current_period_end"],
        "stripe_customer_id": entitlement.get("stripe_customer_id"),
        "stripe_subscription_id": entitlement.get("stripe_subscription_id"),
        "stripe_subscription_item_id": entitlement.get("stripe_subscription_item_id"),
        "warnings": quota["warnings"],
    }


@app.post("/managed/billing/portal")
def managed_billing_portal(entitlement: dict[str, Any] = Depends(get_subscription_entitlement)):
    if not entitlement.get("stripe_customer_id"):
        raise HTTPException(
            status_code=400,
            detail="No billing customer found yet. Run 'matriosha billing subscribe' first.",
        )

    stripe = _get_stripe_module()
    return_url = _require_env(
        "STRIPE_SUCCESS_URL",
        purpose="Set STRIPE_SUCCESS_URL so users can return from the billing portal.",
    )

    try:
        portal = stripe.billing_portal.Session.create(
            customer=entitlement["stripe_customer_id"],
            return_url=return_url,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not create billing portal session ({exc.__class__.__name__}).") from exc

    return {
        "portal_url": getattr(portal, "url", None),
    }


@app.get("/managed/subscription")
def managed_subscription_status(entitlement: dict[str, Any] = Depends(get_subscription_entitlement)):
    return managed_billing_status(entitlement)


@app.get("/managed/quota/status")
def managed_quota_status(entitlement: dict[str, Any] = Depends(require_active_subscription)):
    return _build_quota_status(entitlement)


@app.post("/managed/memories")
def managed_memories_create(
    req: ManagedMemoryCreateRequest,
    entitlement: dict[str, Any] = Depends(require_active_subscription),
):
    user_id = entitlement["user_id"]
    payload_size_bytes = _decoded_payload_size_bytes(req.payload_b64)
    _enforce_storage_quota_before_upload(entitlement, payload_size_bytes=payload_size_bytes)

    envelope = dict(req.envelope or {})
    embedding = _validate_embedding(req.embedding)
    tags = _extract_tags(envelope)

    db = _supabase_service_client()
    memory_row = {
        "user_id": user_id,
        "envelope": envelope,
        "payload_b64": req.payload_b64,
        "tags": tags,
    }

    insert_result = db.table("memories").insert(memory_row).execute()
    inserted_rows = getattr(insert_result, "data", None) or []
    if not inserted_rows:
        raise HTTPException(status_code=500, detail="Could not store memory. Please retry.")

    memory_id = str(inserted_rows[0].get("id") or "").strip()
    if not memory_id:
        raise HTTPException(status_code=500, detail="Managed backend did not return memory id")

    if embedding is not None:
        try:
            db.table("memory_vectors").upsert({"memory_id": memory_id, "embedding": embedding}, on_conflict="memory_id").execute()
        except Exception as exc:
            db.table("memories").delete().eq("id", memory_id).eq("user_id", user_id).execute()
            raise HTTPException(status_code=500, detail="Could not index memory embedding. Please retry.") from exc

    _sync_quota_usage_for_user(user_id)
    return {"id": memory_id, "memory_id": memory_id}


@app.get("/managed/memories")
def managed_memories_list(
    tag: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    entitlement: dict[str, Any] = Depends(require_active_subscription),
):
    user_id = entitlement["user_id"]
    db = _supabase_service_client()
    result = (
        db.table("memories")
        .select("id,envelope,payload_b64,created_at,tags")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = getattr(result, "data", None) or []

    filtered: list[dict[str, Any]] = []
    wanted_tag = tag.strip() if isinstance(tag, str) else None
    for row in rows:
        if wanted_tag:
            row_tags = row.get("tags") if isinstance(row.get("tags"), list) else _extract_tags(row.get("envelope") or {})
            if wanted_tag not in row_tags:
                continue

        filtered.append(
            {
                "id": row.get("id"),
                "memory_id": row.get("id"),
                "envelope": row.get("envelope") or {},
                "payload_b64": row.get("payload_b64") or "",
                "created_at": row.get("created_at"),
            }
        )

    return {"items": filtered, "memories": filtered}


@app.get("/managed/memories/{memory_id}")
def managed_memories_fetch(memory_id: str, entitlement: dict[str, Any] = Depends(require_active_subscription)):
    user_id = entitlement["user_id"]
    db = _supabase_service_client()
    result = db.table("memories").select("id,envelope,payload_b64").eq("id", memory_id).eq("user_id", user_id).limit(1).execute()
    rows = getattr(result, "data", None) or []
    if not rows:
        raise _memory_not_found_error()

    row = rows[0]
    return {
        "id": row.get("id"),
        "memory_id": row.get("id"),
        "envelope": row.get("envelope") or {},
        "payload_b64": row.get("payload_b64") or "",
    }


@app.delete("/managed/memories/{memory_id}")
def managed_memories_delete(memory_id: str, entitlement: dict[str, Any] = Depends(require_active_subscription)):
    user_id = entitlement["user_id"]
    db = _supabase_service_client()

    lookup = db.table("memories").select("id").eq("id", memory_id).eq("user_id", user_id).limit(1).execute()
    rows = getattr(lookup, "data", None) or []
    if not rows:
        raise _memory_not_found_error()

    db.table("memory_vectors").delete().eq("memory_id", memory_id).execute()
    db.table("memories").delete().eq("id", memory_id).eq("user_id", user_id).execute()
    _sync_quota_usage_for_user(user_id)
    return {"deleted": True, "ok": True}


@app.post("/managed/search")
def managed_search(req: ManagedSearchRequest, entitlement: dict[str, Any] = Depends(require_active_subscription)):
    user_id = entitlement["user_id"]
    limit = req.limit or req.k or 10
    limit = min(max(int(limit), 1), 200)

    if req.embedding is None and (req.query is None or not req.query.strip()):
        raise HTTPException(status_code=400, detail="Provide either 'embedding' or 'query' for search")

    db = _supabase_service_client()
    memories_result = (
        db.table("memories")
        .select("id,envelope,payload_b64,created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(2000)
        .execute()
    )
    memory_rows = getattr(memories_result, "data", None) or []
    if not memory_rows:
        return {"items": [], "results": []}

    if req.embedding is not None:
        embedding = _validate_embedding(req.embedding)
        assert embedding is not None

        id_to_memory = {str(row.get("id")): row for row in memory_rows if row.get("id")}
        memory_ids = list(id_to_memory.keys())
        vectors_result = db.table("memory_vectors").select("memory_id,embedding").in_("memory_id", memory_ids).execute()
        vector_rows = getattr(vectors_result, "data", None) or []

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in vector_rows:
            memory_id = str(row.get("memory_id") or "")
            if not memory_id or memory_id not in id_to_memory:
                continue
            candidate_vec = _vector_from_db(row.get("embedding"))
            if candidate_vec is None:
                continue
            score = _cosine_similarity(embedding, candidate_vec)
            if score < -0.5:
                continue
            memory = id_to_memory[memory_id]
            scored.append(
                (
                    score,
                    {
                        "id": memory_id,
                        "memory_id": memory_id,
                        "score": round(float(score), 6),
                        "envelope": memory.get("envelope") or {},
                        "payload_b64": memory.get("payload_b64") or "",
                        "created_at": memory.get("created_at"),
                    },
                )
            )

        scored.sort(key=lambda pair: pair[0], reverse=True)
        items = [item for _, item in scored[:limit]]
        return {"items": items, "results": items}

    query = req.query.strip().lower()
    lexical_matches: list[dict[str, Any]] = []
    for row in memory_rows:
        envelope = row.get("envelope") if isinstance(row.get("envelope"), dict) else {}
        haystack = str(envelope).lower()
        if query in haystack:
            memory_id = str(row.get("id") or "")
            lexical_matches.append(
                {
                    "id": memory_id,
                    "memory_id": memory_id,
                    "envelope": envelope,
                    "payload_b64": row.get("payload_b64") or "",
                    "created_at": row.get("created_at"),
                }
            )
        if len(lexical_matches) >= limit:
            break

    return {"items": lexical_matches, "results": lexical_matches}


@app.post("/managed/agent-tokens")
def managed_agent_tokens_create(
    req: ManagedAgentTokenCreateRequest,
    entitlement: dict[str, Any] = Depends(require_active_subscription),
):
    user_id = entitlement["user_id"]
    _enforce_agent_quota(entitlement)

    name = str(req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    scope = _normalize_scope(req.scope)
    plaintext_token = f"mt_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(plaintext_token.encode("utf-8")).hexdigest()

    db = _supabase_service_client()
    base_row = {
        "user_id": user_id,
        "token_hash": token_hash,
        "name": name,
    }
    full_row = base_row | {
        "scope": scope,
        "expires_at": req.expires_at,
    }

    insert_result = None
    try:
        insert_result = db.table("agent_tokens").insert(full_row).execute()
    except Exception as exc:
        if "column" in str(exc).lower() and ("scope" in str(exc).lower() or "expires_at" in str(exc).lower()):
            insert_result = db.table("agent_tokens").insert(base_row).execute()
        else:
            raise

    rows = getattr(insert_result, "data", None) or []
    token_id = str(rows[0].get("id") if rows else "").strip()
    if not token_id:
        lookup = (
            db.table("agent_tokens")
            .select("id")
            .eq("user_id", user_id)
            .eq("token_hash", token_hash)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        lookup_rows = getattr(lookup, "data", None) or []
        if lookup_rows:
            token_id = str(lookup_rows[0].get("id") or "")

    if not token_id:
        raise HTTPException(status_code=500, detail="Could not create agent token. Please retry.")

    return {
        "id": token_id,
        "token_id": token_id,
        "name": name,
        "scope": scope,
        "expires_at": req.expires_at,
        "token": plaintext_token,
        "token_plaintext": plaintext_token,
    }


@app.get("/managed/agent-tokens")
def managed_agent_tokens_list(entitlement: dict[str, Any] = Depends(require_active_subscription)):
    user_id = entitlement["user_id"]
    db = _supabase_service_client()
    result = db.table("agent_tokens").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    rows = getattr(result, "data", None) or []

    items: list[dict[str, Any]] = []
    for row in rows:
        revoked = bool(row.get("revoked") or row.get("revoked_at"))
        items.append(
            {
                "id": row.get("id"),
                "name": row.get("name") or "token",
                "scope": row.get("scope") or "write",
                "created_at": row.get("created_at"),
                "last_used": row.get("last_used"),
                "expires_at": row.get("expires_at"),
                "revoked": revoked,
            }
        )

    return {"items": items, "tokens": items}


@app.delete("/managed/agent-tokens/{token_id}")
def managed_agent_tokens_delete(token_id: str, entitlement: dict[str, Any] = Depends(require_active_subscription)):
    user_id = entitlement["user_id"]
    db = _supabase_service_client()
    lookup = db.table("agent_tokens").select("id").eq("id", token_id).eq("user_id", user_id).limit(1).execute()
    rows = getattr(lookup, "data", None) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Agent token not found or access denied")

    db.table("agent_tokens").delete().eq("id", token_id).eq("user_id", user_id).execute()
    return {"deleted": True, "ok": True}


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: str | None = Header(default=None, alias="Stripe-Signature")):
    import json

    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        raise HTTPException(
            status_code=503,
            detail="STRIPE_WEBHOOK_SECRET is not configured. Add it to process Stripe webhooks.",
        )

    payload = await request.body()

    try:
        import stripe

        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=webhook_secret,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook payload.") from exc
    except Exception as exc:
        if exc.__class__.__name__ == "SignatureVerificationError":
            raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature.") from exc
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature.") from exc

    event_id = str(event.get("id") or "").strip()
    event_type = str(event.get("type") or "").strip()
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Stripe event is missing required identifiers.")

    db = _supabase_service_client()
    event_record = {
        "event_id": event_id,
        "event_type": event_type,
        "stripe_data": {
            "object_id": ((event.get("data") or {}).get("object") or {}).get("id"),
            "object": ((event.get("data") or {}).get("object") or {}).get("object"),
        },
    }

    try:
        db.table("stripe_webhook_events").insert(event_record).execute()
    except Exception as exc:
        lower = str(exc).lower()
        if "duplicate" in lower or "unique" in lower or "uq_stripe_webhook_events_event_id" in lower:
            return {"status": "ok", "processed": False, "idempotent": True}
        raise HTTPException(status_code=500, detail="Could not persist webhook event.") from exc

    handled_events = {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.payment_succeeded",
        "invoice.payment_failed",
    }

    if event_type not in handled_events:
        return {"status": "ok", "processed": True, "handled": False}

    stripe_object = ((event.get("data") or {}).get("object")) or {}
    processed = False

    if event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        processed = _upsert_subscription_snapshot_from_stripe(stripe_object)

    elif event_type == "customer.subscription.deleted":
        processed = _upsert_subscription_snapshot_from_stripe(stripe_object, override_status="canceled")
        if not processed:
            processed = _update_subscription_status_by_refs(
                status="canceled",
                stripe_customer_id=str(stripe_object.get("customer") or "") or None,
                stripe_subscription_id=str(stripe_object.get("id") or "") or None,
            )

    elif event_type in {"invoice.payment_succeeded", "invoice.payment_failed"}:
        stripe = _get_stripe_module()
        stripe_subscription_id = str(stripe_object.get("subscription") or "").strip() or None
        stripe_customer_id = str(stripe_object.get("customer") or "").strip() or None

        if stripe_subscription_id:
            try:
                subscription = stripe.Subscription.retrieve(stripe_subscription_id)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Could not fetch Stripe subscription ({exc.__class__.__name__}).") from exc

            override_status = "past_due" if event_type == "invoice.payment_failed" else None
            processed = _upsert_subscription_snapshot_from_stripe(dict(subscription), override_status=override_status)

        if not processed:
            fallback_status = "past_due" if event_type == "invoice.payment_failed" else "active"
            processed = _update_subscription_status_by_refs(
                status=fallback_status,
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=stripe_subscription_id,
            )

    try:
        db.table("stripe_webhook_events").update({"stripe_data": event_record["stripe_data"] | {"processed": bool(processed)}}).eq(
            "event_id", event_id
        ).execute()
    except Exception:
        # Non-blocking metadata update; original event is already journaled.
        pass

    return {"status": "ok", "processed": True, "updated_subscription": bool(processed)}


@app.get("/")
def read_root():
    return {"status": "Matriosha API is running"}


@app.get("/health/secrets")
def health_secrets(_: None = Depends(require_admin_token)):
    names = [
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_JWT_SECRET",
        "SUPABASE_PASSWORD",
        "STRIPE_PUBLISHABLE_KEY",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PRICE_ID_BASE",
        "STRIPE_SUCCESS_URL",
        "STRIPE_CANCEL_URL",
        "GCP_PROJECT_ID",
        "ADMIN_DIAGNOSTICS_TOKEN",
    ]

    return {
        "status": "ok",
        "env": {
            name: {
                "present": bool(os.getenv(name)),
                "length": len(os.getenv(name, "")),
            }
            for name in names
        },
    }


@app.get("/health/deps")
def health_deps(_: None = Depends(require_admin_token)):
    deps = {}
    for name in ["supabase", "stripe", "httpx"]:
        try:
            __import__(name)
            deps[name] = {"available": True}
        except Exception as exc:
            deps[name] = {
                "available": False,
                "error": exc.__class__.__name__,
            }

    return {"status": "ok", "deps": deps}


@app.get("/health/supabase")
def health_supabase(_: None = Depends(require_admin_token)):
    try:
        from supabase import create_client

        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY")

        if not url or not key:
            return {"status": "error", "provider": "supabase", "error": "missing_env"}

        client = create_client(url, key)
        result = client.auth.admin.list_users(page=1, per_page=1)

        return {
            "status": "ok",
            "provider": "supabase",
            "result_type": type(result).__name__,
        }

    except Exception as exc:
        return {
            "status": "error",
            "provider": "supabase",
            "error": exc.__class__.__name__,
            "message": str(exc)[:300],
        }


@app.get("/health/stripe")
def health_stripe(_: None = Depends(require_admin_token)):
    try:
        import httpx

        key = os.getenv("STRIPE_SECRET_KEY")
        if not key:
            return {"status": "error", "provider": "stripe", "error": "missing_env"}

        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                "https://api.stripe.com/v1/account",
                headers={"Authorization": f"Bearer {key}"},
            )

        if response.status_code >= 400:
            try:
                data = response.json()
            except Exception:
                data = {}
            err = data.get("error", {}) if isinstance(data, dict) else {}
            return {
                "status": "error",
                "provider": "stripe",
                "http_status": response.status_code,
                "stripe_error_type": err.get("type"),
                "stripe_error_code": err.get("code"),
                "message": str(err.get("message") or response.text)[:300],
            }

        data = response.json()
        return {
            "status": "ok",
            "provider": "stripe",
            "account_id": data.get("id"),
            "livemode": data.get("livemode"),
            "charges_enabled": data.get("charges_enabled"),
            "payouts_enabled": data.get("payouts_enabled"),
        }

    except Exception as exc:
        return {
            "status": "error",
            "provider": "stripe",
            "error": exc.__class__.__name__,
            "message": str(exc)[:300],
        }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
