"""Secret loading helpers with optional Google Secret Manager support."""

from __future__ import annotations

import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)

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
    """Read-only adapter for Google Secret Manager."""

    def __init__(self, project_id: str | None = None):
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID")
        self.credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self.client: SecretManagerServiceClient | None = None

        # Local-mode friendly behavior: silently disable GSM when required env is absent.
        # Managed-mode callers must enforce required secret presence separately.
        if not self.project_id or not self.credentials_path or not _GSM_AVAILABLE:
            return

        try:
            self.client = SecretManagerServiceClient()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Google Secret Manager client initialization failed")
            raise SecretManagerError(
                "Unable to initialize Google Secret Manager client. "
                "Check GCP_PROJECT_ID, GOOGLE_APPLICATION_CREDENTIALS, and IAM permissions."
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


@lru_cache(maxsize=1)
def _secret_manager() -> SecretManager:
    return SecretManager()


def get_secret(secret_name: str, *, default: str | None = None) -> str | None:
    """Resolve secret by lookup order: env -> GSM -> default."""

    env_value = os.getenv(secret_name)
    if env_value:
        return env_value

    try:
        gsm_value = _secret_manager().get_secret(secret_name)
    except SecretManagerError:
        logger.warning("Secret lookup via GSM unavailable for secret: %s", secret_name)
        gsm_value = None

    if gsm_value:
        return gsm_value

    return default
