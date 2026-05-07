from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import pytest
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
    upgrade_payload: dict | None = None
    start_calls: list[tuple[str, int]] | None = None
    upgrade_calls: list[int] | None = None


class FakeManagedClient:
    state = _FakeState(subscription_sequence=[])
    get_calls = 0

    def __init__(
        self, *, token: str, base_url: str | None = None, managed_mode: bool = True, **_: object
    ):
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

    async def upgrade_subscription(self, quantity: int) -> dict:
        if self.state.upgrade_calls is None:
            self.state.upgrade_calls = []
        self.state.upgrade_calls.append(quantity)
        if self.state.upgrade_payload is not None:
            return dict(self.state.upgrade_payload)
        return {
            "status": "active",
            "agent_quota": quantity * 3,
            "storage_cap_bytes": quantity * 3 * 1024**3,
            "quantity": quantity,
        }


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


@pytest.mark.parametrize(
    "subscription_status", ["active", "trialing", "past_due", "canceled", "missing"]
)
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
    assert "SUBSCRIPTION ALREADY ACTIVE" in result_custom.stdout
    assert "€27/month" in result_custom.stdout
    assert "9.0 GB" in result_custom.stdout
    assert "Checkout URL:" not in result_custom.stdout
    assert state_custom.start_calls == []


def test_upgrade_uses_managed_backend_and_shows_delta(monkeypatch) -> None:
    _patch_managed_profile(monkeypatch, _managed_profile())
    state = _FakeState(
        subscription_sequence=[
            {
                "status": "active",
                "agent_quota": 6,
                "storage_cap_bytes": 6 * 1024**3,
                "quantity": 2,
            },
        ],
        upgrade_calls=[],
        upgrade_payload={
            "status": "active",
            "agent_quota": 9,
            "storage_cap_bytes": 9 * 1024**3,
            "quantity": 3,
        },
    )
    _patch_managed_client(monkeypatch, state)

    result = runner.invoke(
        app,
        ["--plain", "billing", "upgrade", "--yes"],
        env={"MATRIOSHA_MANAGED_TOKEN": "token-ok"},
    )

    assert result.exit_code == 0
    assert "+€9/month, +3 agents, +3 GB" in result.stdout
    assert state.upgrade_calls == [3]


def test_upgrade_reports_backend_reactivation(monkeypatch) -> None:
    _patch_managed_profile(monkeypatch, _managed_profile())
    state = _FakeState(
        subscription_sequence=[
            {
                "status": "active",
                "agent_quota": 3,
                "storage_cap_bytes": 3 * 1024**3,
                "quantity": 1,
                "cancel_at_period_end": True,
            },
        ],
        upgrade_calls=[],
        upgrade_payload={
            "subscription": {
                "status": "active",
                "agent_quota": 6,
                "storage_cap_bytes": 6 * 1024**3,
                "quantity": 2,
                "cancel_at_period_end": False,
            },
            "reactivated": True,
        },
    )
    _patch_managed_client(monkeypatch, state)

    result = runner.invoke(
        app,
        ["--plain", "billing", "upgrade", "--yes"],
        env={"MATRIOSHA_MANAGED_TOKEN": "token-ok"},
    )

    assert result.exit_code == 0
    assert "reactivated" in result.stdout
    assert "yes" in result.stdout
    assert state.upgrade_calls == [2]


def test_upgrade_does_not_require_local_stripe_secrets(monkeypatch) -> None:
    _patch_managed_profile(monkeypatch, _managed_profile())
    state = _FakeState(
        subscription_sequence=[
            {
                "status": "active",
                "agent_quota": 3,
                "storage_cap_bytes": 3 * 1024**3,
                "quantity": 1,
            },
        ],
        upgrade_calls=[],
    )
    _patch_managed_client(monkeypatch, state)
    monkeypatch.setattr(
        billing_cmd.common,
        "get_stripe_credentials",
        lambda *, allow_env_fallback=True: type(
            "StripeCredentialsStub",
            (),
            {"secret_key": "", "webhook_secret": "", "publishable_key": ""},
        )(),
    )

    result = runner.invoke(
        app,
        ["--json", "billing", "upgrade", "--yes"],
        env={"MATRIOSHA_MANAGED_TOKEN": "token-ok"},
    )

    assert result.exit_code == 0
    assert "Stripe billing credentials are missing" not in result.stdout
    assert state.upgrade_calls == [2]


