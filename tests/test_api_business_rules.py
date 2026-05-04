from __future__ import annotations

import asyncio
import base64
import hashlib
import sys
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from fastapi import HTTPException

import matriosha.api as api


GB = 1024 * 1024 * 1024



def _as_dict(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value)


@pytest.mark.parametrize(
    ("quantity", "expected"),
    [
        (None, 3),
        (0, 3),
        (-1, 3),
        (1, 3),
        (2, 6),
        (10, 30),
        (100, 300),
    ],
)
def test_quantity_to_agent_quota_maps_paid_quantity_to_three_agents_each(quantity: int | None, expected: int) -> None:
    assert api._quantity_to_agent_quota(quantity) == expected


@pytest.mark.parametrize(
    ("quantity", "expected_gb"),
    [
        (None, 3),
        (0, 3),
        (-1, 3),
        (1, 3),
        (3, 9),
        (100, 300),
    ],
)
def test_quantity_to_storage_cap_bytes_maps_paid_quantity_to_three_gb_each(quantity: int | None, expected_gb: int) -> None:
    assert api._quantity_to_storage_cap_bytes(quantity) == expected_gb * GB


@pytest.mark.parametrize("invalid_quantity", ["", "abc", object()])
def test_invalid_quantity_defaults_to_one_paid_pack(invalid_quantity: object) -> None:
    assert api._quantity_to_agent_quota(invalid_quantity) == 3  # type: ignore[arg-type]
    assert api._quantity_to_storage_cap_bytes(invalid_quantity) == 3 * GB  # type: ignore[arg-type]


def test_storage_quota_gb_from_bytes() -> None:
    assert api._storage_quota_gb_from_bytes(2 * GB) == 2.0
    assert api._storage_quota_gb_from_bytes(None) == 0.0


def test_subscription_access_active_statuses() -> None:
    assert api._is_subscription_access_active("active", None) is True
    assert api._is_subscription_access_active("trialing", None) is True
    assert api._is_subscription_access_active("past_due", None) is False
    assert api._is_subscription_access_active("canceled", None) is False


def test_subscription_access_remains_active_until_cancel_at() -> None:
    future_cancel = datetime.now(UTC) + timedelta(days=2)
    past_cancel = datetime.now(UTC) - timedelta(days=2)

    assert api._is_subscription_access_active("canceled", future_cancel.isoformat()) is True
    assert api._is_subscription_access_active("canceled", past_cancel.isoformat()) is False


def test_billing_checkout_rejects_existing_active_stripe_subscription() -> None:
    req = api.BillingCheckoutRequest(plan="eur_monthly", quantity=1)
    entitlement = {
        "user_id": "user-1",
        "is_active": True,
        "stripe_subscription_id": "sub_123",
    }

    with pytest.raises(HTTPException) as exc:
        api.managed_billing_checkout(req, entitlement)

    assert exc.value.status_code == 409
    assert "active subscription" in str(exc.value.detail).lower()


def test_subscription_row_to_entitlement_without_row_has_inactive_status_and_zero_quota() -> None:
    entitlement = api._subscription_row_to_entitlement("user-1", None)

    assert entitlement["user_id"] == "user-1"
    assert entitlement["status"] == "inactive"
    assert entitlement["is_active"] is False
    assert entitlement["agent_quota"] == 0
    assert entitlement["storage_cap_bytes"] == 0
    assert entitlement["storage_quota_gb"] == 0.0


def test_subscription_row_to_entitlement_reads_stored_quota_snapshot() -> None:
    future_cancel = datetime.now(UTC) + timedelta(days=2)
    row = {
        "status": "active",
        "quantity": 999,
        "agent_quota": 6,
        "storage_cap_bytes": 6 * GB,
        "storage_used_bytes": 123,
        "cancel_at": future_cancel.isoformat(),
        "stripe_customer_id": "cus_123",
        "stripe_subscription_id": "sub_123",
    }

    entitlement = api._subscription_row_to_entitlement("user-1", row)

    assert entitlement["user_id"] == "user-1"
    assert entitlement["is_active"] is True
    assert entitlement["status"] == "active"
    assert entitlement["agent_quota"] == 6
    assert entitlement["storage_cap_bytes"] == 6 * GB
    assert entitlement["storage_quota_gb"] == 6.0
    assert entitlement["stripe_customer_id"] == "cus_123"
    assert entitlement["stripe_subscription_id"] == "sub_123"


def test_build_quota_status_reports_remaining_capacity_from_managed_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "_resolve_agent_in_use", lambda user_id: 2)
    monkeypatch.setattr(api, "_sync_quota_usage_for_user", lambda user_id: 400)

    status = api._build_quota_status(
        {
            "user_id": "user-1",
            "agent_quota": 6,
            "storage_cap_bytes": 6 * GB,
        }
    )

    assert status["agent_quota"] == 6
    assert status["agent_in_use"] == 2
    assert status["agent_available"] == 4
    assert status["storage_used_bytes"] == 400
    assert status["storage_cap_bytes"] == 6 * GB


def test_build_quota_status_handles_zero_quota_without_negative_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "_resolve_agent_in_use", lambda user_id: 2)
    monkeypatch.setattr(api, "_sync_quota_usage_for_user", lambda user_id: 400)

    status = api._build_quota_status(
        {
            "user_id": "user-1",
            "agent_quota": 0,
            "storage_cap_bytes": 0,
        }
    )

    assert status["agent_quota"] == 0
    assert status["agent_in_use"] == 2
    assert status["agent_available"] == 0
    assert status["storage_cap_bytes"] == 0


def test_enforce_storage_quota_allows_upload_within_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "_resolve_agent_in_use", lambda user_id: 0)
    monkeypatch.setattr(api, "_sync_quota_usage_for_user", lambda user_id: 100)

    entitlement = {
        "user_id": "user-1",
        "storage_cap_bytes": 500,
        "storage_used_bytes": 100,
        "agent_quota": 3,
    }

    result = api._enforce_storage_quota_before_upload(entitlement, payload_size_bytes=300)

    assert result["storage_used_bytes"] == 100
    assert result["storage_cap_bytes"] == 500


def test_enforce_storage_quota_blocks_upload_over_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "_resolve_agent_in_use", lambda user_id: 0)
    monkeypatch.setattr(api, "_sync_quota_usage_for_user", lambda user_id: 400)

    entitlement = {
        "user_id": "user-1",
        "storage_cap_bytes": 500,
        "storage_used_bytes": 400,
        "agent_quota": 3,
    }

    with pytest.raises(HTTPException) as exc:
        api._enforce_storage_quota_before_upload(entitlement, payload_size_bytes=101)

    assert exc.value.status_code == 413
    assert "storage quota" in str(exc.value.detail).lower()


def test_enforce_agent_quota_allows_when_under_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "_resolve_agent_in_use", lambda user_id: 1)
    monkeypatch.setattr(api, "_sync_quota_usage_for_user", lambda user_id: 0)

    entitlement = {
        "user_id": "user-1",
        "agent_quota": 3,
        "storage_cap_bytes": 3 * GB,
    }

    snapshot = api._enforce_agent_quota(entitlement)

    assert snapshot["status"] == "ok"
    assert snapshot["agent_quota"] == 3
    assert snapshot["agent_in_use"] == 1
    assert snapshot["agent_available"] == 2


def test_enforce_agent_quota_blocks_when_at_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "_resolve_agent_in_use", lambda user_id: 3)
    monkeypatch.setattr(api, "_sync_quota_usage_for_user", lambda user_id: 0)

    entitlement = {
        "user_id": "user-1",
        "agent_quota": 3,
        "storage_cap_bytes": 3 * GB,
    }

    with pytest.raises(HTTPException) as exc:
        api._enforce_agent_quota(entitlement)

    assert exc.value.status_code == 403
    assert "agent limit" in str(exc.value.detail).lower()


def test_enforce_agent_quota_supports_large_customer_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "_resolve_agent_in_use", lambda user_id: 250)
    monkeypatch.setattr(api, "_sync_quota_usage_for_user", lambda user_id: 0)

    entitlement = {
        "user_id": "enterprise-user",
        "agent_quota": 300,
        "storage_cap_bytes": 300 * GB,
    }

    snapshot = api._enforce_agent_quota(entitlement)

    assert snapshot["agent_quota"] == 300
    assert snapshot["agent_in_use"] == 250
    assert snapshot["agent_available"] == 50


def test_validate_embedding_accepts_none_as_no_vector() -> None:
    assert api._validate_embedding(None) is None


def test_validate_embedding_accepts_exact_vector_dim_floaty_values() -> None:
    embedding = [1, 2.5, -3] + [0] * (api.VECTOR_DIM - 3)

    validated = api._validate_embedding(embedding)

    assert validated is not None
    assert validated[:3] == [1.0, 2.5, -3.0]
    assert len(validated) == api.VECTOR_DIM


