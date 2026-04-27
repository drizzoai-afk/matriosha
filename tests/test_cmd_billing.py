from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from typer.testing import CliRunner

from matriosha.cli.commands import billing as billing_cmd
from matriosha.cli.main import app
from matriosha.core.config import MatrioshaConfig, Profile

runner = CliRunner()


@dataclass
class _FakeState:
    subscription_sequence: list[dict]
    checkout_payload: dict | None = None
    cancel_payload: dict | None = None
    start_calls: list[tuple[str, int]] | None = None


class FakeManagedClient:
    state = _FakeState(subscription_sequence=[])
    get_calls = 0

    def __init__(self, *, token: str, base_url: str | None = None, managed_mode: bool = True, **_: object):
        self.token = token
        self.base_url = base_url
        self.managed_mode = managed_mode

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def aclose(self):
        return None

    async def get_subscription(self) -> dict:
        seq = self.state.subscription_sequence
        if not seq:
            return {}
        idx = min(self.get_calls, len(seq) - 1)
        self.__class__.get_calls += 1
        return dict(seq[idx])

    async def start_checkout(self, plan: str = "eur_monthly", quantity: int = 1) -> dict:
        if self.state.start_calls is None:
            self.state.start_calls = []
        self.state.start_calls.append((plan, quantity))
        return dict(self.state.checkout_payload or {"checkout_url": "https://pay.example/checkout"})

    async def cancel_subscription(self) -> dict:
        return dict(
            self.state.cancel_payload
            or {
                "current_period_end": "2026-05-22T00:00:00Z",
                "status": "canceled",
            }
        )


def _managed_profile() -> Profile:
    return Profile(
        name="default",
        mode="managed",
        managed_endpoint="https://managed.example",
        created_at=datetime.now(timezone.utc),
    )


def _local_profile() -> Profile:
    return Profile(name="default", mode="local", created_at=datetime.now(timezone.utc))


def _patch_managed_profile(monkeypatch, profile: Profile) -> None:
    cfg = MatrioshaConfig(profiles={"default": profile}, active_profile="default")
    monkeypatch.setattr(billing_cmd, "load_config", lambda: cfg)
    monkeypatch.setattr(billing_cmd, "get_active_profile", lambda _cfg, _override: profile)


def _patch_managed_client(monkeypatch, state: _FakeState) -> None:
    FakeManagedClient.state = state
    FakeManagedClient.get_calls = 0
    monkeypatch.setattr(billing_cmd, "ManagedClient", FakeManagedClient)



@pytest.mark.parametrize("subscription_status", ["active", "trialing", "past_due", "canceled", "missing"])
def test_status_plain_outputs_subscription_status(subscription_status: str, monkeypatch) -> None:
    _patch_managed_profile(monkeypatch, _managed_profile())
    _patch_managed_client(
        monkeypatch,
        _FakeState(
            subscription_sequence=[
                {
                    "status": subscription_status,
                    "plan_code": "eur_monthly",
                    "current_period_end": "2026-05-22T00:00:00Z",
                    "agent_quota": 6,
                    "agent_in_use": 2,
                    "storage_cap_bytes": 6 * 1024**3,
                    "storage_used_bytes": 1024**3,
                    "quantity": 2,
                }
            ]
        ),
    )

    result = runner.invoke(
        app,
        ["--plain", "billing", "status"],
        env={"MATRIOSHA_MANAGED_TOKEN": "token-ok"},
    )

    assert result.exit_code == 0
    assert f"status: {subscription_status}" in result.stdout
    assert "agents" in result.stdout
    assert "storage" in result.stdout