def test_subscribe_invalid_pack_count_exits_usage(monkeypatch) -> None:
    _patch_managed_profile(monkeypatch, _managed_profile())
    _patch_managed_client(
        monkeypatch, _FakeState(subscription_sequence=[{"status": "active"}], start_calls=[])
    )

    env = {
        "MATRIOSHA_MANAGED_TOKEN": "token-ok",
        "STRIPE_SECRET_KEY": "sk_test",
        "STRIPE_WEBHOOK_SECRET": "whsec_test",
        "SUPABASE_URL": "https://supabase.example",
        "SUPABASE_SERVICE_ROLE_KEY": "srv",
        "SUPABASE_ANON_KEY": "anon",
    }

    zero = runner.invoke(
        app, ["--plain", "billing", "subscribe", "--agent-pack-count", "0"], env=env
    )
    assert zero.exit_code == 2

    negative = runner.invoke(
        app, ["--plain", "billing", "subscribe", "--agent-pack-count", "-5"], env=env
    )
    assert negative.exit_code == 2

    non_int = runner.invoke(
        app, ["--plain", "billing", "subscribe", "--agent-pack-count", "abc"], env=env
    )
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


def test_upgrade_requires_yes(monkeypatch) -> None:
    _patch_managed_profile(monkeypatch, _managed_profile())
    state = _FakeState(
        subscription_sequence=[
            {
                "status": "active",
                "agent_quota": 3,
                "storage_cap_bytes": 3 * 1024**3,
                "quantity": 1,
            },
        ],
        upgrade_calls=[],
    )
    _patch_managed_client(monkeypatch, state)

    result = runner.invoke(
        app,
        ["--plain", "billing", "upgrade"],
        env={"MATRIOSHA_MANAGED_TOKEN": "token-ok"},
    )

    assert result.exit_code == 2
    assert "--yes" in result.stdout
    assert state.upgrade_calls == []


def test_billing_local_mode_guard_exits_30(monkeypatch) -> None:
    _patch_managed_profile(monkeypatch, _local_profile())

    result = runner.invoke(
        app, ["--plain", "billing", "status"], env={"MATRIOSHA_MANAGED_TOKEN": "token-ok"}
    )
    assert result.exit_code == 30