@pytest.mark.parametrize("embedding", [[], [1, "bad"], ["bad"], [1.0]])
def test_validate_embedding_rejects_wrong_shape_or_non_numeric_values(embedding: list[object]) -> None:
    with pytest.raises(HTTPException):
        api._validate_embedding(embedding)  # type: ignore[arg-type]


def test_decoded_payload_size_bytes() -> None:
    payload = b"hello world"

    assert api._decoded_payload_size_bytes(base64.b64encode(payload).decode("ascii")) == len(payload)


def test_decoded_payload_size_bytes_rejects_invalid_base64() -> None:
    with pytest.raises(HTTPException):
        api._decoded_payload_size_bytes("not base64")


def test_cosine_similarity_identical_orthogonal_mismatched_and_zero_vectors() -> None:
    assert api._cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert api._cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert api._cosine_similarity([1.0], [1.0, 0.0]) == -1.0
    assert api._cosine_similarity([0.0, 0.0], [1.0, 0.0]) == -1.0


def test_business_quota_helpers_are_explicitly_managed_only_and_do_not_touch_local_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    """Business quota logic must stay isolated from local agent/vault behavior."""

    touched_local_storage = False

    def fail_if_local_storage_touched(*args: object, **kwargs: object) -> None:
        nonlocal touched_local_storage
        touched_local_storage = True
        raise AssertionError("managed business logic must not touch local storage")

    for name in ("LocalStorage", "Vault", "EncryptedStorage"):
        if hasattr(api, name):
            monkeypatch.setattr(api, name, fail_if_local_storage_touched)

    assert api._quantity_to_agent_quota(1) == 3
    assert api._quantity_to_storage_cap_bytes(1) == 3 * GB
    assert touched_local_storage is False


def test_normalize_email_trims_lowercases_and_validates_domain() -> None:
    assert api._normalize_email("  USER@Example.COM  ") == "user@example.com"

    for value in ("", "no-at-symbol", "user@example", "   "):
        with pytest.raises(HTTPException) as exc:
            api._normalize_email(value)

        assert exc.value.status_code == 400
        assert "valid email" in str(exc.value.detail).lower()


def test_bearer_token_accepts_case_insensitive_scheme_and_trims_token() -> None:
    assert api._bearer_token("bearer token-123 ") == "token-123"
    assert api._bearer_token("Bearer token-123") == "token-123"


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Basic token-123",
        "Bearer",
        "Bearer ",
        "Bearer    ",
    ],
)
def test_bearer_token_rejects_missing_malformed_or_blank_values(authorization: str | None) -> None:
    with pytest.raises(HTTPException) as exc:
        api._bearer_token(authorization)

    assert exc.value.status_code == 401


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"user_id": " user-1 "}, "user-1"),
        ({"userId": "user-2"}, "user-2"),
        ({"matriosha_user_id": "user-3"}, "user-3"),
        ({"user_id": "", "userId": "   ", "matriosha_user_id": 123}, None),
        ({}, None),
    ],
)
def test_extract_user_id_from_subscription_object_supports_known_metadata_keys(
    metadata: dict[str, object],
    expected: str | None,
) -> None:
    assert api._extract_user_id_from_subscription_object({"metadata": metadata}) == expected


@pytest.mark.parametrize(
    ("subscription", "expected"),
    [
        ({}, None),
        ({"items": None}, None),
        ({"items": []}, None),
        ({"items": {"data": []}}, None),
        ({"items": {"data": ["not-dict"]}}, None),
        ({"items": {"data": [{"id": "si_123", "quantity": 2}]}}, {"id": "si_123", "quantity": 2}),
    ],
)
def test_subscription_item_from_subscription_handles_malformed_shapes(
    subscription: dict[str, object],
    expected: dict[str, object] | None,
) -> None:
    assert api._subscription_item_from_subscription(subscription) == expected


def test_safe_int_defaults_invalid_values_but_preserves_valid_numeric_strings() -> None:
    assert api._safe_int("42") == 42
    assert api._safe_int("-7") == -7
    assert api._safe_int(None, default=9) == 9
    assert api._safe_int("bad", default=9) == 9


def test_storage_formatting_helpers_report_gb_to_two_decimals() -> None:
    assert api._bytes_to_gb(GB) == 1.0
    assert api._format_storage_used_vs_cap(512 * 1024 * 1024, 2 * GB) == "0.50/2.00 GB"


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ("read", "read"),
        (" WRITE ", "write"),
        ("admin", "admin"),
        ("", "write"),
    ],
)
def test_normalize_scope_accepts_known_scopes_and_defaults_empty_to_write(scope: str, expected: str) -> None:
    assert api._normalize_scope(scope) == expected


@pytest.mark.parametrize("scope", ["owner", "billing", "read write"])
def test_normalize_scope_rejects_unknown_scopes(scope: str) -> None:
    with pytest.raises(HTTPException) as exc:
        api._normalize_scope(scope)

    assert exc.value.status_code == 400
    assert "scope must be one of" in str(exc.value.detail).lower()


def test_extract_tags_trims_deduplicates_and_ignores_non_string_values() -> None:
    envelope = {
        "tags": [
            " alpha ",
            "beta",
            "alpha",
            "",
            "   ",
            123,
            None,
            "Beta",
        ]
    }

    assert api._extract_tags(envelope) == ["alpha", "beta", "Beta"]


def test_extract_tags_returns_empty_list_for_missing_or_non_list_tags() -> None:
    assert api._extract_tags({}) == []
    assert api._extract_tags({"tags": "alpha"}) == []


class _FakeSupabaseExecuteResult:
    def __init__(self, data: list[dict[str, object]] | None = None) -> None:
        self.data = data or []


class _FakeSupabaseTable:
    def __init__(self, name: str, parent: "_FakeSupabaseClient") -> None:
        self.name = name
        self.parent = parent
        self.last_upsert: dict[str, object] | None = None

    def upsert(self, row: dict[str, object], on_conflict: str | None = None) -> "_FakeSupabaseTable":
        self.parent.upserts.append(
            {
                "table": self.name,
                "row": row,
                "on_conflict": on_conflict,
            }
        )
        self.last_upsert = row
        return self

    def select(self, columns: str) -> "_FakeSupabaseTable":
        self.parent.selects.append({"table": self.name, "columns": columns})
        return self

    def eq(self, column: str, value: object) -> "_FakeSupabaseTable":
        self.parent.filters.append({"table": self.name, "column": column, "value": value})
        return self

    def limit(self, count: int) -> "_FakeSupabaseTable":
        self.parent.limits.append({"table": self.name, "count": count})
        return self

    def update(self, row: dict[str, object]) -> "_FakeSupabaseTable":
        self.parent.updates.append({"table": self.name, "row": row})
        return self

    def execute(self) -> _FakeSupabaseExecuteResult:
        if self.name == "subscriptions":
            return _FakeSupabaseExecuteResult(self.parent.subscription_lookup_rows)
        return _FakeSupabaseExecuteResult([])


class _FakeSupabaseClient:
    def __init__(self, subscription_lookup_rows: list[dict[str, object]] | None = None) -> None:
        self.subscription_lookup_rows = subscription_lookup_rows or []
        self.upserts: list[dict[str, object]] = []
        self.updates: list[dict[str, object]] = []
        self.selects: list[dict[str, object]] = []
        self.filters: list[dict[str, object]] = []
        self.limits: list[dict[str, object]] = []
        self.pending_insert = False

    def table(self, name: str) -> _FakeSupabaseTable:
        return _FakeSupabaseTable(name, self)


def test_upsert_subscription_snapshot_uses_metadata_user_id_and_large_quantity(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeSupabaseClient()
    ensured_users: list[str] = []

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)
    monkeypatch.setattr(api, "_ensure_public_user", lambda user_id: ensured_users.append(user_id))

    subscription = {
        "id": "sub_123",
        "customer": "cus_123",
        "status": "active",
        "current_period_end": 2_000_000_000,
        "metadata": {"user_id": " user-1 "},
        "items": {
            "data": [
                {
                    "id": "si_123",
                    "quantity": 100,
                    "price": {"unit_amount": 900},
                }
            ]
        },
    }

    assert api._upsert_subscription_snapshot_from_stripe(subscription) is True

    assert ensured_users == ["user-1"]
    assert len(fake_db.upserts) == 1
    upsert = fake_db.upserts[0]
    assert upsert["table"] == "subscriptions"
    assert upsert["on_conflict"] == "user_id"

    row = _as_dict(upsert["row"])
    assert row["user_id"] == "user-1"
    assert row["status"] == "active"
    assert row["stripe_customer_id"] == "cus_123"
    assert row["stripe_subscription_id"] == "sub_123"
    assert row["stripe_subscription_item_id"] == "si_123"
    assert row["agent_quota"] == 300
    assert row["storage_cap_bytes"] == 300 * GB
    assert row["unit_price_cents"] == 900


