from __future__ import annotations
from typing import Any, cast

import os

import pytest
from fastapi import HTTPException

from matriosha.api import OtpVerifyRequest, managed_auth_otp_verify, require_admin_token
from matriosha.core.managed import auth as managed_auth
from matriosha.core.secrets import SecretManager, SecretManagerError


def test_require_admin_token_accepts_legacy_admin_token_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADMIN_DIAGNOSTICS_TOKEN", raising=False)
    monkeypatch.setenv("ADMIN_TOKEN", "legacy-secret")

    require_admin_token("legacy-secret")


def test_require_admin_token_prefers_canonical_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_DIAGNOSTICS_TOKEN", "canonical-secret")
    monkeypatch.setenv("ADMIN_TOKEN", "legacy-secret")

    require_admin_token("canonical-secret")

    with pytest.raises(HTTPException):
        require_admin_token("legacy-secret")


def test_secret_manager_has_no_default_gcp_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)

    manager = SecretManager()

    assert manager.project_id is None
    assert manager.client is None


def test_secret_manager_fail_fast_requires_explicit_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)

    with pytest.raises(SecretManagerError):
        SecretManager(fail_fast=True)


def test_ensure_process_managed_passphrase_does_not_write_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MATRIOSHA_PASSPHRASE", raising=False)
    monkeypatch.setattr(
        managed_auth, "resolve_managed_passphrase", lambda profile_name: "managed-secret"
    )

    assert managed_auth.ensure_process_managed_passphrase("default") == "managed-secret"
    assert "MATRIOSHA_PASSPHRASE" not in os.environ


def test_otp_verify_does_not_require_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class DummyUser:
        id = "user_123"
        email = "user@example.com"

    class DummySession:
        access_token = "access"
        refresh_token = "refresh"
        expires_in = 3600
        token_type = "bearer"

    class DummyResult:
        session = DummySession()
        user = DummyUser()

    class DummyAuth:
        def verify_otp(self, payload: dict[str, str]) -> DummyResult:
            assert payload == {
                "email": "user@example.com",
                "token": "123456",
                "type": "email",
            }
            return DummyResult()

    class DummyClient:
        auth = DummyAuth()

    class DummyRequest:
        client = None
        headers: dict[str, str] = {}

    monkeypatch.setattr("matriosha.api._supabase_anon_client", lambda: DummyClient())
    monkeypatch.setattr("matriosha.api._apply_otp_rate_limit", lambda **kwargs: None)
    monkeypatch.setattr("matriosha.api._ensure_public_user", lambda user_id: calls.append(user_id))

    def fail_if_called(user_id: str) -> None:
        raise AssertionError(
            "_require_active_subscription_for_user must not be called during OTP verify"
        )

    monkeypatch.setattr("matriosha.api._require_active_subscription_for_user", fail_if_called)

    result = managed_auth_otp_verify(
        OtpVerifyRequest(email="user@example.com", code="123456"),
        cast(Any, DummyRequest()),
    )

    assert result["access_token"] == "access"
    assert result["refresh_token"] == "refresh"
    assert calls == ["user_123"]
