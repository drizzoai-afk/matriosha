"""Secret loading helpers with optional Google Secret Manager support."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

try:
    from google.api_core.exceptions import GoogleAPICallError, NotFound, PermissionDenied
    from google.cloud import secretmanager

    _GSM_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on optional dependency
    GoogleAPICallError = Exception  # type: ignore[assignment]
    NotFound = Exception  # type: ignore[assignment]
    PermissionDenied = Exception  # type: ignore[assignment]
    secretmanager = None  # type: ignore[assignment]
    _GSM_AVAILABLE = False


class SecretManagerError(RuntimeError):
    """Raised for non-recoverable Secret Manager setup/runtime failures."""


class SecretManager:
    def __init__(self, project_id: str | None = None):
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID")
        self.credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self.client = None

        if not self.project_id:
            return

        if not _GSM_AVAILABLE:
            logger.warning(
                "Google Secret Manager client unavailable; install optional cloud dependencies."
            )
            return

        try:
            self.client = secretmanager.SecretManagerServiceClient()
        except Exception:
            logger.warning("Google Secret Manager client initialization failed.")
            self.client = None

    def get_secret(self, secret_name: str, version: str = "latest") -> str | None:
        if not self.client or not self.project_id:
            return None

        name = f"projects/{self.project_id}/secrets/{secret_name}/versions/{version}"
        try:
            response = self.client.access_secret_version(request={"name": name})
            return response.payload.data.decode("utf-8")
        except (NotFound, PermissionDenied, GoogleAPICallError):
            logger.warning("Unable to read secret from Google Secret Manager.")
            return None


def get_secret(secret_name: str, *, default: str | None = None) -> str | None:
    """Resolve secret from env override, then GSM, then provided default."""

    return os.getenv(secret_name) or SecretManager().get_secret(secret_name) or default