def test_upsert_subscription_snapshot_defaults_missing_item_to_one_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeSupabaseClient()

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)
    monkeypatch.setattr(api, "_ensure_public_user", lambda user_id: None)

    subscription = {
        "id": "sub_missing_item",
        "customer": "cus_missing_item",
        "status": "active",
        "metadata": {"user_id": "user-1"},
        "items": {"data": []},
    }

    assert api._upsert_subscription_snapshot_from_stripe(subscription) is True

    row = _as_dict(fake_db.upserts[0]["row"])
    assert row["agent_quota"] == 3
    assert row["storage_cap_bytes"] == 3 * GB
    assert row["stripe_subscription_item_id"] is None
    assert row["unit_price_cents"] == 900


def test_upsert_subscription_snapshot_preserves_access_until_period_end_when_canceling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeSupabaseClient()

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)
    monkeypatch.setattr(api, "_ensure_public_user", lambda user_id: None)

    subscription = {
        "id": "sub_canceling",
        "customer": "cus_canceling",
        "status": "canceled",
        "current_period_end": 2_000_000_000,
        "cancel_at_period_end": True,
        "cancel_at": None,
        "metadata": {"user_id": "user-1"},
        "items": {"data": [{"id": "si_canceling", "quantity": 2, "price": {"unit_amount": 900}}]},
    }

    assert api._upsert_subscription_snapshot_from_stripe(subscription, override_status="canceled") is True

    row = _as_dict(fake_db.upserts[0]["row"])
    assert row["status"] == "active"
    assert row["cancel_at"] == "2033-05-18T03:33:20Z"
    assert row["current_period_end"] == "2033-05-18T03:33:20Z"
    assert row["agent_quota"] == 6
    assert row["storage_cap_bytes"] == 6 * GB


def test_upsert_subscription_snapshot_can_resolve_user_id_by_existing_stripe_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeSupabaseClient(subscription_lookup_rows=[{"user_id": "user-from-db"}])

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)
    monkeypatch.setattr(api, "_ensure_public_user", lambda user_id: None)

    subscription = {
        "id": "sub_existing",
        "customer": "cus_existing",
        "status": "active",
        "items": {"data": [{"id": "si_existing", "quantity": 1, "price": {"unit_amount": 900}}]},
    }

    assert api._upsert_subscription_snapshot_from_stripe(subscription) is True

    row = _as_dict(fake_db.upserts[0]["row"])
    assert row["user_id"] == "user-from-db"
    assert {"table": "subscriptions", "column": "stripe_subscription_id", "value": "sub_existing"} in fake_db.filters


def test_upsert_subscription_snapshot_returns_false_when_user_cannot_be_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeSupabaseClient(subscription_lookup_rows=[])

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    subscription = {
        "id": "sub_unknown",
        "customer": "cus_unknown",
        "status": "active",
        "items": {"data": [{"quantity": 1}]},
    }

    assert api._upsert_subscription_snapshot_from_stripe(subscription) is False
    assert fake_db.upserts == []


class _FakeAuthUser:
    def __init__(self, *, user_id: object, email: str | None = "user@example.com", aud: str | None = "authenticated", role: str | None = "user") -> None:
        self.id = user_id
        self.email = email
        self.aud = aud
        self.role = role


class _FakeAuthResult:
    def __init__(self, user: object | None) -> None:
        self.user = user


class _FakeSupabaseAuth:
    def __init__(self, result: object | None = None, exc: Exception | None = None) -> None:
        self.result = result
        self.exc = exc
        self.tokens: list[str] = []

    def get_user(self, token: str) -> object:
        self.tokens.append(token)
        if self.exc:
            raise self.exc
        return self.result


class _FakeSupabaseAuthClient:
    def __init__(self, auth: _FakeSupabaseAuth) -> None:
        self.auth = auth


def test_get_authenticated_user_returns_supabase_identity_and_ensures_public_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = _FakeSupabaseAuth(
        result=_FakeAuthResult(
            _FakeAuthUser(user_id="user-1", email="USER@example.com", aud="authenticated", role="member")
        )
    )
    ensured_users: list[str] = []

    monkeypatch.setattr(api, "_supabase_anon_client", lambda: _FakeSupabaseAuthClient(auth))
    monkeypatch.setattr(api, "_ensure_public_user", lambda user_id: ensured_users.append(user_id))

    user = api._get_authenticated_user("Bearer session-token")

    assert auth.tokens == ["session-token"]
    assert ensured_users == ["user-1"]
    assert user == {
        "user_id": "user-1",
        "email": "USER@example.com",
        "aud": "authenticated",
        "role": "member",
    }


def test_get_authenticated_user_wraps_supabase_exception_as_401(monkeypatch: pytest.MonkeyPatch) -> None:
    auth = _FakeSupabaseAuth(exc=RuntimeError("boom"))

    monkeypatch.setattr(api, "_supabase_anon_client", lambda: _FakeSupabaseAuthClient(auth))

    with pytest.raises(HTTPException) as exc:
        api._get_authenticated_user("Bearer session-token")

    assert exc.value.status_code == 401
    assert "invalid session" in str(exc.value.detail).lower()
    assert "runtimeerror" in str(exc.value.detail).lower()


@pytest.mark.parametrize("result", [_FakeAuthResult(None), _FakeAuthResult(_FakeAuthUser(user_id=None))])
def test_get_authenticated_user_rejects_missing_user_or_missing_user_id(
    monkeypatch: pytest.MonkeyPatch,
    result: _FakeAuthResult,
) -> None:
    auth = _FakeSupabaseAuth(result=result)

    monkeypatch.setattr(api, "_supabase_anon_client", lambda: _FakeSupabaseAuthClient(auth))

    with pytest.raises(HTTPException) as exc:
        api._get_authenticated_user("Bearer session-token")

    assert exc.value.status_code == 401
    assert "invalid session" in str(exc.value.detail).lower()


def test_get_subscription_row_for_user_marks_expired_active_subscription_canceled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired_cancel_at = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    fake_db = _FakeSupabaseClient(
        subscription_lookup_rows=[
            {
                "user_id": "user-1",
                "status": "active",
                "cancel_at": expired_cancel_at,
            }
        ]
    )

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    row = api._get_subscription_row_for_user("user-1")

    assert row is not None
    assert row["status"] == "canceled"
    assert fake_db.updates
    assert fake_db.updates[0]["table"] == "subscriptions"
    assert _as_dict(fake_db.updates[0]["row"])["status"] == "canceled"


def test_require_active_subscription_passes_active_entitlement_and_blocks_inactive() -> None:
    active = {"user_id": "user-1", "is_active": True}
    inactive = {"user_id": "user-1", "is_active": False}

    assert api.require_active_subscription(active) == active

    with pytest.raises(HTTPException) as exc:
        api.require_active_subscription(inactive)

    assert exc.value.status_code == 403
    assert "active subscription" in str(exc.value.detail).lower()


def test_get_active_subscription_entitlement_for_user_blocks_without_active_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "_get_subscription_row_for_user", lambda user_id: None)

    with pytest.raises(HTTPException) as exc:
        api._get_active_subscription_entitlement_for_user("user-1")

    assert exc.value.status_code == 403
    assert "active subscription" in str(exc.value.detail).lower()


def test_get_active_subscription_entitlement_for_user_returns_active_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api,
        "_get_subscription_row_for_user",
        lambda user_id: {
            "status": "active",
            "agent_quota": 6,
            "storage_cap_bytes": 6 * GB,
        },
    )

    entitlement = api._get_active_subscription_entitlement_for_user("user-1")

    assert entitlement["user_id"] == "user-1"
    assert entitlement["is_active"] is True
    assert entitlement["agent_quota"] == 6
    assert entitlement["storage_cap_bytes"] == 6 * GB


def test_require_agent_scope_ignores_user_auth_and_accepts_allowed_agent_scope() -> None:
    api._require_agent_scope({"auth_kind": "user"}, {"read"})

    api._require_agent_scope(
        {"auth_kind": "agent", "agent_scope": "write"},
        {"read", "write"},
    )


def test_require_agent_scope_blocks_agent_scope_not_in_allowed_set() -> None:
    with pytest.raises(HTTPException) as exc:
        api._require_agent_scope(
            {"auth_kind": "agent", "agent_scope": "read"},
            {"write", "admin"},
        )

    assert exc.value.status_code == 403
    assert "cannot perform" in str(exc.value.detail).lower()


