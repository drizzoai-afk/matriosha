from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from matriosha.cli.commands import auth as auth_package
from matriosha.cli.commands.auth import common as auth_common
from matriosha.cli.commands.auth import login as auth_login
from matriosha.cli.commands.auth import logout as auth_logout
from matriosha.cli.utils import mode_guard
from matriosha.cli.main import app
from matriosha.core.config import MatrioshaConfig, Profile
from matriosha.core.managed.auth import ManagedTokens, TokenStore

runner = CliRunner()


@pytest.fixture()
def managed_profile() -> Profile:
    return Profile(
        name="default",
        mode="managed",
        managed_endpoint="https://managed.example",
        created_at=datetime.now(timezone.utc),
    )


def _patch_managed_mode(monkeypatch, profile: Profile) -> None:
    cfg = MatrioshaConfig(profiles={"default": profile}, active_profile="default")
    monkeypatch.setattr(auth_common, "load_config", lambda: cfg)
    monkeypatch.setattr(auth_common, "get_active_profile", lambda _cfg, _override: profile)
    monkeypatch.setattr(auth_package, "require_mode", lambda _mode: (lambda _ctx: None))


def test_auth_login_happy_path_created(monkeypatch, managed_profile, tmp_path) -> None:
    _patch_managed_mode(monkeypatch, managed_profile)

    import matriosha.core.managed.auth as managed_auth

    monkeypatch.setattr(managed_auth.platformdirs, "user_data_dir", lambda _app: str(tmp_path / "data"))
    monkeypatch.setattr(managed_auth.platformdirs, "user_config_dir", lambda _app: str(tmp_path / "cfg"))

    class _FakeFlow:
        def __init__(self, *_args, **_kwargs):
            pass

        async def verify(self, *, email: str, code: str):
            assert email == "u1@example.com"
            assert code == "123456"
            return ManagedTokens(access_token="access-1", refresh_token="refresh-1", expires_at=None)

    class _FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def whoami(self):
            return {"user_id": "u1", "email": "u1@example.com"}

    monkeypatch.setattr(auth_login, "EmailOtpFlow", _FakeFlow)
    monkeypatch.setattr(auth_login, "ManagedClient", _FakeClient)

    async def _bootstrap(*_args, **_kwargs):
        return {"status": "created"}

    monkeypatch.setattr(auth_login, "ensure_managed_key_bootstrap", _bootstrap)

    result = runner.invoke(app, ["auth", "login", "--json", "--email", "u1@example.com", "--code", "123456"])
    assert result.exit_code == 0, result.stdout
    done = json.loads([ln for ln in result.stdout.splitlines() if ln.strip()][-1])
    assert done["status"] == "authenticated"
    assert done["managed_key_bootstrap"] == "created"


def test_auth_login_existing_bootstrap_via_env_code(monkeypatch, managed_profile) -> None:
    _patch_managed_mode(monkeypatch, managed_profile)

    class _FakeFlow:
        def __init__(self, *_args, **_kwargs):
            pass

        async def verify(self, *, email: str, code: str):
            assert email == "u2@example.com"
            assert code == "654321"
            return ManagedTokens(access_token="access-1", refresh_token=None, expires_at=None)

    class _FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def whoami(self):
            return {"user_id": "u2", "email": "u2@example.com"}

    async def _bootstrap(*_args, **_kwargs):
        return {"status": "existing"}

    monkeypatch.setattr(auth_login, "EmailOtpFlow", _FakeFlow)
    monkeypatch.setattr(auth_login, "ManagedClient", _FakeClient)
    monkeypatch.setattr(auth_login, "ensure_managed_key_bootstrap", _bootstrap)

    result = runner.invoke(
        app,
        ["auth", "login", "--json", "--email", "u2@example.com"],
        env={"MATRIOSHA_AUTH_OTP_CODE": "654321"},
    )
    assert result.exit_code == 0, result.stdout
    done = json.loads([ln for ln in result.stdout.splitlines() if ln.strip()][-1])
    assert done["managed_key_bootstrap"] == "existing"


