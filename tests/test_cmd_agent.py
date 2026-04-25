from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import respx
from typer.testing import CliRunner

from matriosha.cli.commands.agent import common as agent_common
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

    monkeypatch.setattr(agent_common, "load_config", lambda: cfg)
    monkeypatch.setattr(agent_common, "get_active_profile", lambda _cfg, _override: profile)


def _managed_env() -> dict[str, str]:
    return {
        "MATRIOSHA_MANAGED_TOKEN": "managed-session-token",
        "SUPABASE_URL": "https://supabase.example",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
        "SUPABASE_ANON_KEY": "anon-key",
        "STRIPE_SECRET_KEY": "stripe-secret",
        "STRIPE_WEBHOOK_SECRET": "stripe-wh",
    }


def test_connect_with_valid_token_registers_agent(monkeypatch) -> None:
    _patch_managed_mode(monkeypatch, _managed_profile())

    def _connect(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer agt_valid_token"
        body = json.loads(request.content.decode("utf-8"))
        assert body["name"] == "Workstation"
        assert body["agent_kind"] == "desktop"
        return httpx.Response(
            200,
            json={
                "agent_id": "0a10f6a2-f5bb-4b6b-9f9a-f8a3f1111111",
                "fingerprint": "fp:aa:bb:cc:dd",
            },
        )

    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://managed.example/agents/connect").mock(side_effect=_connect)

        result = runner.invoke(
            app,
            [
                "agent",
                "connect",
                "--token",
                "agt_valid_token",
                "--name",
                "Workstation",
                "--kind",
                "desktop",
                "--json",
            ],
            env=_managed_env(),
        )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["agent_id"].startswith("0a10f6a2")
    assert payload["fingerprint"] == "fp:aa:bb:cc:dd"


def test_connect_with_invalid_token_returns_exit_20(monkeypatch) -> None:
    _patch_managed_mode(monkeypatch, _managed_profile())

    with respx.mock(assert_all_called=True) as mock:
        mock.post("https://managed.example/agents/connect").mock(
            return_value=httpx.Response(401, json={"error": "invalid token"})
        )

        result = runner.invoke(
            app,
            [
                "agent",
                "connect",
                "--token",
                "agt_invalid",
                "--name",
                "CI Runner",
                "--kind",
                "ci",
                "--json",
            ],
            env=_managed_env(),
        )

    assert result.exit_code == 20
    payload = json.loads(result.stdout)
    assert payload["category"] == "AUTH"


def test_remove_idempotent_when_agent_not_found(monkeypatch) -> None:
    _patch_managed_mode(monkeypatch, _managed_profile())

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://managed.example/agents").mock(return_value=httpx.Response(200, json={"items": []}))

        result = runner.invoke(
            app,
            ["agent", "remove", "12345678", "--yes", "--json"],
            env=_managed_env(),
        )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["removed"] is False
    assert payload["reason"] == "already_absent"


def test_list_output_format_contains_expected_columns(monkeypatch) -> None:
    _patch_managed_mode(monkeypatch, _managed_profile())

    now = datetime.now(timezone.utc)
    online_seen = now.isoformat().replace("+00:00", "Z")
    offline_seen = (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z")

    with respx.mock(assert_all_called=True) as mock:
        mock.get("https://managed.example/agents").mock(
            return_value=httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "11111111-2222-3333-4444-555555555555",
                            "name": "Desktop Alpha",
                            "agent_kind": "desktop",
                            "connected_at": "2026-04-23T10:00:00Z",
                            "last_seen": online_seen,
                        },
                        {
                            "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                            "name": "Build Server",
                            "agent_kind": "server",
                            "connected_at": "2026-04-20T10:00:00Z",
                            "last_seen": offline_seen,
                        },
                    ]
                },
            )
        )

        result = runner.invoke(app, ["--plain", "agent", "list"], env=_managed_env())

    assert result.exit_code == 0
    stdout = result.stdout
    assert "ID | Name | Kind | Connected At | Last Seen | Status" in stdout
    assert "Desktop Alpha" in stdout
    assert "Build Server" in stdout
    assert "online" in stdout
    assert "offline" in stdout