class _FakeAgentTokenTable:
    def __init__(self, parent: "_FakeAgentTokenDb") -> None:
        self.parent = parent

    def select(self, columns: str) -> "_FakeAgentTokenTable":
        self.parent.selects.append(columns)
        return self

    def eq(self, column: str, value: object) -> "_FakeAgentTokenTable":
        self.parent.filters.append({"column": column, "value": value})
        return self

    def limit(self, count: int) -> "_FakeAgentTokenTable":
        self.parent.limits.append(count)
        return self

    def update(self, row: dict[str, object]) -> "_FakeAgentTokenTable":
        self.parent.updates.append(row)
        if self.parent.raise_on_update:
            raise RuntimeError("telemetry failed")
        return self

    def execute(self) -> _FakeSupabaseExecuteResult:
        return _FakeSupabaseExecuteResult(self.parent.rows)


class _FakeAgentTokenDb:
    def __init__(self, rows: list[dict[str, object]], *, raise_on_update: bool = False) -> None:
        self.rows = rows
        self.raise_on_update = raise_on_update
        self.selects: list[str] = []
        self.filters: list[dict[str, object]] = []
        self.limits: list[int] = []
        self.updates: list[dict[str, object]] = []

    def table(self, name: str) -> _FakeAgentTokenTable:
        assert name == "agent_tokens"
        return _FakeAgentTokenTable(self)


def test_get_agent_token_context_rejects_non_agent_token() -> None:
    with pytest.raises(HTTPException) as exc:
        api._get_agent_token_context("regular-session-token")

    assert exc.value.status_code == 401
    assert "invalid agent token" in str(exc.value.detail).lower()


def test_get_agent_token_context_rejects_lookup_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeAgentTokenDb([])

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    with pytest.raises(HTTPException) as exc:
        api._get_agent_token_context("mt_missing")

    assert exc.value.status_code == 401
    assert "invalid agent token" in str(exc.value.detail).lower()


@pytest.mark.parametrize(
    "row",
    [
        {"id": "tok-1", "user_id": "user-1", "revoked": True},
        {"id": "tok-1", "user_id": "user-1", "revoked_at": "2026-01-01T00:00:00Z"},
    ],
)
def test_get_agent_token_context_rejects_revoked_tokens(
    monkeypatch: pytest.MonkeyPatch,
    row: dict[str, object],
) -> None:
    fake_db = _FakeAgentTokenDb([row])

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    with pytest.raises(HTTPException) as exc:
        api._get_agent_token_context("mt_revoked")

    assert exc.value.status_code == 401
    assert "revoked" in str(exc.value.detail).lower()


def test_get_agent_token_context_rejects_expired_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeAgentTokenDb(
        [
            {
                "id": "tok-1",
                "user_id": "user-1",
                "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            }
        ]
    )

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    with pytest.raises(HTTPException) as exc:
        api._get_agent_token_context("mt_expired")

    assert exc.value.status_code == 401
    assert "expired" in str(exc.value.detail).lower()


def test_get_agent_token_context_rejects_token_without_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeAgentTokenDb([{"id": "tok-1", "user_id": "   "}])

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    with pytest.raises(HTTPException) as exc:
        api._get_agent_token_context("mt_orphan")

    assert exc.value.status_code == 401
    assert "no owner" in str(exc.value.detail).lower()


def test_get_agent_token_context_returns_actor_and_updates_last_used(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeAgentTokenDb(
        [
            {
                "id": "tok-1",
                "user_id": "user-1",
                "scope": " ADMIN ",
                "name": "Deploy Agent",
                "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            }
        ]
    )

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    actor = api._get_agent_token_context("mt_valid")

    assert actor == {
        "kind": "agent",
        "agent_token_id": "tok-1",
        "user_id": "user-1",
        "scope": "admin",
        "name": "Deploy Agent",
    }
    assert fake_db.updates
    assert "last_used" in fake_db.updates[0]
    assert {"column": "id", "value": "tok-1"} in fake_db.filters


def test_get_agent_token_context_ignores_last_used_telemetry_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeAgentTokenDb(
        [
            {
                "id": "tok-1",
                "user_id": "user-1",
                "scope": "write",
                "name": "Agent",
            }
        ],
        raise_on_update=True,
    )

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    actor = api._get_agent_token_context("mt_valid")

    assert actor["user_id"] == "user-1"
    assert actor["scope"] == "write"


class _FakeCountResult:
    def __init__(self, *, count: object = None, data: list[dict[str, object]] | None = None) -> None:
        self.count = count
        self.data = data or []


class _FakeQuotaTable:
    def __init__(self, name: str, parent: "_FakeQuotaDb") -> None:
        self.name = name
        self.parent = parent
        self.range_start: int | None = None
        self.range_end: int | None = None
        self.raise_on_is = False

    def select(self, columns: str, count: str | None = None) -> "_FakeQuotaTable":
        self.parent.selects.append({"table": self.name, "columns": columns, "count": count})
        return self

    def eq(self, column: str, value: object) -> "_FakeQuotaTable":
        self.parent.filters.append({"table": self.name, "column": column, "value": value})
        return self

    def is_(self, column: str, value: object) -> "_FakeQuotaTable":
        self.parent.is_filters.append({"table": self.name, "column": column, "value": value})
        if self.parent.raise_on_is:
            raise RuntimeError("is_ not supported")
        return self

    def range(self, start: int, end: int) -> "_FakeQuotaTable":
        self.range_start = start
        self.range_end = end
        self.parent.ranges.append({"table": self.name, "start": start, "end": end})
        return self

    def upsert(self, row: dict[str, object], on_conflict: str | None = None) -> "_FakeQuotaTable":
        self.parent.upserts.append({"table": self.name, "row": row, "on_conflict": on_conflict})
        return self

    def update(self, row: dict[str, object]) -> "_FakeQuotaTable":
        self.parent.updates.append({"table": self.name, "row": row})
        return self

    def execute(self) -> _FakeCountResult:
        if self.name == "memories":
            assert self.range_start is not None
            page_index = self.range_start // 500
            rows = self.parent.memory_pages[page_index] if page_index < len(self.parent.memory_pages) else []
            return _FakeCountResult(data=rows)

        if self.name == "agent_tokens":
            return _FakeCountResult(count=self.parent.agent_token_count)

        if self.name == "agents":
            if self.parent.raise_on_agents:
                raise RuntimeError("agents table unavailable")
            return _FakeCountResult(count=self.parent.connected_agent_count)

        return _FakeCountResult()


class _FakeQuotaDb:
    def __init__(
        self,
        *,
        memory_pages: list[list[dict[str, object]]] | None = None,
        agent_token_count: object = 0,
        connected_agent_count: object = 0,
        raise_on_is: bool = False,
        raise_on_agents: bool = False,
    ) -> None:
        self.memory_pages = memory_pages or []
        self.agent_token_count = agent_token_count
        self.connected_agent_count = connected_agent_count
        self.raise_on_is = raise_on_is
        self.raise_on_agents = raise_on_agents
        self.selects: list[dict[str, object]] = []
        self.filters: list[dict[str, object]] = []
        self.is_filters: list[dict[str, object]] = []
        self.ranges: list[dict[str, object]] = []
        self.upserts: list[dict[str, object]] = []
        self.updates: list[dict[str, object]] = []

    def table(self, name: str) -> _FakeQuotaTable:
        return _FakeQuotaTable(name, self)


def test_decoded_payload_size_bytes_validates_base64_payloads() -> None:
    payload = base64.b64encode(b"hello").decode("ascii")

    assert api._decoded_payload_size_bytes(payload) == 5

    for invalid in ("", "   ", "not base64!"):
        with pytest.raises(HTTPException) as exc:
            api._decoded_payload_size_bytes(invalid)

        assert exc.value.status_code == 400


def test_recompute_storage_usage_bytes_paginates_and_ignores_corrupt_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_1 = [{"payload_b64": base64.b64encode(b"a").decode("ascii")} for _ in range(500)]
    page_2 = [
        {"payload_b64": base64.b64encode(b"bc").decode("ascii")},
        {"payload_b64": "corrupt!"},
        {"payload_b64": base64.b64encode(b"def").decode("ascii")},
    ]
    fake_db = _FakeQuotaDb(memory_pages=[cast(list[dict[str, object]], page_1), cast(list[dict[str, object]], page_2)])

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    assert api._recompute_storage_usage_bytes("user-1") == 505
    assert fake_db.ranges == [
        {"table": "memories", "start": 0, "end": 499},
        {"table": "memories", "start": 500, "end": 999},
    ]


def test_increment_quota_usage_for_user_calls_atomic_rpc(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeMemoryDb(rpc_rows=[123])

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    assert api._increment_quota_usage_for_user("user-1", delta_bytes=77) == 123
    assert fake_db.rpcs == [
        {
            "name": "increment_storage_usage",
            "params": {"p_user_id": "user-1", "p_delta_bytes": 77},
        }
    ]


def test_sync_quota_usage_for_user_writes_usage_rows_without_recompute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeQuotaDb()

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    assert api._sync_quota_usage_for_user("user-1", storage_used_bytes=123) == 123

    assert fake_db.upserts[0]["table"] == "quota_usage"
    assert fake_db.upserts[0]["on_conflict"] == "user_id"
    assert _as_dict(fake_db.upserts[0]["row"])["storage_used_bytes"] == 123
    assert fake_db.updates[0]["table"] == "subscriptions"
    assert _as_dict(fake_db.updates[0]["row"])["storage_used_bytes"] == 123


def test_sync_quota_usage_for_user_recomputes_invalid_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeQuotaDb(
        memory_pages=[
            [{"payload_b64": base64.b64encode(b"abc").decode("ascii")}],
        ]
    )

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    assert api._sync_quota_usage_for_user("user-1", storage_used_bytes=-1) == 3


def test_count_active_agent_tokens_falls_back_when_null_filter_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeQuotaDb(agent_token_count="7", raise_on_is=True)

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    assert api._count_active_agent_tokens("user-1") == 7


def test_count_connected_agents_returns_zero_when_count_query_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeQuotaDb(raise_on_agents=True)

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    assert api._count_connected_agents("user-1") == 0


def test_resolve_agent_in_use_uses_higher_defensive_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "_count_active_agent_tokens", lambda user_id: 2)
    monkeypatch.setattr(api, "_count_connected_agents", lambda user_id: 5)

    assert api._resolve_agent_in_use("user-1") == 5


def test_build_quota_status_derives_storage_cap_from_gb_and_warns_over_80_percent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api, "_sync_quota_usage_for_user", lambda user_id: 850)
    monkeypatch.setattr(api, "_resolve_agent_in_use", lambda user_id: 2)

    status = api._build_quota_status(
        {
            "user_id": "user-1",
            "storage_cap_bytes": 0,
            "storage_quota_gb": 1000 / GB,
            "agent_quota": 3,
        }
    )

    assert status["storage_used_bytes"] == 850
    assert status["storage_cap_bytes"] == 1000
    assert status["storage_used_percent"] == 85.0
    assert status["agent_in_use"] == 2
    assert status["agent_available"] == 1
    assert status["warnings"]


def test_enforce_storage_quota_allows_exact_cap_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api,
        "_build_quota_status",
        lambda entitlement, **kwargs: {
            "storage_cap_bytes": 100,
            "storage_used_bytes": 80,
        },
    )

    assert api._enforce_storage_quota_before_upload({"user_id": "user-1"}, payload_size_bytes=20) == {
        "storage_cap_bytes": 100,
        "storage_used_bytes": 80,
    }


def test_enforce_storage_quota_blocks_zero_cap_and_projected_overage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api,
        "_build_quota_status",
        lambda entitlement, **kwargs: {
            "storage_cap_bytes": 0,
            "storage_used_bytes": 0,
        },
    )

    with pytest.raises(HTTPException) as exc:
        api._enforce_storage_quota_before_upload({"user_id": "user-1"}, payload_size_bytes=1)

    assert exc.value.status_code == 413

    monkeypatch.setattr(
        api,
        "_build_quota_status",
        lambda entitlement, **kwargs: {
            "storage_cap_bytes": 100,
            "storage_used_bytes": 80,
        },
    )

    with pytest.raises(HTTPException) as exc:
        api._enforce_storage_quota_before_upload({"user_id": "user-1"}, payload_size_bytes=21)

    assert exc.value.status_code == 413
    assert "storage quota exceeded" in str(exc.value.detail).lower()


