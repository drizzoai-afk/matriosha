from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from matriosha.core.local_tokens import (
    LocalTokenError,
    create_local_agent_token,
    list_local_agent_tokens,
    verify_local_agent_token,
)


def _future_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")


def _past_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")


def test_local_token_verify_updates_last_used_and_hides_hash(monkeypatch, tmp_path):
    monkeypatch.setattr("platformdirs.user_data_dir", lambda appname: str(tmp_path / appname))

    created = create_local_agent_token(
        profile_name="default",
        name="local-agent",
        scope="read",
        expires_at=_future_iso(),
    )

    verified = verify_local_agent_token(
        profile_name="default",
        token_plaintext=created["token"],
        required_scope="read",
    )

    assert verified["id"] == created["id"]
    assert verified["name"] == "local-agent"
    assert verified["scope"] == "read"
    assert verified["last_used"] is not None
    assert "token" not in verified
    assert "token_hash" not in verified

    listed = list_local_agent_tokens("default")
    assert listed == [verified]
    assert "token_hash" not in listed[0]


def test_local_token_write_satisfies_required_read_scope(monkeypatch, tmp_path):
    import matriosha.core.local_tokens as local_tokens_module

    data_root = tmp_path / "data"
    monkeypatch.setattr(local_tokens_module.platformdirs, "user_data_dir", lambda appname: str(data_root))

    created = create_local_agent_token(
        profile_name="default",
        name="writer",
        scope="write",
        expires_at=None,
    )

    verified = verify_local_agent_token(
        profile_name="default",
        token_plaintext=created["token"],
        required_scope="read",
    )

    assert verified["id"] == created["id"]
    assert verified["scope"] == "write"
    assert verified["last_used"] is not None


def test_local_token_admin_satisfies_required_write_scope(monkeypatch, tmp_path):
    monkeypatch.setattr("platformdirs.user_data_dir", lambda appname: str(tmp_path / appname))

    created = create_local_agent_token(
        profile_name="default",
        name="admin-agent",
        scope="admin",
        expires_at=None,
    )

    verified = verify_local_agent_token(
        profile_name="default",
        token_plaintext=created["token"],
        required_scope="write",
    )

    assert verified["scope"] == "admin"


def test_local_token_wrong_prefix_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr("platformdirs.user_data_dir", lambda appname: str(tmp_path / appname))

    with pytest.raises(LocalTokenError) as exc:
        verify_local_agent_token(
            profile_name="default",
            token_plaintext="not_local",
            required_scope="read",
        )

    assert exc.value.code == "AUTH-LOCAL-401"


def test_local_token_unknown_token_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr("platformdirs.user_data_dir", lambda appname: str(tmp_path / appname))

    with pytest.raises(LocalTokenError) as exc:
        verify_local_agent_token(
            profile_name="default",
            token_plaintext="mtl_unknown",
            required_scope="read",
        )

    assert exc.value.code == "AUTH-LOCAL-401"


def test_local_token_expired_token_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr("platformdirs.user_data_dir", lambda appname: str(tmp_path / appname))

    created = create_local_agent_token(
        profile_name="default",
        name="expired-agent",
        scope="read",
        expires_at=_past_iso(),
    )

    with pytest.raises(LocalTokenError) as exc:
        verify_local_agent_token(
            profile_name="default",
            token_plaintext=created["token"],
            required_scope="read",
        )

    assert exc.value.code == "AUTH-LOCAL-403"
    assert "expired" in exc.value.message.lower()


def test_local_token_insufficient_scope_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr("platformdirs.user_data_dir", lambda appname: str(tmp_path / appname))

    created = create_local_agent_token(
        profile_name="default",
        name="reader-agent",
        scope="read",
        expires_at=None,
    )

    with pytest.raises(LocalTokenError) as exc:
        verify_local_agent_token(
            profile_name="default",
            token_plaintext=created["token"],
            required_scope="write",
        )

    assert exc.value.code == "AUTH-LOCAL-403"
    assert "scope" in exc.value.message.lower()
def test_local_token_revoke_marks_token_unusable(monkeypatch, tmp_path):
    monkeypatch.setattr("platformdirs.user_data_dir", lambda appname: str(tmp_path / appname))

    created = create_local_agent_token(
        profile_name="default",
        name="local-agent",
        scope="read",
        expires_at=None,
    )

    from matriosha.core.local_tokens import revoke_local_agent_token

    assert revoke_local_agent_token("default", created["id"][:8]) is True

    listed = list_local_agent_tokens("default")
    assert listed[0]["revoked"] is True

    with pytest.raises(LocalTokenError) as exc:
        verify_local_agent_token(
            profile_name="default",
            token_plaintext=created["token"],
            required_scope="read",
        )

    assert exc.value.code == "AUTH-LOCAL-403"
    assert "revoked" in exc.value.message.lower()


def test_local_token_revoke_unknown_prefix_returns_false(monkeypatch, tmp_path):
    monkeypatch.setattr("platformdirs.user_data_dir", lambda appname: str(tmp_path / appname))

    from matriosha.core.local_tokens import revoke_local_agent_token

    assert revoke_local_agent_token("default", "missing-token") is False
