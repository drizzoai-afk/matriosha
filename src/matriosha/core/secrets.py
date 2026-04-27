"""Secret loading helpers with optional Google Secret Manager support."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

try:
    from google.api_core.exceptions import GoogleAPICallError, NotFound, PermissionDenied
    from google.cloud.secretmanager import SecretManagerServiceClient

    _GSM_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    GoogleAPICallError = Exception  # type: ignore[assignment,misc]
    NotFound = Exception  # type: ignore[assignment,misc]
    PermissionDenied = Exception  # type: ignore[assignment,misc]
    SecretManagerServiceClient = None  # type: ignore[assignment,misc]
    _GSM_AVAILABLE = False


class SecretManagerError(RuntimeError):
    """Raised for non-recoverable Secret Manager setup/runtime failures."""


class SecretManager:
    """Read-only adapter for Google Secret Manager."""

    def __init__(self, project_id: str | None = None, *, fail_fast: bool = False):
        self.project_id = project_id or os.getenv("GCP_PROJECT_ID")
        self.client: Any | None = None

        if not self.project_id:
            if fail_fast:
                raise SecretManagerError(
                    "GCP_PROJECT_ID is not configured. Set GCP_PROJECT_ID or pass project_id explicitly "
                    "to use Google Secret Manager."
                )
            return

        if not _GSM_AVAILABLE:
            return

        try:
            self.client = SecretManagerServiceClient()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Google Secret Manager client initialization failed")
            if fail_fast:
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
        except Exception:  # noqa: BLE001
            logger.warning("Unexpected Google Secret Manager failure for secret: %s", secret_name)
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


def require_secret(secret_name: str) -> str:
    """Resolve secret and raise actionable error when missing."""

    value = get_secret(secret_name)
    if value:
        return value
    raise SecretManagerError(
        f"Missing required secret '{secret_name}'. Set env var, configure GSM, or provide runtime secret."
    )