def test_enforce_agent_quota_blocks_when_in_use_reaches_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api,
        "_build_quota_status",
        lambda entitlement, **kwargs: {
            "agent_quota": 3,
            "agent_in_use": 3,
        },
    )

    with pytest.raises(HTTPException) as exc:
        api._enforce_agent_quota({"user_id": "user-1"})

    assert exc.value.status_code == 403
    assert "agent limit reached" in str(exc.value.detail).lower()


def test_enforce_agent_quota_allows_below_quota_and_currently_treats_zero_quota_as_unlimited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api,
        "_build_quota_status",
        lambda entitlement, **kwargs: {
            "agent_quota": 3,
            "agent_in_use": 2,
        },
    )
    assert api._enforce_agent_quota({"user_id": "user-1"}) == {"agent_quota": 3, "agent_in_use": 2}

    monkeypatch.setattr(
        api,
        "_build_quota_status",
        lambda entitlement, **kwargs: {
            "agent_quota": 0,
            "agent_in_use": 999,
        },
    )
    assert api._enforce_agent_quota({"user_id": "user-1"}) == {"agent_quota": 0, "agent_in_use": 999}


class _FakeMemoryResult:
    def __init__(self, data: list[dict[str, object]] | None = None) -> None:
        self.data = data or []


class _FakeMemoryTable:
    def __init__(self, name: str, parent: "_FakeMemoryDb") -> None:
        self.name = name
        self.parent = parent

    def select(self, columns: str) -> "_FakeMemoryTable":
        self.parent.selects.append({"table": self.name, "columns": columns})
        return self

    def insert(self, row: dict[str, object]) -> "_FakeMemoryTable":
        self.parent.inserts.append({"table": self.name, "row": row})
        return self

    def upsert(self, row: dict[str, object], on_conflict: str | None = None) -> "_FakeMemoryTable":
        self.parent.upserts.append({"table": self.name, "row": row, "on_conflict": on_conflict})
        if self.parent.raise_on_vector_upsert and self.name == "memory_vectors":
            raise RuntimeError("vector index failed")
        return self

    def delete(self) -> "_FakeMemoryTable":
        self.parent.deletes.append({"table": self.name})
        return self

    def eq(self, column: str, value: object) -> "_FakeMemoryTable":
        self.parent.filters.append({"table": self.name, "column": column, "value": value})
        return self

    def order(self, column: str, desc: bool = False) -> "_FakeMemoryTable":
        self.parent.orders.append({"table": self.name, "column": column, "desc": desc})
        return self

    def limit(self, count: int) -> "_FakeMemoryTable":
        self.parent.limits.append({"table": self.name, "count": count})
        return self

    def execute(self) -> _FakeMemoryResult:
        if self.name == "memories" and self.parent.inserts:
            return _FakeMemoryResult(self.parent.insert_rows)
        if self.name == "memories":
            return _FakeMemoryResult(self.parent.memory_rows)
        return _FakeMemoryResult([])


class _FakeMemoryRpc:
    def __init__(self, parent: "_FakeMemoryDb") -> None:
        self.parent = parent

    def execute(self) -> _FakeMemoryResult:
        return _FakeMemoryResult(self.parent.rpc_rows)


class _FakeMemoryDb:
    def __init__(
        self,
        *,
        insert_rows: list[dict[str, object]] | None = None,
        memory_rows: list[dict[str, object]] | None = None,
        rpc_rows: list[dict[str, object]] | None = None,
        raise_on_vector_upsert: bool = False,
    ) -> None:
        self.insert_rows = insert_rows or []
        self.memory_rows = memory_rows or []
        self.rpc_rows = rpc_rows or []
        self.raise_on_vector_upsert = raise_on_vector_upsert
        self.selects: list[dict[str, object]] = []
        self.inserts: list[dict[str, object]] = []
        self.upserts: list[dict[str, object]] = []
        self.deletes: list[dict[str, object]] = []
        self.filters: list[dict[str, object]] = []
        self.orders: list[dict[str, object]] = []
        self.limits: list[dict[str, object]] = []
        self.rpcs: list[dict[str, object]] = []

    def table(self, name: str) -> _FakeMemoryTable:
        return _FakeMemoryTable(name, self)

    def rpc(self, name: str, params: dict[str, object]) -> _FakeMemoryRpc:
        self.rpcs.append({"name": name, "params": params})
        return _FakeMemoryRpc(self)


def test_vector_from_db_parses_lists_and_postgres_style_strings() -> None:
    assert api._vector_from_db([1, "2.5", 3]) == [1.0, 2.5, 3.0]
    assert api._vector_from_db("[1, 2.5, -3]") == [1.0, 2.5, -3.0]
    assert api._vector_from_db("[]") == []
    assert api._vector_from_db("[1, nope]") is None
    assert api._vector_from_db({"bad": "shape"}) is None


def test_cosine_similarity_handles_identical_orthogonal_and_invalid_vectors() -> None:
    assert api._cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert api._cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert api._cosine_similarity([], []) == -1.0
    assert api._cosine_similarity([1.0], [1.0, 2.0]) == -1.0
    assert api._cosine_similarity([0.0, 0.0], [1.0, 2.0]) == -1.0