def test_auth_login_verify_error_maps_to_auth_exit(monkeypatch, managed_profile) -> None:
    _patch_managed_mode(monkeypatch, managed_profile)

    class _FailingFlow:
        def __init__(self, *_args, **_kwargs):
            pass

        async def verify(self, *, email: str, code: str):
            raise auth_common.EmailOtpFlowError("invalid code")

    monkeypatch.setattr(auth_login, "EmailOtpFlow", _FailingFlow)
    result = runner.invoke(app, ["auth", "login", "--json", "--email", "u3@example.com", "--code", "000000"])
    assert result.exit_code == 20
    payload = json.loads([ln for ln in result.stdout.splitlines() if ln.strip()][-1])
    assert payload["category"] == "AUTH"


def test_auth_rate_limit_backoff_called_after_many_attempts(monkeypatch, managed_profile) -> None:
    _patch_managed_mode(monkeypatch, managed_profile)
    calls = {"backoff": 0}

    class _Limiter:
        def __init__(self, *_args, **_kwargs):
            pass

        def apply_backoff_if_needed(self):
            calls["backoff"] += 1

        def record_attempt(self):
            return None

        def clear(self):
            return None

    class _Flow:
        def __init__(self, *_args, **_kwargs):
            pass

        async def verify(self, *, email: str, code: str):
            return ManagedTokens(access_token="access-1", refresh_token=None, expires_at=None)

    class _Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def whoami(self):
            return {"user_id": "u3", "email": "u3@example.com"}

    async def _bootstrap(*_args, **_kwargs):
        return {"status": "existing"}

    monkeypatch.setattr(auth_login, "LoginRateLimiter", _Limiter)
    monkeypatch.setattr(auth_login, "EmailOtpFlow", _Flow)
    monkeypatch.setattr(auth_login, "ManagedClient", _Client)
    monkeypatch.setattr(auth_login, "ensure_managed_key_bootstrap", _bootstrap)

    for _ in range(6):
        result = runner.invoke(app, ["auth", "login", "--json", "--email", "u3@example.com", "--code", "111111"])
        assert result.exit_code == 0
    assert calls["backoff"] == 6


def test_auth_logout_clears_store(monkeypatch, managed_profile, tmp_path) -> None:
    _patch_managed_mode(monkeypatch, managed_profile)

    import matriosha.core.managed.auth as managed_auth

    monkeypatch.setattr(managed_auth.platformdirs, "user_data_dir", lambda _app: str(tmp_path / "data"))
    monkeypatch.setattr(managed_auth.platformdirs, "user_config_dir", lambda _app: str(tmp_path / "cfg"))

    store = TokenStore("default")
    store.save({"access_token": "token-1"})

    class _Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def _request(self, *_args, **_kwargs):
            return {"status": "ok"}

    monkeypatch.setattr(auth_logout, "ManagedClient", _Client)

    result = runner.invoke(app, ["auth", "logout", "--json"])
    assert result.exit_code == 0
    assert store.load() is None


def test_auth_local_mode_guard_exits_30(monkeypatch) -> None:
    local_profile = Profile(name="default", mode="local", created_at=datetime.now(timezone.utc))
    cfg = MatrioshaConfig(profiles={"default": local_profile}, active_profile="default")

    monkeypatch.setattr(auth_common, "load_config", lambda: cfg)
    monkeypatch.setattr(auth_common, "get_active_profile", lambda _cfg, _override: local_profile)
    monkeypatch.setattr(mode_guard, "load_config", lambda: cfg)
    monkeypatch.setattr(mode_guard, "get_active_profile", lambda _cfg, _override: local_profile)

    result = runner.invoke(app, ["auth", "whoami", "--json"])
    assert result.exit_code == 30
