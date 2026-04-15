import os
from google.cloud import secretmanager

PROJECT_ID = "matriosha"
_client = None


def get_client():
    global _client
    if _client is None:
        _client = secretmanager.SecretManagerServiceClient()
    return _client


def get_secret(secret_id, version_id="latest"):
    """
    Access the payload for the given secret version if one exists. The version
    can be a version number as a string (e.g. "5") or an alias name (e.g. "latest").
    """
    # Check local env first for development
    local_val = os.getenv(secret_id.upper().replace("-", "_"))
    if local_val:
        return local_val

    try:
        name = f"projects/{PROJECT_ID}/secrets/{secret_id}/versions/{version_id}"
        response = get_client().access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        print(f"Warning: Could not retrieve secret {secret_id} from GCP: {e}")
        return None