def test_managed_memories_create_stores_memory_tags_embedding_and_increments_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeMemoryDb(insert_rows=[{"id": "mem-1"}])
    quota_increments: list[tuple[str, int]] = []

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)
    monkeypatch.setattr(api, "_enforce_storage_quota_before_upload", lambda entitlement, payload_size_bytes: {})
    monkeypatch.setattr(
        api,
        "_increment_quota_usage_for_user",
        lambda user_id, *, delta_bytes: quota_increments.append((user_id, delta_bytes)),
    )

    req = api.ManagedMemoryCreateRequest(
        envelope={
            "tags": [" alpha ", "alpha", "beta", 123],
            "filename": "Notes.TXT",
            "mime_type": "text/plain",
            "content_kind": "text",
            "plaintext_bytes": 7,
        },
        payload_b64=base64.b64encode(b"payload").decode("ascii"),
        embedding=[0.0] * api.VECTOR_DIM,
    )

    result = api.managed_memories_create(req, {"user_id": "user-1", "auth_kind": "user"})

    assert result == {"id": "mem-1", "memory_id": "mem-1"}
    assert fake_db.inserts[0]["table"] == "memories"
    memory_row = _as_dict(fake_db.inserts[0]["row"])
    assert memory_row["tags"] == ["alpha", "beta"]
    assert memory_row["safe_metadata"]["filename"] == "Notes.TXT"
    assert memory_row["safe_metadata"]["mime_type"] == "text/plain"
    assert memory_row["search_keywords"] == ["alpha", "beta", "notes.txt", "text/plain", "text", "txt"]
    assert len(memory_row["metadata_hashes"]) == len(memory_row["search_keywords"])
    assert api._metadata_hash("alpha") in memory_row["metadata_hashes"]
    assert fake_db.upserts[0]["table"] == "memory_vectors"
    assert _as_dict(fake_db.upserts[0]["row"])["memory_id"] == "mem-1"
    assert quota_increments == [("user-1", len(b"payload"))]


def test_managed_memories_create_rejects_insert_without_returned_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeMemoryDb(insert_rows=[{"id": "   "}])

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)
    monkeypatch.setattr(api, "_enforce_storage_quota_before_upload", lambda entitlement, payload_size_bytes: {})

    req = api.ManagedMemoryCreateRequest(
        envelope={},
        payload_b64=base64.b64encode(b"payload").decode("ascii"),
        embedding=None,
    )

    with pytest.raises(HTTPException) as exc:
        api.managed_memories_create(req, {"user_id": "user-1", "auth_kind": "user"})

    assert exc.value.status_code == 500
    assert "memory id" in str(exc.value.detail).lower()


def test_managed_memories_create_rolls_back_memory_when_vector_indexing_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeMemoryDb(insert_rows=[{"id": "mem-1"}], raise_on_vector_upsert=True)

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)
    monkeypatch.setattr(api, "_enforce_storage_quota_before_upload", lambda entitlement, payload_size_bytes: {})

    req = api.ManagedMemoryCreateRequest(
        envelope={},
        payload_b64=base64.b64encode(b"payload").decode("ascii"),
        embedding=[0.0] * api.VECTOR_DIM,
    )

    with pytest.raises(HTTPException) as exc:
        api.managed_memories_create(req, {"user_id": "user-1", "auth_kind": "user"})

    assert exc.value.status_code == 500
    assert {"table": "memory_vectors"} in fake_db.deletes or {"table": "memories"} in fake_db.deletes
    assert {"table": "memories", "column": "id", "value": "mem-1"} in fake_db.filters


def test_managed_memories_create_rejects_invalid_base64_before_db_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeMemoryDb(insert_rows=[{"id": "mem-1"}])

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    req = api.ManagedMemoryCreateRequest(envelope={}, payload_b64="not-base64!", embedding=None)

    with pytest.raises(HTTPException) as exc:
        api.managed_memories_create(req, {"user_id": "user-1", "auth_kind": "user"})

    assert exc.value.status_code == 400
    assert fake_db.inserts == []


def test_managed_search_candidate_only_uses_safe_metadata_rpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeMemoryDb(
        rpc_rows=[
            {
                "id": "mem-1",
                "score": 0.9,
                "safe_metadata": {"content_kind": "text"},
                "tags": ["alpha"],
                "search_keywords": ["alpha", "text"],
                "metadata_hashes": ["hash-alpha"],
                "created_at": "2026-05-02T00:00:00Z",
            }
        ]
    )

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    req = api.ManagedSearchRequest(
        embedding=[0.0] * api.VECTOR_DIM,
        limit=50,
        candidate_only=True,
        tags=["alpha"],
        search_keywords=["text"],
        metadata_hashes=["hash-alpha"],
    )
    result = api.managed_search(req, {"user_id": "user-1", "auth_kind": "user"})

    assert fake_db.rpcs[0]["name"] == "match_memory_candidates"
    params = _as_dict(fake_db.rpcs[0]["params"])
    assert params["p_user_id"] == "user-1"
    assert params["p_limit"] == 50
    assert params["p_tags"] == ["alpha"]
    assert params["p_search_keywords"] == ["text"]
    assert params["p_metadata_hashes"] == ["hash-alpha"]
    assert result["items"] == [
        {
            "id": "mem-1",
            "memory_id": "mem-1",
            "score": 0.9,
            "created_at": "2026-05-02T00:00:00Z",
            "safe_metadata": {"content_kind": "text"},
            "tags": ["alpha"],
            "search_keywords": ["alpha", "text"],
            "metadata_hashes": ["hash-alpha"],
        }
    ]
    assert "payload_b64" not in result["items"][0]
    assert "envelope" not in result["items"][0]


def test_managed_memories_list_filters_by_row_tags_and_envelope_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeMemoryDb(
        memory_rows=[
            {
                "id": "mem-1",
                "envelope": {"title": "one"},
                "payload_b64": "a",
                "created_at": "now",
                "tags": ["alpha"],
            },
            {
                "id": "mem-2",
                "envelope": {"tags": ["beta"]},
                "payload_b64": "b",
                "created_at": "later",
                "tags": None,
            },
            {
                "id": "mem-3",
                "envelope": {"tags": ["gamma"]},
                "payload_b64": "c",
                "created_at": "later",
                "tags": [],
            },
        ]
    )

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    result = api.managed_memories_list(tag="beta", limit=100, entitlement={"user_id": "user-1", "auth_kind": "user"})

    assert result["items"] == [
        {
            "id": "mem-2",
            "memory_id": "mem-2",
            "envelope": {"tags": ["beta"]},
            "payload_b64": "b",
            "created_at": "later",
            "tags": [],
            "safe_metadata": {},
            "search_keywords": [],
            "metadata_hashes": [],
        }
    ]
    assert result["memories"] == result["items"]


def test_managed_memories_fetch_returns_404_for_missing_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeMemoryDb(memory_rows=[])

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    with pytest.raises(HTTPException) as exc:
        api.managed_memories_fetch("missing", {"user_id": "user-1", "auth_kind": "user"})

    assert exc.value.status_code == 404
    assert "not found" in str(exc.value.detail).lower()


def test_managed_memories_delete_removes_vector_and_memory_then_syncs_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeMemoryDb(memory_rows=[{"id": "mem-1"}])
    synced_users: list[str] = []

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)
    monkeypatch.setattr(api, "_sync_quota_usage_for_user", lambda user_id: synced_users.append(user_id))

    result = api.managed_memories_delete("mem-1", {"user_id": "user-1", "auth_kind": "user"})

    assert result == {"deleted": True, "ok": True}
    assert {"table": "memory_vectors"} in fake_db.deletes
    assert {"table": "memories"} in fake_db.deletes
    assert synced_users == ["user-1"]


def test_managed_search_rejects_missing_query_and_embedding() -> None:
    req = api.ManagedSearchRequest(query="   ", embedding=None)

    with pytest.raises(HTTPException) as exc:
        api.managed_search(req, {"user_id": "user-1", "auth_kind": "user"})

    assert exc.value.status_code == 400
    assert "either" in str(exc.value.detail).lower()


