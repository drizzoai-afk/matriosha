"""Secret loading helpers with optional Google Secret Manager support."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

SAFE_LOCAL_FALLBACKS: dict[str, str] = {
    "SUPABASE_URL": "http://127.0.0.1:54321",
    "SUPABASE_SERVICE_ROLE_KEY": "local-service-role",
    "SUPABASE_ANON_KEY": "local-anon-key",
    "STRIPE_SECRET_KEY": "local-stripe-secret",
    "STRIPE_WEBHOOK_SECRET": "local-stripe-webhook",
}

try:
    from google.api_core.exceptions import GoogleAPICallError, NotFound, PermissionDenied
    from google.cloud.secretmanager import SecretManagerServiceClient

    _GSM_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    GoogleAPICallError = Exception  # type: ignore[assignment]
    NotFound = Exception  # type: ignore[assignment]
    PermissionDenied = Exception  # type: ignore[assignment]
    SecretManagerServiceClient = None  # type: ignore[assignment]
    _GSM_AVAILABLE = False


class SecretManagerError(RuntimeError):
    """Raised for non-recoverable Secret Manager setup/runtime failures."""


class SecretManager:
    """Read-only adapter for Google Secret Manager.

    Lookup order is intentionally not implemented here; callers should use `get_secret`
    for env -> GSM -> safe fallback behavior.
    """

    def __init__(self, project_id: str | None = None):
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID")
        self.credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self.client: SecretManagerServiceClient | None = None

        if not self.project_id:
            return

        if not _GSM_AVAILABLE:
            logger.warning("Google Secret Manager client unavailable.")
            return

        try:
            self.client = SecretManagerServiceClient()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Google Secret Manager client initialization failed.")
            if self.credentials_path:
                raise SecretManagerError(
                    "Unable to initialize Google Secret Manager client. "
                    "Check GOOGLE_APPLICATION_CREDENTIALS and IAM permissions."
                ) from exc

    def get_secret(self, secret_name: str, version: str = "latest") -> str | None:
        if not self.client or not self.project_id:
            return None

        resource = f"projects/{self.project_id}/secrets/{secret_name}/versions/{version}"
        try:
            response = self.client.access_secret_version(request={"name": resource})
            return response.payload.data.decode("utf-8")
        except NotFound:
            logger.warning("Secret not found in Google Secret Manager: %s", secret_name)
            return None
        except PermissionDenied:
            logger.warning("Permission denied reading secret from Google Secret Manager: %s", secret_name)
            return None
        except GoogleAPICallError:
            logger.warning("Google Secret Manager API call failed for secret: %s", secret_name)
            return None


def get_secret(secret_name: str, *, default: str | None = None) -> str | None:
    """Resolve secret by lookup order: env -> GSM -> safe local fallback/default.

    The optional `default` argument takes precedence over built-in fallback values.
    """

    env_value = os.getenv(secret_name)
    if env_value:
        return env_value

    gsm_value = SecretManager().get_secret(secret_name)
    if gsm_value:
        return gsm_value

    if default is not None:
        return default

    return SAFE_LOCAL_FALLBACKS.get(secret_name)
