"""Local-only agent token storage."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import platformdirs


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _store_path(profile_name: str) -> Path:
    return Path(platformdirs.user_data_dir("matriosha")) / profile_name / "local_agent_tokens.json"


def _read_tokens(profile_name: str) -> list[dict[str, Any]]:
    path = _store_path(profile_name)
    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if not isinstance(payload, list):
        return []

    return [item for item in payload if isinstance(item, dict)]


def _write_tokens(profile_name: str, tokens: list[dict[str, Any]]) -> None:
    path = _store_path(profile_name)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    tmp_path.write_text(json.dumps(tokens, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if os.name != "nt":
        os.chmod(tmp_path, 0o600)

    tmp_path.replace(path)

    if os.name != "nt":
        os.chmod(path, 0o600)


def create_local_agent_token(
    *,
    profile_name: str,
    name: str,
    scope: str,
    expires_at: str | None,
) -> dict[str, Any]:
    """Create and persist a local-only agent token, returning plaintext once."""

    token = f"mtl_{secrets.token_urlsafe(32)}"
    token_id = str(uuid.uuid4())
    created_at = _now_iso()

    record = {
        "id": token_id,
        "name": name,
        "scope": scope,
        "created_at": created_at,
        "last_used": None,
        "expires_at": expires_at,
        "revoked": False,
        "token_hash": _token_hash(token),
    }

    tokens = _read_tokens(profile_name)
    tokens.append(record)
    _write_tokens(profile_name, tokens)

    return {
        "id": token_id,
        "token": token,
        "name": name,
        "scope": scope,
        "created_at": created_at,
        "expires_at": expires_at,
    }