def test_managed_search_embedding_rpc_handles_score_distance_and_missing_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeMemoryDb(
        rpc_rows=[
            {"id": "mem-1", "score": 0.987654321, "envelope": {"title": "one"}, "payload_b64": "a"},
            {"memory_id": "mem-2", "distance": 0.25, "envelope": {"title": "two"}, "payload_b64": "b"},
            {"score": 1.0, "envelope": {"title": "missing id"}},
        ]
    )

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    req = api.ManagedSearchRequest(embedding=[0.0] * api.VECTOR_DIM, limit=10)
    result = api.managed_search(req, {"user_id": "user-1", "auth_kind": "user"})

    assert fake_db.rpcs[0]["name"] == "match_memory_vectors"
    assert _as_dict(fake_db.rpcs[0]["params"])["p_user_id"] == "user-1"
    assert result["items"] == [
        {
            "id": "mem-1",
            "memory_id": "mem-1",
            "score": 0.987654,
            "envelope": {"title": "one"},
            "payload_b64": "a",
            "created_at": None,
        },
        {
            "id": "mem-2",
            "memory_id": "mem-2",
            "score": 0.75,
            "envelope": {"title": "two"},
            "payload_b64": "b",
            "created_at": None,
        },
    ]
    assert result["results"] == result["items"]


def test_managed_search_lexical_is_case_insensitive_and_respects_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeMemoryDb(
        memory_rows=[
            {"id": "mem-1", "envelope": {"text": "Alpha Project"}, "payload_b64": "a", "created_at": "1"},
            {"id": "mem-2", "envelope": {"text": "alpha second"}, "payload_b64": "b", "created_at": "2"},
            {"id": "mem-3", "envelope": {"text": "unrelated"}, "payload_b64": "c", "created_at": "3"},
        ]
    )

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    req = api.ManagedSearchRequest(query="ALPHA", limit=2)
    result = api.managed_search(req, {"user_id": "user-1", "auth_kind": "user"})

    assert result["items"] == [
        {
            "id": "mem-1",
            "memory_id": "mem-1",
            "envelope": {"text": "Alpha Project"},
            "payload_b64": "a",
            "created_at": "1",
        },
        {
            "id": "mem-2",
            "memory_id": "mem-2",
            "envelope": {"text": "alpha second"},
            "payload_b64": "b",
            "created_at": "2",
        },
    ]
    assert {"table": "memories", "count": 2000} in fake_db.limits


class _FakeManagedAgentTokenResult:
    def __init__(self, data: list[dict[str, object]] | None = None) -> None:
        self.data = data or []


class _FakeManagedAgentTokenTable:
    def __init__(self, name: str, parent: "_FakeManagedAgentTokenDb") -> None:
        self.name = name
        self.parent = parent
        self.current_select: str | None = None
        self.did_delete = False

    def select(self, columns: str) -> "_FakeManagedAgentTokenTable":
        self.current_select = columns
        self.parent.selects.append({"table": self.name, "columns": columns})
        return self

    def insert(self, row: dict[str, object]) -> "_FakeManagedAgentTokenTable":
        self.parent.inserts.append({"table": self.name, "row": row})
        if self.parent.raise_on_full_insert and ("scope" in row or "expires_at" in row):
            raise RuntimeError('column "scope" does not exist')
        self.parent.pending_insert = True
        return self

    def delete(self) -> "_FakeManagedAgentTokenTable":
        self.did_delete = True
        self.parent.deletes.append({"table": self.name})
        return self

    def eq(self, column: str, value: object) -> "_FakeManagedAgentTokenTable":
        self.parent.filters.append({"table": self.name, "column": column, "value": value})
        return self

    def order(self, column: str, desc: bool = False) -> "_FakeManagedAgentTokenTable":
        self.parent.orders.append({"table": self.name, "column": column, "desc": desc})
        return self

    def limit(self, count: int) -> "_FakeManagedAgentTokenTable":
        self.parent.limits.append({"table": self.name, "count": count})
        return self

    def execute(self) -> _FakeManagedAgentTokenResult:
        if self.did_delete:
            return _FakeManagedAgentTokenResult([])
        if self.parent.pending_insert:
            self.parent.pending_insert = False
            insert_index = self.parent.insert_execute_count
            self.parent.insert_execute_count += 1
            if insert_index < len(self.parent.insert_rows_by_call):
                return _FakeManagedAgentTokenResult(self.parent.insert_rows_by_call[insert_index])
            return _FakeManagedAgentTokenResult(self.parent.insert_rows)
        if self.current_select == "*":
            return _FakeManagedAgentTokenResult(self.parent.list_rows)
        return _FakeManagedAgentTokenResult(self.parent.lookup_rows)


class _FakeManagedAgentTokenDb:
    def __init__(
        self,
        *,
        insert_rows: list[dict[str, object]] | None = None,
        insert_rows_by_call: list[list[dict[str, object]]] | None = None,
        lookup_rows: list[dict[str, object]] | None = None,
        list_rows: list[dict[str, object]] | None = None,
        raise_on_full_insert: bool = False,
    ) -> None:
        self.insert_rows = insert_rows or []
        self.insert_rows_by_call = insert_rows_by_call or []
        self.lookup_rows = lookup_rows or []
        self.list_rows = list_rows or []
        self.raise_on_full_insert = raise_on_full_insert
        self.insert_execute_count = 0
        self.selects: list[dict[str, object]] = []
        self.inserts: list[dict[str, object]] = []
        self.deletes: list[dict[str, object]] = []
        self.filters: list[dict[str, object]] = []
        self.orders: list[dict[str, object]] = []
        self.limits: list[dict[str, object]] = []
        self.pending_insert = False

    def table(self, name: str) -> _FakeManagedAgentTokenTable:
        return _FakeManagedAgentTokenTable(name, self)


def test_managed_agent_tokens_create_hashes_plaintext_and_returns_token_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeManagedAgentTokenDb(insert_rows=[{"id": "tok-1"}])
    quota_checked: list[dict[str, object]] = []

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)
    monkeypatch.setattr(api, "_enforce_agent_quota", lambda entitlement: quota_checked.append(entitlement))
    monkeypatch.setattr(api.secrets, "token_urlsafe", lambda size: "fixed-secret")

    req = api.ManagedAgentTokenCreateRequest(name="  My Agent  ", scope="read", expires_at="2030-01-01T00:00:00Z")
    result = api.managed_agent_tokens_create(req, {"user_id": "user-1"})

    assert quota_checked == [{"user_id": "user-1"}]
    assert result["id"] == "tok-1"
    assert result["token_id"] == "tok-1"
    assert result["name"] == "My Agent"
    assert result["scope"] == "read"
    assert result["token"] == "mt_fixed-secret"
    assert result["token_plaintext"] == "mt_fixed-secret"

    inserted = _as_dict(fake_db.inserts[0]["row"])
    assert inserted["user_id"] == "user-1"
    assert inserted["name"] == "My Agent"
    assert inserted["token_hash"] == hashlib.sha256(b"mt_fixed-secret").hexdigest()
    assert "token" not in inserted
    assert "token_plaintext" not in inserted


def test_managed_agent_tokens_create_rejects_blank_name_after_quota_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quota_checked: list[dict[str, object]] = []

    monkeypatch.setattr(api, "_enforce_agent_quota", lambda entitlement: quota_checked.append(entitlement))

    req = api.ManagedAgentTokenCreateRequest(name="   ")

    with pytest.raises(HTTPException) as exc:
        api.managed_agent_tokens_create(req, {"user_id": "user-1"})

    assert exc.value.status_code == 400
    assert "name is required" in str(exc.value.detail).lower()
    assert quota_checked == [{"user_id": "user-1"}]


def test_managed_agent_tokens_create_falls_back_when_scope_columns_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeManagedAgentTokenDb(
        insert_rows_by_call=[
            [{"id": "tok-legacy"}],
        ],
        raise_on_full_insert=True,
    )

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)
    monkeypatch.setattr(api, "_enforce_agent_quota", lambda entitlement: None)
    monkeypatch.setattr(api.secrets, "token_urlsafe", lambda size: "legacy-secret")

    req = api.ManagedAgentTokenCreateRequest(name="Legacy Agent", scope="read", expires_at="2030-01-01T00:00:00Z")
    result = api.managed_agent_tokens_create(req, {"user_id": "user-1"})

    assert result["id"] == "tok-legacy"
    assert "scope" in _as_dict(fake_db.inserts[0]["row"])
    assert "expires_at" in _as_dict(fake_db.inserts[0]["row"])
    assert "scope" not in _as_dict(fake_db.inserts[1]["row"])
    assert "expires_at" not in _as_dict(fake_db.inserts[1]["row"])


def test_managed_agent_tokens_create_uses_lookup_when_insert_does_not_return_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeManagedAgentTokenDb(insert_rows=[], lookup_rows=[{"id": "tok-from-lookup"}])

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)
    monkeypatch.setattr(api, "_enforce_agent_quota", lambda entitlement: None)
    monkeypatch.setattr(api.secrets, "token_urlsafe", lambda size: "lookup-secret")

    req = api.ManagedAgentTokenCreateRequest(name="Lookup Agent")
    result = api.managed_agent_tokens_create(req, {"user_id": "user-1"})

    assert result["id"] == "tok-from-lookup"
    assert {"table": "agent_tokens", "columns": "id"} in fake_db.selects
    assert {"table": "agent_tokens", "column": "token_hash", "value": hashlib.sha256(b"mt_lookup-secret").hexdigest()} in fake_db.filters
    assert {"table": "agent_tokens", "count": 1} in fake_db.limits