def test_subscribe_default_and_custom_pack_count(monkeypatch) -> None:
    _patch_managed_profile(monkeypatch, _managed_profile())
    monkeypatch.setattr(billing_cmd, "SUBSCRIBE_POLL_SECONDS", 0)

    state_default = _FakeState(
        subscription_sequence=[
            {"status": "incomplete"},
            {
                "status": "active",
                "agent_quota": 3,
                "storage_cap_bytes": 3 * 1024**3,
                "quantity": 1,
            },
        ],
        checkout_payload={"checkout_url": "https://pay.example/default"},
        start_calls=[],
    )
    _patch_managed_client(monkeypatch, state_default)

    result_default = runner.invoke(
        app,
        ["--plain", "billing", "subscribe", "--agent-pack-count", "1"],
        env={
            "MATRIOSHA_MANAGED_TOKEN": "token-ok",
            "STRIPE_SECRET_KEY": "sk_test",
            "STRIPE_WEBHOOK_SECRET": "whsec_test",
            "SUPABASE_URL": "https://supabase.example",
            "SUPABASE_SERVICE_ROLE_KEY": "srv",
            "SUPABASE_ANON_KEY": "anon",
        },
    )
    assert result_default.exit_code == 0
    assert "Checkout URL: https://pay.example/default" in result_default.stdout
    assert "€9/month" in result_default.stdout
    assert state_default.start_calls == [("eur_monthly", 1)]

    state_custom = _FakeState(
        subscription_sequence=[
            {
                "status": "active",
                "agent_quota": 9,
                "storage_cap_bytes": 9 * 1024**3,
                "quantity": 3,
            }
        ],
        checkout_payload={"checkout_url": "https://pay.example/custom"},
        start_calls=[],
    )
    _patch_managed_client(monkeypatch, state_custom)

    result_custom = runner.invoke(
        app,
        ["--plain", "billing", "subscribe", "--agent-pack-count", "3"],
        env={
            "MATRIOSHA_MANAGED_TOKEN": "token-ok",
            "STRIPE_SECRET_KEY": "sk_test",
            "STRIPE_WEBHOOK_SECRET": "whsec_test",
            "SUPABASE_URL": "https://supabase.example",
            "SUPABASE_SERVICE_ROLE_KEY": "srv",
            "SUPABASE_ANON_KEY": "anon",
        },
    )
    assert result_custom.exit_code == 0
    assert "TypeError" not in result_custom.stdout
    assert "unexpected keyword argument" not in result_custom.stdout
    assert "€27/month" in result_custom.stdout
    assert "9.0 GB" in result_custom.stdout
    assert state_custom.start_calls == [("eur_monthly", 3)]


def test_upgrade_updates_stripe_quantity_and_shows_delta(monkeypatch) -> None:
    _patch_managed_profile(monkeypatch, _managed_profile())
    _patch_managed_client(
        monkeypatch,
        _FakeState(
            subscription_sequence=[
                {
                    "status": "active",
                    "agent_quota": 6,
                    "quantity": 2,
                    "stripe_subscription_id": "sub_123",
                }
            ]
        ),
    )

    with respx.mock(assert_all_called=True) as mock:
        get_route = mock.get("https://api.stripe.com/v1/subscriptions/sub_123").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "sub_123",
                    "items": {"data": [{"id": "si_123", "quantity": 2}]},
                },
            )
        )
        post_route = mock.post("https://api.stripe.com/v1/subscriptions/sub_123").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "sub_123",
                    "items": {"data": [{"id": "si_123", "quantity": 3}]},
                },
            )
        )

        result = runner.invoke(
            app,
            ["--plain", "billing", "upgrade"],
            env={
                "MATRIOSHA_MANAGED_TOKEN": "token-ok",
                "STRIPE_SECRET_KEY": "sk_test",
                "STRIPE_WEBHOOK_SECRET": "whsec_test",
                "SUPABASE_URL": "https://supabase.example",
                "SUPABASE_SERVICE_ROLE_KEY": "srv",
                "SUPABASE_ANON_KEY": "anon",
            },
        )

    assert result.exit_code == 0
    assert "+€9/month, +3 agents, +3 GB" in result.stdout
    assert get_route.called
    assert post_route.called
    sent = parse_qs(post_route.calls[0].request.content.decode("utf-8"))
    assert sent["items[0][quantity]"] == ["3"]


