"""Tamper-evident audit trail primitives.

Audit records intentionally avoid plaintext memory content, tokens, keys, and
raw secrets. Each JSONL record is hash-chained so local tampering is detectable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import platformdirs  # noqa: F401
from typing import Any

from matriosha.core.paths import data_dir

_SECRET_KEY_RE = re.compile(
    r"(token|secret|password|passphrase|api[_-]?key|authorization|credential|data[_-]?key|refresh)",
    re.IGNORECASE,
)
_REDACTED = "[REDACTED]"


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    occurred_at: str
    actor_type: str
    actor_id: str | None
    profile: str
    mode: str
    action: str
    target_type: str
    target_id: str | None
    outcome: str
    reason_code: str | None = None
    request_id: str | None = None
    ip_hash: str | None = None
    user_agent_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        profile: str,
        mode: str,
        action: str,
        target_type: str,
        outcome: str,
        actor_type: str = "cli",
        actor_id: str | None = None,
        target_id: str | None = None,
        reason_code: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "AuditEvent":
        return cls(
            event_id=str(uuid.uuid4()),
            occurred_at=datetime.now(timezone.utc).isoformat(),
            actor_type=actor_type,
            actor_id=actor_id,
            profile=profile,
            mode=mode,
            action=action,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            reason_code=reason_code,
            request_id=request_id,
            metadata=redact(metadata or {}),
        )


class AuditJournal:
    def __init__(self, profile: str, *, root: Path | None = None) -> None:
        self.profile = profile
        base = root or data_dir() / profile
        self.path = base / "audit" / "events.jsonl"

    def append(self, event: AuditEvent) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        previous_hash = self._last_hash()
        payload = asdict(event)
        payload["metadata"] = redact(payload.get("metadata") or {})
        payload["previous_hash"] = previous_hash
        payload["event_hash"] = _hash_payload(payload)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        if os.name != "nt":
            os.chmod(self.path, 0o600)
        return payload

    def verify(self) -> tuple[bool, str | None]:
        previous_hash: str | None = None
        if not self.path.exists():
            return True, None
        with self.path.open("r", encoding="utf-8") as fh:
            for index, line in enumerate(fh, start=1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    return False, f"line {index}: invalid json"
                expected_previous = record.get("previous_hash")
                if expected_previous != previous_hash:
                    return False, f"line {index}: previous hash mismatch"
                stored_hash = record.get("event_hash")
                unsigned = dict(record)
                unsigned.pop("event_hash", None)
                actual_hash = _hash_payload(unsigned)
                if stored_hash != actual_hash:
                    return False, f"line {index}: event hash mismatch"
                previous_hash = stored_hash
        return True, None

    def _last_hash(self) -> str | None:
        if not self.path.exists():
            return None
        last = None
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = json.loads(line)
        return None if last is None else str(last.get("event_hash"))


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): (_REDACTED if _SECRET_KEY_RE.search(str(k)) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    return value


def hash_remote_hint(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()