def test_managed_agent_tokens_create_fails_when_no_id_can_be_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeManagedAgentTokenDb(insert_rows=[], lookup_rows=[])

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)
    monkeypatch.setattr(api, "_enforce_agent_quota", lambda entitlement: None)

    req = api.ManagedAgentTokenCreateRequest(name="No Id Agent")

    with pytest.raises(HTTPException) as exc:
        api.managed_agent_tokens_create(req, {"user_id": "user-1"})

    assert exc.value.status_code == 500
    assert "could not create agent token" in str(exc.value.detail).lower()


def test_managed_agent_tokens_list_returns_defaults_and_revoked_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeManagedAgentTokenDb(
        list_rows=[
            {
                "id": "tok-1",
                "name": "",
                "scope": "",
                "created_at": "created",
                "last_used": "used",
                "expires_at": None,
                "revoked": False,
            },
            {
                "id": "tok-2",
                "name": "Agent 2",
                "scope": "read",
                "created_at": "created2",
                "last_used": None,
                "expires_at": "2030",
                "revoked_at": "now",
            },
        ]
    )

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    result = api.managed_agent_tokens_list({"user_id": "user-1"})

    assert result["items"] == [
        {
            "id": "tok-1",
            "name": "token",
            "scope": "write",
            "created_at": "created",
            "last_used": "used",
            "expires_at": None,
            "revoked": False,
        },
        {
            "id": "tok-2",
            "name": "Agent 2",
            "scope": "read",
            "created_at": "created2",
            "last_used": None,
            "expires_at": "2030",
            "revoked": True,
        },
    ]
    assert result["tokens"] == result["items"]


def test_managed_agent_tokens_delete_checks_owner_and_deletes_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeManagedAgentTokenDb(lookup_rows=[{"id": "tok-1"}])

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    result = api.managed_agent_tokens_delete("tok-1", {"user_id": "user-1"})

    assert result == {"deleted": True, "ok": True}
    assert {"table": "agent_tokens"} in fake_db.deletes
    assert {"table": "agent_tokens", "column": "id", "value": "tok-1"} in fake_db.filters
    assert {"table": "agent_tokens", "column": "user_id", "value": "user-1"} in fake_db.filters


def test_managed_agent_tokens_delete_returns_404_when_missing_or_wrong_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeManagedAgentTokenDb(lookup_rows=[])

    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    with pytest.raises(HTTPException) as exc:
        api.managed_agent_tokens_delete("missing", {"user_id": "user-1"})

    assert exc.value.status_code == 404
    assert "not found" in str(exc.value.detail).lower()
    assert fake_db.deletes == []

class _FakeWebhookResult:
    def __init__(self, data: list[dict[str, object]] | None = None) -> None:
        self.data = data or []


class _FakeWebhookTable:
    def __init__(self, name: str, parent: "_FakeWebhookDb") -> None:
        self.name = name
        self.parent = parent

    def insert(self, row: dict[str, object]) -> "_FakeWebhookTable":
        self.parent.inserts.append({"table": self.name, "row": row})
        if self.parent.raise_duplicate:
            raise RuntimeError("duplicate key value violates unique constraint uq_stripe_webhook_events_event_id")
        if self.parent.raise_insert:
            raise RuntimeError("database unavailable")
        return self

    def update(self, row: dict[str, object]) -> "_FakeWebhookTable":
        self.parent.updates.append({"table": self.name, "row": row})
        if self.parent.raise_update:
            raise RuntimeError("update failed")
        return self

    def eq(self, column: str, value: object) -> "_FakeWebhookTable":
        self.parent.filters.append({"table": self.name, "column": column, "value": value})
        return self

    def execute(self) -> _FakeWebhookResult:
        return _FakeWebhookResult([])


class _FakeWebhookDb:
    def __init__(
        self,
        *,
        raise_duplicate: bool = False,
        raise_insert: bool = False,
        raise_update: bool = False,
    ) -> None:
        self.raise_duplicate = raise_duplicate
        self.raise_insert = raise_insert
        self.raise_update = raise_update
        self.inserts: list[dict[str, object]] = []
        self.updates: list[dict[str, object]] = []
        self.filters: list[dict[str, object]] = []

    def table(self, name: str) -> _FakeWebhookTable:
        return _FakeWebhookTable(name, self)


class _FakeStripeWebhook:
    event: dict[str, object] = {}

    @classmethod
    def construct_event(cls, *, payload: bytes, sig_header: str | None, secret: str) -> dict[str, object]:
        return cls.event


class _FakeStripeModule:
    Webhook = _FakeStripeWebhook


class _FakeRequest:
    def __init__(self, body: bytes = b'{"ok": true}') -> None:
        self._body = body

    async def body(self) -> bytes:
        return self._body


def test_stripe_webhook_rejects_missing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.stripe_webhook(cast(Any, _FakeRequest()), stripe_signature="sig"))

    assert exc.value.status_code == 503
    assert "STRIPE_WEBHOOK_SECRET" in exc.value.detail


def test_stripe_webhook_idempotent_duplicate_event(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeWebhookDb(raise_duplicate=True)
    _FakeStripeWebhook.event = {
        "id": "evt-1",
        "type": "customer.subscription.created",
        "data": {"object": {"id": "sub-1", "object": "subscription"}},
    }

    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setitem(sys.modules, "stripe", _FakeStripeModule)
    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    result = asyncio.run(api.stripe_webhook(cast(Any, _FakeRequest()), stripe_signature="sig"))

    assert result == {"status": "ok", "processed": False, "idempotent": True}


def test_stripe_webhook_unhandled_event_is_journaled(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeWebhookDb()
    _FakeStripeWebhook.event = {
        "id": "evt-unhandled",
        "type": "charge.succeeded",
        "data": {"object": {"id": "ch-1", "object": "charge"}},
    }

    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setitem(sys.modules, "stripe", _FakeStripeModule)
    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)

    result = asyncio.run(api.stripe_webhook(cast(Any, _FakeRequest()), stripe_signature="sig"))

    assert result == {"status": "ok", "processed": True, "handled": False}
    assert _as_dict(fake_db.inserts[0]["row"])["event_id"] == "evt-unhandled"


def test_stripe_webhook_subscription_deleted_uses_fallback_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = _FakeWebhookDb(raise_update=True)
    fallback_calls: list[dict[str, object]] = []
    _FakeStripeWebhook.event = {
        "id": "evt-deleted",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub-1", "customer": "cus-1", "object": "subscription"}},
    }

    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setitem(sys.modules, "stripe", _FakeStripeModule)
    monkeypatch.setattr(api, "_supabase_service_client", lambda: fake_db)
    monkeypatch.setattr(api, "_upsert_subscription_snapshot_from_stripe", lambda obj, override_status=None: False)

    def fake_update_by_refs(**kwargs: object) -> bool:
        fallback_calls.append(kwargs)
        return True

    monkeypatch.setattr(api, "_update_subscription_status_by_refs", fake_update_by_refs)

    result = asyncio.run(api.stripe_webhook(cast(Any, _FakeRequest()), stripe_signature="sig"))

    assert result == {"status": "ok", "processed": True, "updated_subscription": True}
    assert fallback_calls == [
        {
            "status": "canceled",
            "stripe_customer_id": "cus-1",
            "stripe_subscription_id": "sub-1",
        }
    ]


def test_read_root_and_basic_health_endpoints() -> None:
    assert api.read_root() == {"status": "Matriosha API is running"}
    assert api.health() == {"status": "ok"}


def test_health_secrets_reports_presence_and_lengths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)

    result = api.health_secrets(None)

    assert result["status"] == "ok"
    assert result["env"]["SUPABASE_URL"]["present"] is True
    assert result["env"]["SUPABASE_URL"]["length"] == len("https://example.supabase.co")
    assert result["env"]["STRIPE_SECRET_KEY"]["present"] is False


def test_health_deps_reports_import_status() -> None:
    result = api.health_deps(None)

    assert result["status"] == "ok"
    assert set(result["deps"]) == {"supabase", "stripe", "httpx"}


def test_health_supabase_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)

    assert api.health_supabase(None) == {
        "status": "error",
        "provider": "supabase",
        "error": "missing_env",
    }


def test_health_stripe_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)

    assert api.health_stripe(None) == {
        "status": "error",
        "provider": "stripe",
        "error": "missing_env",
    }