def test_subscribe_timeout(monkeypatch) -> None:
    _patch_managed_profile(monkeypatch, _managed_profile())
    _patch_managed_client(
        monkeypatch,
        _FakeState(
            subscription_sequence=[{"status": "incomplete"}],
            checkout_payload={"checkout_url": "https://pay.example"},
        ),
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


def test_billing_common_formatting_and_pack_parsing() -> None:
    common = billing_cmd.common

    assert common._format_bytes(None) == "0B"
    assert common._format_bytes("bad") == "0B"
    assert common._format_bytes(512) == "512B"
    assert common._format_bytes(2048) == "2.00KiB"
    assert common._format_bytes(2 * 1024**2) == "2.00MiB"
    assert common._format_bytes(2 * 1024**3) == "2.00GiB"

    assert common._bytes_to_gb_text(None) == "n/a"
    assert common._bytes_to_gb_text(3 * 1024**3) == "3.0 GB"

    assert common._safe_int("7") == 7
    assert common._safe_int("nope", 42) == 42
    assert common._safe_int(None, 9) == 9

    assert common._parse_pack_count({"agent_pack_count": "4"}) == 4
    assert common._parse_pack_count({"agent_pack_count": "0"}) == 1
    assert common._parse_pack_count({"quantity": "3"}) == 3
    assert common._parse_pack_count({"agent_quota": 9}) == 3
    assert common._parse_pack_count({}) == 1

    assert common._format_date(None) == "n/a"
    assert common._format_date("2026-05-22T00:00:00Z") == "2026-05-22"
    assert common._format_date("2026-05-22") == "2026-05-22"
    assert common._format_date(1_771_632_000) == "2026-02-21"


def test_billing_status_rows_are_derived_from_subscription() -> None:
    rows = dict(
        billing_cmd.common._status_rows(
            {
                "plan_code": "eur_monthly",
                "status": "active",
                "quantity": 2,
                "current_period_end": "2026-06-10T00:00:00Z",
                "agent_quota": 6,
                "agent_in_use": 2,
                "storage_cap_bytes": 6 * 1024**3,
                "storage_used_bytes": 1024**3,
            }
        )
    )

    assert rows["plan"] == "eur_monthly"
    assert rows["status"] == "active"
    assert rows["monthly"] == "€18/month (2 packs × €9)"
    assert rows["dates"] == "period_end=2026-06-10"
    assert rows["agents"] == "6 total / 2 in use"
    assert rows["storage"] == "6.00GiB cap / 1.00GiB used"


def test_parse_checkout_url_accepts_supported_keys_and_rejects_missing() -> None:
    common = billing_cmd.common

    assert (
        common._parse_checkout_url({"checkout_url": "https://pay.example/a"})
        == "https://pay.example/a"
    )
    assert common._parse_checkout_url({"url": "https://pay.example/b"}) == "https://pay.example/b"
    assert (
        common._parse_checkout_url({"checkoutUrl": "https://pay.example/c"})
        == "https://pay.example/c"
    )

    with pytest.raises(common.BillingError) as exc:
        common._parse_checkout_url({"url": ""})

    assert exc.value.code == "PAY-002"
    assert exc.value.exit_code != 0


def test_extract_stripe_ids_from_flat_and_nested_payloads() -> None:
    common = billing_cmd.common

    assert common._extract_stripe_ids(
        {
            "stripe_subscription_id": "sub_123",
            "stripe_subscription_item_id": "si_123",
        }
    ) == ("sub_123", "si_123")

    assert common._extract_stripe_ids(
        {
            "stripe": {
                "subscription_id": "sub_nested",
                "subscription_item_id": "si_nested",
            }
        }
    ) == ("sub_nested", "si_nested")

    assert common._extract_stripe_ids({"stripe_subscription_id": "sub_only"}) == (
        "sub_only",
        None,
    )

    with pytest.raises(common.BillingError) as exc:
        common._extract_stripe_ids({})

    assert exc.value.code == "PAY-020"


def test_resolve_billing_secrets_allows_optional_webhook(monkeypatch) -> None:
    common = billing_cmd.common

    monkeypatch.setattr(
        common,
        "get_stripe_credentials",
        lambda *, allow_env_fallback=True: type(
            "StripeCredentialsStub",
            (),
            {"secret_key": "sk_live_x", "webhook_secret": "", "publishable_key": "pk_live_x"},
        )(),
    )
    monkeypatch.setattr(
        common,
        "get_supabase_credentials",
        lambda *, allow_env_fallback=True: type(
            "SupabaseCredentialsStub",
            (),
            {
                "url": "https://supabase.example",
                "service_role_key": "srv",
                "anon_key": "anon",
            },
        )(),
    )

    secrets = common._resolve_billing_secrets(
        json_output=False, plain=True, require_webhook_secret=False
    )

    assert secrets["STRIPE_SECRET_KEY"] == "sk_live_x"
    assert secrets["STRIPE_WEBHOOK_SECRET"] == ""
    assert secrets["SUPABASE_SERVICE_ROLE_KEY"] == "srv"


def test_resolve_billing_secrets_emits_json_error_when_required_missing(
    monkeypatch, capsys
) -> None:
    common = billing_cmd.common

    monkeypatch.setattr(
        common,
        "get_stripe_credentials",
        lambda *, allow_env_fallback=True: type(
            "StripeCredentialsStub",
            (),
            {"secret_key": "", "webhook_secret": "", "publishable_key": ""},
        )(),
    )
    monkeypatch.setattr(
        common,
        "get_supabase_credentials",
        lambda *, allow_env_fallback=True: type(
            "SupabaseCredentialsStub",
            (),
            {"url": "", "service_role_key": "", "anon_key": ""},
        )(),
    )

    with pytest.raises(Exception) as exc:
        common._resolve_billing_secrets(json_output=True, plain=False)

    assert getattr(exc.value, "exit_code", None) == 99
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["code"] == "PAY-001"
    assert "STRIPE_SECRET_KEY" in payload["debug"]


def test_poll_subscription_until_active_terminal_state(monkeypatch) -> None:
    common = billing_cmd.common

    async def fake_get_subscription(token: str, endpoint: str | None) -> dict:
        return {"status": "unpaid"}

    monkeypatch.setattr(common, "_get_subscription", fake_get_subscription)

    with pytest.raises(common.BillingError) as exc:
        common._poll_subscription_until_active(
            "token",
            "https://managed.example",
            timeout_seconds=1,
            poll_seconds=0,
            show_progress=False,
        )

    assert exc.value.code == "PAY-004"
    assert "subscription_status=unpaid" in exc.value.debug


def test_poll_subscription_until_quota_success_and_timeout(monkeypatch) -> None:
    common = billing_cmd.common
    calls = {"count": 0}

    async def fake_get_subscription_success(token: str, endpoint: str | None) -> dict:
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "agent_quota": 3,
                "storage_cap_bytes": 3 * 1024**3,
                "cancel_at_period_end": False,
            }
        return {
            "agent_quota": 6,
            "storage_cap_bytes": 6 * 1024**3,
            "cancel_at_period_end": False,
        }

    monkeypatch.setattr(common, "_get_subscription", fake_get_subscription_success)

    subscription = common._poll_subscription_until_quota(
        "token",
        "https://managed.example",
        target_packs=2,
        timeout_seconds=1,
        poll_seconds=0,
    )

    assert subscription["agent_quota"] == 6
    assert calls["count"] == 2

    async def fake_get_subscription_timeout(token: str, endpoint: str | None) -> dict:
        return {
            "agent_quota": 3,
            "storage_cap_bytes": 3 * 1024**3,
            "cancel_at_period_end": True,
        }

    monkeypatch.setattr(common, "_get_subscription", fake_get_subscription_timeout)

    with pytest.raises(common.BillingError) as exc:
        common._poll_subscription_until_quota(
            "token",
            "https://managed.example",
            target_packs=2,
            timeout_seconds=0,
            poll_seconds=0,
        )

    assert exc.value.code == "PAY-027"
    assert "target_agents=6" in exc.value.debug
