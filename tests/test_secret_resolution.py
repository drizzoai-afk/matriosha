from __future__ import annotations

import pytest

from matriosha.core import secrets as core_secrets
from matriosha.core.managed import secrets as managed_secrets


class DummyPayload:
    def __init__(self, value: str) -> None:
        self.data = value.encode("utf-8")


class DummyResponse:
    def __init__(self, value: str) -> None:
        self.payload = DummyPayload(value)


class DummyGsmClient:
    def __init__(self, values: dict[str, str] | None = None, exc: Exception | None = None) -> None:
        self.values = values or {}
        self.exc = exc
        self.requests: list[dict[str, str]] = []

    def access_secret_version(self, *, request: dict[str, str]) -> DummyResponse:
        self.requests.append(request)
        if self.exc:
            raise self.exc
        name = request["name"].split("/secrets/", 1)[1].split("/versions/", 1)[0]
        return DummyResponse(self.values[name])


def _clear_project_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCLOUD_PROJECT", raising=False)


def test_secret_manager_google_cloud_project_alias_is_safe_when_gsm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_project_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "alias-project")
    monkeypatch.setattr(core_secrets, "_GSM_AVAILABLE", False)

    manager = core_secrets.SecretManager()

    assert manager.project_id in {None, "alias-project"}
    assert manager.client is None


def test_secret_manager_reads_secret_from_gsm_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_project_env(monkeypatch)
    monkeypatch.setattr(core_secrets, "_GSM_AVAILABLE", True)
    client = DummyGsmClient({"SUPABASE_JWT_SECRET": "jwt-from-gsm"})
    monkeypatch.setattr(core_secrets, "SecretManagerServiceClient", lambda: client)

    manager = core_secrets.SecretManager(project_id="prod-project")

    assert manager.get_secret("SUPABASE_JWT_SECRET") == "jwt-from-gsm"
    assert client.requests == [
        {
            "name": "projects/prod-project/secrets/SUPABASE_JWT_SECRET/versions/latest",
        }
    ]


def test_get_secret_prefers_env_then_default(monkeypatch: pytest.MonkeyPatch) -> None:
    core_secrets._secret_manager.cache_clear()
    monkeypatch.setenv("EXAMPLE_SECRET", "from-env")

    assert core_secrets.get_secret("EXAMPLE_SECRET", default="fallback") == "from-env"

    monkeypatch.delenv("EXAMPLE_SECRET", raising=False)
    monkeypatch.setattr(core_secrets, "_secret_manager", lambda: core_secrets.SecretManager())

    assert core_secrets.get_secret("EXAMPLE_SECRET", default="fallback") == "fallback"


def test_require_secret_raises_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_REQUIRED_SECRET", raising=False)
    monkeypatch.setattr(core_secrets, "_secret_manager", lambda: core_secrets.SecretManager())

    with pytest.raises(core_secrets.SecretManagerError, match="MISSING_REQUIRED_SECRET"):
        core_secrets.require_secret("MISSING_REQUIRED_SECRET")


def test_managed_runtime_secrets_prefers_gsm_over_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed_secrets.clear_secret_cache()
    monkeypatch.setenv("SUPABASE_URL", "env-url")

    class DummySecretManager:
        def __init__(self, project_id: str | None = None) -> None:
            self.project_id = project_id

        def get_secret(self, name: str) -> str | None:
            return {"SUPABASE_URL": "gsm-url"}.get(name)

    monkeypatch.setattr(managed_secrets, "SecretManager", DummySecretManager)

    resolved = managed_secrets.load_runtime_secrets(
        ["SUPABASE_URL"], project_id="prod-project", force_refresh=True
    )

    assert resolved.get("SUPABASE_URL").value == "gsm-url"
    assert resolved.get("SUPABASE_URL").source == "gsm"


def test_managed_runtime_secrets_can_disable_env_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed_secrets.clear_secret_cache()
    monkeypatch.setenv("STRIPE_SECRET_KEY", "env-stripe-secret")

    class EmptySecretManager:
        def __init__(self, project_id: str | None = None) -> None:
            self.project_id = project_id

        def get_secret(self, name: str) -> None:
            return None

    monkeypatch.setattr(managed_secrets, "SecretManager", EmptySecretManager)

    resolved = managed_secrets.load_runtime_secrets(
        ["STRIPE_SECRET_KEY"], allow_env_fallback=False, force_refresh=True
    )

    assert resolved.get("STRIPE_SECRET_KEY").value == ""
    assert resolved.get("STRIPE_SECRET_KEY").source == "missing"


def test_managed_required_secret_and_credential_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed_secrets.clear_secret_cache()
    values = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role",
        "SUPABASE_ANON_KEY": "anon",
        "SUPABASE_JWT_SECRET": "jwt",
        "SUPABASE_PASSWORD": "password",
        "STRIPE_SECRET_KEY": "stripe-secret",
        "STRIPE_WEBHOOK_SECRET": "stripe-webhook",
        "STRIPE_PUBLISHABLE_KEY": "stripe-publishable",
    }

    for name, value in values.items():
        monkeypatch.setenv(name, value)

    supabase = (
        managed_secrets.get_supabase_credentials(force_refresh=True)
        if False
        else managed_secrets.get_supabase_credentials()
    )
    stripe = managed_secrets.get_stripe_credentials()

    assert supabase.url == values["SUPABASE_URL"]
    assert supabase.service_role_key == values["SUPABASE_SERVICE_ROLE_KEY"]
    assert supabase.anon_key == values["SUPABASE_ANON_KEY"]
    assert supabase.jwt_secret == values["SUPABASE_JWT_SECRET"]
    assert supabase.password == values["SUPABASE_PASSWORD"]
    assert stripe.secret_key == values["STRIPE_SECRET_KEY"]
    assert stripe.webhook_secret == values["STRIPE_WEBHOOK_SECRET"]
    assert stripe.publishable_key == values["STRIPE_PUBLISHABLE_KEY"]
    assert managed_secrets.get_required_secret("SUPABASE_URL") == values["SUPABASE_URL"]


def test_managed_required_secret_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    managed_secrets.clear_secret_cache()
    monkeypatch.delenv("MISSING_MANAGED_SECRET", raising=False)

    class EmptySecretManager:
        def __init__(self, project_id: str | None = None) -> None:
            self.project_id = project_id

        def get_secret(self, name: str) -> None:
            return None

    monkeypatch.setattr(managed_secrets, "SecretManager", EmptySecretManager)

    with pytest.raises(managed_secrets.ManagedSecretError, match="MISSING_MANAGED_SECRET"):
        managed_secrets.get_required_secret("MISSING_MANAGED_SECRET")
