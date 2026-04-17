"""
Matriosha — Secrets Manager

Loads secrets with fallback chain:
  1. Environment variables (.env in dev)
  2. Google Cloud Secret Manager (prod)

Usage:
    from core.secrets import get_secret, load_all_secrets

    url = get_secret("SUPABASE_URL")
    all_secrets = load_all_secrets()
"""

import os
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# GCP Project ID — env var override, fallback to "matriosha"
GCP_PROJECT = os.getenv("GCP_PROJECT", "matriosha")

# All secrets Matriosha needs
SECRET_KEYS = [
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "CLERK_SECRET_KEY",
    "CLERK_PUBLISHABLE_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_PRO_PRICE_ID",
    "PLATFORM_MASTER_KEY",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
]

# Singleton GCP client (avoid recreating on every call)
_gcp_client = None


def _get_gcp_client():
    """Get or create singleton GCP Secret Manager client."""
    global _gcp_client
    if _gcp_client is None:
        try:
            from google.cloud import secretmanager
            _gcp_client = secretmanager.SecretManagerServiceClient()
        except ImportError:
            logger.debug("google-cloud-secret-manager not installed")
            return None
    return _gcp_client


def _get_from_gcp(secret_id: str, project_id: str = GCP_PROJECT) -> Optional[str]:
    """Fetch a single secret from Google Cloud Secret Manager."""
    client = _get_gcp_client()
    if client is None:
        return None

    try:
        name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        logger.warning(f"GCP Secret Manager fetch failed for {secret_id}: {e}")
        return None


def get_secret(key: str) -> Optional[str]:
    """
    Get a secret value with fallback:
      1. Environment variable
      2. Google Cloud Secret Manager

    No caching — always fresh from source.
    """
    # 1. Check env var first (local dev / .env)
    val = os.getenv(key)
    if val:
        return val

    # 2. Try GCP Secret Manager
    val = _get_from_gcp(key)
    if val:
        return val

    logger.warning(f"Secret '{key}' not found in env or GCP (project: {GCP_PROJECT})")
    return None


def load_all_secrets() -> Dict[str, Optional[str]]:
    """Load all Matriosha secrets. Returns dict with None for missing keys."""
    return {key: get_secret(key) for key in SECRET_KEYS}


def require_secret(key: str) -> str:
    """Get a secret or raise if missing."""
    val = get_secret(key)
    if val is None:
        raise RuntimeError(
            f"Required secret '{key}' not found. "
            f"Set it as env var or in GCP Secret Manager (project: {GCP_PROJECT})"
        )
    return val


def check_secrets() -> Dict[str, bool]:
    """Check which secrets are available. Useful for health checks."""
    return {key: get_secret(key) is not None for key in SECRET_KEYS}
