from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from matriosha.core.managed import auth


def test_managed_tokens_as_dict_preserves_fields() -> None:
    tokens = auth.ManagedTokens(
        access_token="access",
        refresh_token="refresh",
        expires_at="2030-01-01T00:00:00+00:00",
        managed_passphrase="secret",
    )

    assert tokens.as_dict() == {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "managed_passphrase": "secret",
        "token_type": "bearer",
        "scope": None,
    }


def test_managed_tokens_as_dict_preserves_none_optional_fields() -> None:
    tokens = auth.ManagedTokens(
        access_token="access",
        refresh_token="refresh",
        expires_at=None,
    )

    assert tokens.as_dict() == {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_at": None,
        "managed_passphrase": None,
        "token_type": "bearer",
        "scope": None,
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("hello", "hello"),
        ("", None),
        (None, None),
        (123, "123"),
        (False, "False"),
    ],
)
def test_optional_str_converts_truthy_and_falsey_non_none_values(
    value: object, expected: str | None
) -> None:
    assert auth._optional_str(value) == expected


def test_compute_expires_at_prefers_explicit_expires_at() -> None:
    assert (
        auth._compute_expires_at(3600, "2030-01-01T00:00:00+00:00") == "2030-01-01T00:00:00+00:00"
    )


def test_compute_expires_at_uses_expires_in_seconds() -> None:
    before = datetime.now(UTC)
    computed = auth._compute_expires_at(120, None)
    after = datetime.now(UTC)

    assert computed is not None
    parsed = datetime.fromisoformat(computed.replace("Z", "+00:00"))
    assert before + timedelta(seconds=110) <= parsed <= after + timedelta(seconds=130)


@pytest.mark.parametrize("expires_in", [None, "soon"])
def test_compute_expires_at_returns_none_when_expires_in_cannot_be_coerced(
    expires_in: object,
) -> None:
    assert auth._compute_expires_at(expires_in, None) is None


@pytest.mark.parametrize("expires_in", [-1, 0])
def test_compute_expires_at_accepts_zero_or_negative_offsets(expires_in: object) -> None:
    before = datetime.now(UTC)
    computed = auth._compute_expires_at(expires_in, None)
    after = datetime.now(UTC)

    assert computed is not None
    parsed = datetime.fromisoformat(computed.replace("Z", "+00:00"))
    assert before <= parsed <= after + timedelta(seconds=2)


def test_is_token_stale_treats_missing_expiry_as_not_stale() -> None:
    assert auth.is_token_stale(None) is False


def test_is_token_stale_handles_invalid_values_as_not_stale() -> None:
    assert auth.is_token_stale("not-a-date") is False


def test_is_token_stale_detects_expired_and_future_tokens() -> None:
    expired = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

    assert auth.is_token_stale(expired) is True
    assert auth.is_token_stale(future, clock_skew_seconds=30) is False


def test_safe_json_returns_dict_payload() -> None:
    response = httpx.Response(200, json={"ok": True})

    assert auth._safe_json(response) == {"ok": True}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=["not", "dict"]),
        httpx.Response(204),
    ],
)
def test_safe_json_returns_empty_dict_for_invalid_or_non_object_payload(
    response: httpx.Response,
) -> None:
    assert auth._safe_json(response) == {}


def test_ensure_managed_passphrase_in_payload_preserves_existing_value() -> None:
    payload = {"managed_passphrase": "existing"}

    assert auth.ensure_managed_passphrase_in_payload(payload) == {"managed_passphrase": "existing"}


def test_ensure_managed_passphrase_in_payload_generates_missing_value() -> None:
    payload = {"access_token": "token"}

    result = auth.ensure_managed_passphrase_in_payload(payload)

    assert result["access_token"] == "token"
    assert isinstance(result["managed_passphrase"], str)
    assert len(result["managed_passphrase"]) >= 32


def test_local_wrap_unwrap_round_trip() -> None:
    data_key = b"0" * 32
    salt = b"1" * 16
    passphrase = "managed-secret"

    wrapped = auth._wrap_data_key_locally(data_key, passphrase, salt)

    assert wrapped != data_key
    assert auth._unwrap_local_blob(wrapped, passphrase, salt) == data_key


def test_local_unwrap_rejects_wrong_passphrase() -> None:
    data_key = b"0" * 32
    salt = b"1" * 16
    wrapped = auth._wrap_data_key_locally(data_key, "right-passphrase", salt)

    with pytest.raises(Exception):
        auth._unwrap_local_blob(wrapped, "wrong-passphrase", salt)
