"""Managed backup helpers for semantic-recall corruption recovery.

Backup object key contract: <memory_id>.bin.b64.backup in Supabase bucket `vault`.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.managed.secrets import get_supabase_credentials

try:
    from supabase import create_client
except Exception:  # noqa: BLE001
    create_client = None


class ManagedBackupError(RuntimeError):
    """Raised for managed backup upload/download failures."""


@dataclass(frozen=True)
class ManagedBackupStore:
    """Supabase Storage backup copy manager for managed mode."""

    bucket: str = "vault"

    def _client(self):
        if create_client is None:
            raise ManagedBackupError("supabase dependency not available")

        creds = get_supabase_credentials(allow_env_fallback=True)
        if not creds.url or not creds.service_role_key:
            raise ManagedBackupError("missing SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY")
        return create_client(creds.url, creds.service_role_key)

    @staticmethod
    def backup_key(memory_id: str) -> str:
        return f"{memory_id}.bin.b64.backup"

    def upload_backup(self, memory_id: str, payload_b64: bytes) -> str:
        client = self._client()
        key = self.backup_key(memory_id)
        try:
            client.storage.from_(self.bucket).upload(
                key,
                payload_b64,
                {"upsert": True, "content-type": "application/octet-stream"},
            )
            return key
        except Exception as exc:  # noqa: BLE001
            raise ManagedBackupError(f"backup upload failed for {memory_id}: {exc}") from exc

    def download_backup(self, memory_id: str) -> bytes:
        client = self._client()
        key = self.backup_key(memory_id)
        try:
            data = client.storage.from_(self.bucket).download(key)
            if not isinstance(data, (bytes, bytearray)):
                raise ManagedBackupError("backup payload response is not bytes")
            return bytes(data)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, ManagedBackupError):
                raise
            raise ManagedBackupError(f"backup download failed for {memory_id}: {exc}") from exc
