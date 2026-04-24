from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from matriosha.cli.commands import auth as auth_cmd
from matriosha.cli.main import app
from matriosha.core.config import MatrioshaConfig, Profile
from matriosha.core.managed.auth import DeviceAuthorization, ManagedTokens, TokenStore

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
    monkeypatch.setattr(auth_cmd, "load_config", lambda: cfg)
    monkeypatch.setattr(auth_cmd, "get_active_profile", lambda _cfg, _override: profile)
    monkeypatch.setattr(auth_cmd, "require_mode", lambda _mode: (lambda _ctx: None))


def test_auth_login_happy_path_created(monkeypatch, managed_profile, tmp_path) -> None:
    _patch_managed_mode(monkeypatch, managed_profile)

    import matriosha.core.managed.auth as managed_auth

    monkeypatch.setattr(managed_auth.platformdirs, "user_data_dir", lambda _app: str(tmp_path / "data"))
    monkeypatch.setattr(managed_auth.platformdirs, "user_config_dir", lambda _app: str(tmp_path / "cfg"))

    class _FakeFlow:
        def __init__(self, *_args, **_kwargs):
            pass

        async def start(self):
            return DeviceAuthorization(
                device_code="dev123",
                user_code="USER-123",
                verification_uri="https://verify.example",
                interval=1,
                expires_in=60,
            )

        async def poll(self, _authz):
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

    monkeypatch.setattr(auth_cmd, "DeviceCodeFlow", _FakeFlow)
    monkeypatch.setattr(auth_cmd, "ManagedClient", _FakeClient)
    async def _bootstrap(*_args, **_kwargs):
        return {"status": "created"}

    monkeypatch.setattr(auth_cmd, "ensure_managed_key_bootstrap", _bootstrap)

    result = runner.invoke(app, ["auth", "login", "--json"])
    assert result.exit_code == 0, result.stdout
    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    assert len(lines) == 2
    pending = json.loads(lines[0])
    done = json.loads(lines[1])
    assert pending["status"] == "pending"
    assert done["status"] == "authenticated"
    assert done["managed_key_bootstrap"] == "created"


def test_auth_login_existing_bootstrap(monkeypatch, managed_profile) -> None:
    _patch_managed_mode(monkeypatch, managed_profile)

    class _FakeFlow:
        def __init__(self, *_args, **_kwargs):
            pass

        async def start(self):
            return DeviceAuthorization("d", "U", "https://verify.example", 1, 60)

        async def poll(self, _authz):
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

    monkeypatch.setattr(auth_cmd, "DeviceCodeFlow", _FakeFlow)
    monkeypatch.setattr(auth_cmd, "ManagedClient", _FakeClient)
    monkeypatch.setattr(auth_cmd, "ensure_managed_key_bootstrap", _bootstrap)

    result = runner.invoke(app, ["auth", "login", "--json"])
    assert result.exit_code == 0, result.stdout
    done = json.loads([ln for ln in result.stdout.splitlines() if ln.strip()][-1])
    assert done["managed_key_bootstrap"] == "existing"


def test_auth_login_timeout_maps_to_auth_exit(monkeypatch, managed_profile) -> None:
    _patch_managed_mode(monkeypatch, managed_profile)

    class _TimeoutFlow:
        def __init__(self, *_args, **_kwargs):
            pass

        async def start(self):
            return DeviceAuthorization("d", "U", "https://verify.example", 1, 1)

        async def poll(self, _authz):
            raise auth_cmd.DeviceFlowError("device authorization timed out")

    monkeypatch.setattr(auth_cmd, "DeviceCodeFlow", _TimeoutFlow)
    result = runner.invoke(app, ["auth", "login", "--json"])
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

        async def start(self):
            return DeviceAuthorization("d", "U", "https://verify.example", 1, 60)

        async def poll(self, _authz):
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

    monkeypatch.setattr(auth_cmd, "LoginRateLimiter", _Limiter)
    monkeypatch.setattr(auth_cmd, "DeviceCodeFlow", _Flow)
    monkeypatch.setattr(auth_cmd, "ManagedClient", _Client)
    monkeypatch.setattr(auth_cmd, "ensure_managed_key_bootstrap", _bootstrap)

    for _ in range(6):
        result = runner.invoke(app, ["auth", "login", "--json"])
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

    monkeypatch.setattr(auth_cmd, "ManagedClient", _Client)

    result = runner.invoke(app, ["auth", "logout", "--json"])
    assert result.exit_code == 0
    assert store.load() is None


def test_auth_local_mode_guard_exits_30(monkeypatch) -> None:
    local_profile = Profile(name="default", mode="local", created_at=datetime.now(timezone.utc))
    cfg = MatrioshaConfig(profiles={"default": local_profile}, active_profile="default")

    monkeypatch.setattr(auth_cmd, "load_config", lambda: cfg)
    monkeypatch.setattr(auth_cmd, "get_active_profile", lambda _cfg, _override: local_profile)

    result = runner.invoke(app, ["auth", "whoami", "--json"])
    assert result.exit_code == 30
