"""Local-only agent token storage and validation."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import platformdirs


class LocalTokenError(RuntimeError):
    """Raised when a local agent token cannot be used."""

    def __init__(self, message: str, *, code: str, debug: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.debug = debug


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_SCOPE_RANK = {
    "read": 1,
    "write": 2,
    "admin": 3,
}


def _scope_allows(scope: str, required_scope: str | None) -> bool:
    """Return whether a local token scope satisfies the required scope."""

    if not required_scope:
        return True

    return _SCOPE_RANK.get(scope, 0) >= _SCOPE_RANK.get(required_scope, 0)


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


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(record.get("id") or ""),
        "name": str(record.get("name") or ""),
        "scope": str(record.get("scope") or ""),
        "created_at": record.get("created_at"),
        "last_used": record.get("last_used"),
        "expires_at": record.get("expires_at"),
        "revoked": bool(record.get("revoked", False)),
    }


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


def list_local_agent_tokens(profile_name: str) -> list[dict[str, Any]]:
    """Return local token metadata without plaintext or hashes."""

    return [_public_record(record) for record in _read_tokens(profile_name)]
def revoke_local_agent_token(profile_name: str, token_id: str) -> bool:
    """Mark a local token as revoked by full id or unique prefix."""

    needle = token_id.strip()
    tokens = _read_tokens(profile_name)

    direct_matches = [index for index, record in enumerate(tokens) if str(record.get("id") or "") == needle]
    prefix_matches = [index for index, record in enumerate(tokens) if str(record.get("id") or "").startswith(needle)]
    matches = direct_matches or prefix_matches

    if len(matches) != 1:
        return False

    index = matches[0]
    updated = dict(tokens[index])
    if bool(updated.get("revoked", False)):
        return True

    updated["revoked"] = True
    tokens[index] = updated
    _write_tokens(profile_name, tokens)
    return True

def verify_local_agent_token(
    *,
    profile_name: str,
    token_plaintext: str,
    required_scope: str | None = None,
) -> dict[str, Any]:
    """Validate a local-only agent token and update last_used."""

    token = token_plaintext.strip()
    if not token.startswith("mtl_"):
        raise LocalTokenError(
            "Invalid local agent token",
            code="AUTH-LOCAL-401",
            debug="token prefix mismatch",
        )

    candidate_hash = _token_hash(token)
    tokens = _read_tokens(profile_name)

    for index, record in enumerate(tokens):
        stored_hash = str(record.get("token_hash") or "")
        if not stored_hash or not hmac.compare_digest(stored_hash, candidate_hash):
            continue

        if bool(record.get("revoked", False)):
            raise LocalTokenError(
                "Local agent token is revoked",
                code="AUTH-LOCAL-403",
                debug=f"token_id={record.get('id')}",
            )

        expires_at = _parse_iso(record.get("expires_at"))
        if expires_at is not None and expires_at <= _now():
            raise LocalTokenError(
                "Local agent token is expired",
                code="AUTH-LOCAL-403",
                debug=f"token_id={record.get('id')}",
            )

        scope = str(record.get("scope") or "").strip().lower()
        if not _scope_allows(scope, required_scope):
            raise LocalTokenError(
                "Local agent token scope is insufficient",
                code="AUTH-LOCAL-403",
                debug=f"token_id={record.get('id')} scope={scope} required={required_scope}",
            )

        updated = dict(record)
        updated["last_used"] = _now_iso()
        tokens[index] = updated
        _write_tokens(profile_name, tokens)
        return _public_record(updated)

    raise LocalTokenError(
        "Local agent token was not found",
        code="AUTH-LOCAL-401",
        debug="hash lookup miss",
    )


__all__ = [
    name
    for name in globals()
    if not name.startswith("__")
]
