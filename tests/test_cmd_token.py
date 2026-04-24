from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import respx
from typer.testing import CliRunner

from matriosha.cli.commands import token as token_cmd
from matriosha.cli.main import app
from matriosha.cli.utils import mode_guard
from matriosha.core.config import MatrioshaConfig, Profile

runner = CliRunner()


def _managed_profile(endpoint: str = "https://managed.example") -> Profile:
    return Profile(
        name="default",
        mode="managed",
        managed_endpoint=endpoint,
        created_at=datetime.now(timezone.utc),
    )


def _patch_managed_mode(monkeypatch, profile: Profile) -> None:
    cfg = MatrioshaConfig(profiles={"default": profile}, active_profile="default")

    monkeypatch.setattr(mode_guard, "load_config", lambda: cfg)
    monkeypatch.setattr(mode_guard, "get_active_profile", lambda _cfg, _override: profile)

    monkeypatch.setattr(token_cmd, "load_config", lambda: cfg)
    monkeypatch.setattr(token_cmd, "get_active_profile", lambda _cfg, _override: profile)


def test_generate_returns_token_and_list_shows_revoked_false(monkeypatch) -> None:
    _patch_managed_mode(monkeypatch, _managed_profile())

    state = {
        "tokens": [
            {
                "id": "9d83f4de-1efe-4f26-9df2-45f3a3e0e8a5",
                "name": "ci-agent",
                "scope": "write",
                "created_at": "2026-04-23T10:00:00Z",
                "last_used": None,
                "expires_at": "2026-04-30T10:00:00Z",
                "revoked": False,
            }
        ]
    }

    def _create(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert body["name"] == "ci-agent"
        assert body["scope"] == "write"
        return httpx.Response(
            200,
            json={
                "id": state["tokens"][0]["id"],
                "name": "ci-agent",
                "scope": "write",
                "expires_at": state["tokens"][0]["expires_at"],
                "token_plaintext": "mt_abcdefghijklmnopqrstuvwxyz1234567890ABCDE",
            },
        )

    def _list(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": state["tokens"]})

    env = {
        "MATRIOSHA_MANAGED_TOKEN": "token-ok",
        "SUPABASE_URL": "https://supabase.example",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
    }

    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://managed.example/managed/agent-tokens").mock(side_effect=_create)
        mock.get("https://managed.example/managed/agent-tokens").mock(side_effect=_list)

        generated = runner.invoke(app, ["token", "generate", "ci-agent", "--json"], env=env)
        listed = runner.invoke(app, ["token", "list", "--json"], env=env)

    assert generated.exit_code == 0
    data = json.loads(generated.stdout)
    assert data["id"] == state["tokens"][0]["id"]
    assert data["token"].startswith("mt_")
    assert data["scope"] == "write"

    assert listed.exit_code == 0
    rows = json.loads(listed.stdout)
    assert rows[0]["id"] == state["tokens"][0]["id"]
    assert rows[0]["revoked"] is False


def test_revoke_then_list_shows_revoked_true(monkeypatch) -> None:
    _patch_managed_mode(monkeypatch, _managed_profile())

    token_id = "7a4b5c6d-6ef1-43a9-aa11-b8f3ba0a45f0"
    state = {
        "tokens": [
            {
                "id": token_id,
                "name": "nightly-sync",
                "scope": "admin",
                "created_at": "2026-04-23T10:00:00Z",
                "last_used": None,
                "expires_at": "2026-05-23T10:00:00Z",
                "revoked": False,
            }
        ]
    }

    def _list(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": state["tokens"]})

    def _revoke(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(token_id):
            state["tokens"][0]["revoked"] = True
        return httpx.Response(204)

    env = {
        "MATRIOSHA_MANAGED_TOKEN": "token-ok",
        "SUPABASE_URL": "https://supabase.example",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
    }

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://managed.example/managed/agent-tokens").mock(side_effect=_list)
        mock.delete(f"https://managed.example/managed/agent-tokens/{token_id}").mock(side_effect=_revoke)

        revoked = runner.invoke(app, ["token", "revoke", token_id[:8], "--yes", "--json"], env=env)
        listed = runner.invoke(app, ["token", "list", "--json"], env=env)

    assert revoked.exit_code == 0
    revoked_payload = json.loads(revoked.stdout)
    assert revoked_payload["revoked"] is True

    assert listed.exit_code == 0
    rows = json.loads(listed.stdout)
    assert rows[0]["revoked"] is True


def test_inspect_with_prefix_matching(monkeypatch) -> None:
    _patch_managed_mode(monkeypatch, _managed_profile())

    token_id = "12345678-90ab-cdef-1234-567890abcdef"

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://managed.example/managed/agent-tokens").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": token_id,
                            "name": "readonly-bot",
                            "scope": "read",
                            "created_at": "2026-04-23T10:00:00Z",
                            "last_used": "2026-04-23T12:00:00Z",
                            "expires_at": "2026-05-01T10:00:00Z",
                            "revoked": False,
                            "token_hash": "sha256:deadbeef",
                            "salt": "salt-01",
                        }
                    ]
                },
            )
        )

        result = runner.invoke(
            app,
            ["token", "inspect", token_id[:10], "--json"],
            env={
                "MATRIOSHA_MANAGED_TOKEN": "token-ok",
                "SUPABASE_URL": "https://supabase.example",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
            },
        )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["id"] == token_id
    assert payload["name"] == "readonly-bot"
    assert "token" not in payload


def test_generate_rate_limited_429_returns_exit_40(monkeypatch) -> None:
    _patch_managed_mode(monkeypatch, _managed_profile())

    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://managed.example/managed/agent-tokens").mock(
            return_value=httpx.Response(429, json={"error": "rate limited"})
        )

        result = runner.invoke(
            app,
            ["--plain", "token", "generate", "limited-agent"],
            env={
                "MATRIOSHA_MANAGED_TOKEN": "token-ok",
                "SUPABASE_URL": "https://supabase.example",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
            },
        )

    assert result.exit_code == 40
    assert "rate limit" in result.stdout.lower()