def test_subscribe_invalid_pack_count_exits_usage(monkeypatch) -> None:
    _patch_managed_profile(monkeypatch, _managed_profile())
    _patch_managed_client(monkeypatch, _FakeState(subscription_sequence=[{"status": "active"}], start_calls=[]))

    env = {
        "MATRIOSHA_MANAGED_TOKEN": "token-ok",
        "STRIPE_SECRET_KEY": "sk_test",
        "STRIPE_WEBHOOK_SECRET": "whsec_test",
        "SUPABASE_URL": "https://supabase.example",
        "SUPABASE_SERVICE_ROLE_KEY": "srv",
        "SUPABASE_ANON_KEY": "anon",
    }

    zero = runner.invoke(app, ["--plain", "billing", "subscribe", "--agent-pack-count", "0"], env=env)
    assert zero.exit_code == 2

    negative = runner.invoke(app, ["--plain", "billing", "subscribe", "--agent-pack-count", "-5"], env=env)
    assert negative.exit_code == 2

    non_int = runner.invoke(app, ["--plain", "billing", "subscribe", "--agent-pack-count", "abc"], env=env)
    assert non_int.exit_code == 2


def test_cancel_requires_yes(monkeypatch) -> None:
    _patch_managed_profile(monkeypatch, _managed_profile())
    _patch_managed_client(monkeypatch, _FakeState(subscription_sequence=[{"status": "active"}]))

    result = runner.invoke(
        app,
        ["--plain", "billing", "cancel"],
        env={"MATRIOSHA_MANAGED_TOKEN": "token-ok"},
    )

    assert result.exit_code == 2
    assert "--yes" in result.stdout


def test_billing_local_mode_guard_exits_30(monkeypatch) -> None:
    _patch_managed_profile(monkeypatch, _local_profile())

    result = runner.invoke(app, ["--plain", "billing", "status"], env={"MATRIOSHA_MANAGED_TOKEN": "token-ok"})
    assert result.exit_code == 30


def test_subscribe_timeout(monkeypatch) -> None:
    _patch_managed_profile(monkeypatch, _managed_profile())
    _patch_managed_client(
        monkeypatch,
        _FakeState(subscription_sequence=[{"status": "incomplete"}], checkout_payload={"checkout_url": "https://pay.example"}),
    )
    monkeypatch.setattr(billing_cmd, "SUBSCRIBE_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(billing_cmd, "SUBSCRIBE_POLL_SECONDS", 1)

    result = runner.invoke(
        app,
        ["--plain", "billing", "subscribe", "--agent-pack-count", "1"],
        env={
            "MATRIOSHA_MANAGED_TOKEN": "token-ok",
            "STRIPE_SECRET_KEY": "sk_test",
            "STRIPE_WEBHOOK_SECRET": "whsec_test",
            "SUPABASE_URL": "https://supabase.example",
            "SUPABASE_SERVICE_ROLE_KEY": "srv",
            "SUPABASE_ANON_KEY": "anon",
        },
    )

    assert result.exit_code == 40
    assert "timed out" in result.stdout.lower()


def test_cancel_success_message(monkeypatch) -> None:
    _patch_managed_profile(monkeypatch, _managed_profile())
    _patch_managed_client(
        monkeypatch,
        _FakeState(
            subscription_sequence=[{"status": "active"}],
            cancel_payload={"current_period_end": "2026-06-10T00:00:00Z", "status": "canceled"},
        ),
    )

    result = runner.invoke(
        app,
        ["--plain", "billing", "cancel", "--yes"],
        env={"MATRIOSHA_MANAGED_TOKEN": "token-ok"},
    )

    assert result.exit_code == 0
    assert "Subscription canceled, access until 2026-06-10" in result.stdout
