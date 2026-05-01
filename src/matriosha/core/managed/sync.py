"""Managed/local synchronization engine for encrypted memories."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Literal
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from matriosha.core.binary_protocol import MemoryEnvelope, decode_envelope, envelope_from_json, envelope_to_json
from matriosha.core.managed.client import ManagedClient
from matriosha.core.storage_local import LocalStore
from matriosha.core.vectors import Embedder

logger = logging.getLogger(__name__)

ManagedVectorMode = Literal["server", "local"]
_MANAGED_VECTOR_MODE_ENV = "MATRIOSHA_MANAGED_VECTOR_MODE"


def resolve_managed_vector_mode(value: str | None = None) -> ManagedVectorMode:
    """Resolve where managed-mode semantic vectors are stored/searched.

    server:
        Current behavior. Upload plaintext-derived embeddings to the managed backend.
    local:
        Privacy mode. Do not upload embeddings; keep semantic vectors local only.
    """

    raw = value if value is not None else os.getenv(_MANAGED_VECTOR_MODE_ENV)
    mode = (raw or "server").strip().lower()
    if mode in {"", "server"}:
        return "server"
    if mode == "local":
        return "local"
    raise ValueError(f"{_MANAGED_VECTOR_MODE_ENV} must be either 'server' or 'local'")


@dataclass
class SyncReport:
    pushed: int = 0
    pulled: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pushed": self.pushed,
            "pulled": self.pulled,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass
class _SyncState:
    local_to_remote: dict[str, str] = field(default_factory=dict)
    remote_to_local: dict[str, str] = field(default_factory=dict)
    roundtrip_hashes: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "_SyncState":
        return cls(
            local_to_remote=dict(data.get("local_to_remote") or {}),
            remote_to_local=dict(data.get("remote_to_local") or {}),
            roundtrip_hashes=dict(data.get("roundtrip_hashes") or {}),
        )


class SyncEngine:
    def __init__(
        self,
        local: LocalStore,
        remote: ManagedClient,
        embedder: Embedder,
        data_key: bytes | None = None,
        managed_vector_mode: ManagedVectorMode | None = None,
    ):
        self.local = local
        self.remote = remote
        self.embedder = embedder
        self.data_key = data_key
        self.managed_vector_mode = managed_vector_mode or resolve_managed_vector_mode()
        self._embedding_text_by_memory_id: dict[str, str] = {}
        self._state_path = Path(self.local.root) / "sync_state.json"

    async def push(self, *, since: datetime | None = None) -> SyncReport:
        report = SyncReport()
        state = self._load_state()

        envelopes = self.local.list(limit=1_000_000)
        ordered = sorted(envelopes, key=lambda env: (env.created_at, env.memory_id))

        for env in ordered:
            if since is not None and _parse_created_at(env.created_at) < since:
                continue

            local_id = env.memory_id
            if local_id in state.local_to_remote:
                continue

            try:
                local_env, payload_b64 = self.local.get(local_id)
                payload_text = payload_b64.decode("utf-8")
                envelope_dict = _envelope_to_dict(local_env)

                embedding: list[float] | None = None
                if self.managed_vector_mode == "server":
                    self._embedding_text_by_memory_id[local_env.memory_id] = self._semantic_text_for_embedding(
                        local_env,
                        payload_b64,
                    )
                    embedding = self._build_embedding(local_env)

                remote_id = await self.remote.upload_memory(
                    envelope=envelope_dict,
                    payload_b64=payload_text,
                    embedding=embedding,
                )

                fetched_env, fetched_payload = await self.remote.fetch_memory(remote_id)
                expected_hash = _roundtrip_hash(envelope_dict, payload_text)
                actual_hash = _roundtrip_hash(fetched_env, fetched_payload)
                if expected_hash != actual_hash:
                    report.errors.append(
                        f"push hash mismatch local_id={local_id} remote_id={remote_id}"
                    )
                    continue

                state.local_to_remote[local_id] = remote_id
                state.remote_to_local[remote_id] = local_id
                state.roundtrip_hashes[remote_id] = actual_hash
                report.pushed += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"push failed local_id={local_id}: {type(exc).__name__}: {exc}")

        self._save_state(state)
        return report

    async def pull(self, *, since: datetime | None = None) -> SyncReport:
        report = SyncReport()
        state = self._load_state()

        remote_items = await self.remote.list_memories(limit=1_000)
        ordered_items = sorted(remote_items, key=self._remote_sort_key)

        for item in ordered_items:
            remote_id = _remote_memory_id(item)
            if remote_id is None:
                self._warn(report, "pull anomaly: remote item missing id")
                continue

            if remote_id in state.remote_to_local:
                mapped_local_id = state.remote_to_local[remote_id]
                try:
                    self.local.get(mapped_local_id)
                    continue
                except Exception:  # noqa: BLE001
                    pass

            try:
                envelope_dict, payload_text = await self.remote.fetch_memory(remote_id)
                actual_hash = _roundtrip_hash(envelope_dict, payload_text)

                expected_hash = (
                    item.get("roundtrip_hash")
                    or item.get("hash")
                    or state.roundtrip_hashes.get(remote_id)
                )
                if expected_hash and not _constant_compare(str(expected_hash), actual_hash):
                    report.errors.append(
                        f"pull hash mismatch remote_id={remote_id} expected={expected_hash} actual={actual_hash}"
                    )
                    continue

                env_obj = envelope_from_json(json.dumps(envelope_dict, separators=(",", ":")))
                if since is not None and _parse_created_at(env_obj.created_at) < since:
                    continue

                payload_bytes = payload_text.encode("utf-8")
                local_id = env_obj.memory_id

                should_write = True
                if local_id in state.local_to_remote and state.local_to_remote[local_id] != remote_id:
                    self._warn(
                        report,
                        (
                            "pull anomaly: local id maps to a different remote id "
                            f"local_id={local_id} old_remote={state.local_to_remote[local_id]} new_remote={remote_id}"
                        ),
                    )

                try:
                    existing_env, _ = self.local.get(local_id)
                    if existing_env.merkle_root != env_obj.merkle_root:
                        local_created = _parse_created_at(existing_env.created_at)
                        remote_created = _parse_created_at(env_obj.created_at)
                        if local_created > remote_created:
                            should_write = False
                            self._warn(
                                report,
                                (
                                    "pull conflict resolved local-wins "
                                    f"local_id={local_id} local_created={existing_env.created_at} "
                                    f"remote_created={env_obj.created_at}"
                                ),
                            )
                        else:
                            self._warn(
                                report,
                                (
                                    "pull conflict resolved remote-wins "
                                    f"local_id={local_id} local_created={existing_env.created_at} "
                                    f"remote_created={env_obj.created_at}"
                                ),
                            )
                except FileNotFoundError:
                    pass

                if should_write:
                    embedding_array: np.ndarray | None = None
                    if self.data_key is not None:
                        self._embedding_text_by_memory_id[env_obj.memory_id] = self._semantic_text_for_embedding(
                            env_obj,
                            payload_bytes,
                        )
                        embedding = self._build_embedding(env_obj)
                        embedding_array = np.asarray(embedding, dtype=np.float32)
                    self.local.put(env_obj, payload_bytes, embedding=embedding_array)
                    report.pulled += 1

                state.local_to_remote[local_id] = remote_id
                state.remote_to_local[remote_id] = local_id
                state.roundtrip_hashes[remote_id] = actual_hash
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"pull failed remote_id={remote_id}: {type(exc).__name__}: {exc}")

        self._save_state(state)
        return report

    def rebuild_local_vectors(self) -> int:
        """Rebuild the encrypted local vector index from local encrypted memories."""

        if self.data_key is None:
            raise ValueError("data key required to rebuild local vectors")

        rebuilt = 0
        for env in self.local.list(limit=1_000_000):
            local_env, payload_bytes = self.local.get(env.memory_id)
            self._embedding_text_by_memory_id[local_env.memory_id] = self._semantic_text_for_embedding(
                local_env,
                payload_bytes,
            )
            embedding = self._build_embedding(local_env)
            embedding_kind: Literal["memory", "parent"] = "parent" if getattr(local_env, "children", None) else "memory"
            self.local.put(
                local_env,
                payload_bytes,
                embedding=np.asarray(embedding, dtype=np.float32),
                embedding_kind=embedding_kind,
                is_active=True,
            )
            rebuilt += 1
        return rebuilt

    async def sync(self) -> SyncReport:
        pushed = await self.push()
        pulled = await self.pull()
        report = SyncReport(
            pushed=pushed.pushed,
            pulled=pulled.pulled,
            errors=[*pushed.errors, *pulled.errors],
            warnings=[*pushed.warnings, *pulled.warnings],
        )
        if self.managed_vector_mode == "local" and self.data_key is not None:
            try:
                rebuilt = self.rebuild_local_vectors()
                if rebuilt:
                    report.warnings.append(f"rebuilt local vector index entries={rebuilt}")
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"local vector rebuild failed: {type(exc).__name__}: {exc}")
        return report

    def _load_state(self) -> _SyncState:
        if not self._state_path.exists():
            return _SyncState()
        try:
            payload = self._state_path.read_text(encoding="utf-8")
            data = json.loads(payload)
            if not isinstance(data, dict):
                return _SyncState()
            return _SyncState.from_dict(data)
        except Exception:  # noqa: BLE001
            return _SyncState()

    def _save_state(self, state: _SyncState) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".tmp")
        data = asdict(state)
        tmp.write_text(json.dumps(data, separators=(",", ":"), sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._state_path)
        if os.name != "nt":
            os.chmod(self._state_path, 0o600)

    def _build_embedding(self, envelope: MemoryEnvelope) -> list[float]:
        text = self._embedding_text_by_memory_id.get(envelope.memory_id, "")
        vector = np.asarray(self.embedder.embed(text), dtype=np.float32)
        return [float(x) for x in vector.tolist()]

    def _semantic_text_for_embedding(self, envelope: MemoryEnvelope, payload_b64: bytes) -> str:
        if self.data_key is None:
            raise ValueError("data key required to build content embedding")
        plaintext = decode_envelope(envelope, payload_b64, self.data_key)
        return plaintext.decode("utf-8", errors="replace")

    @staticmethod
    def _remote_sort_key(item: dict[str, Any]) -> tuple[str, str]:
        envelope_value = item.get("envelope")
        envelope: dict[str, Any] = envelope_value if isinstance(envelope_value, dict) else {}
        created_at = envelope.get("created_at") or item.get("created_at") or ""
        remote_id = _remote_memory_id(item) or ""
        return str(created_at), str(remote_id)

    @staticmethod
    def _warn(report: SyncReport, message: str) -> None:
        logger.warning(message)
        report.warnings.append(message)


def _parse_created_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _envelope_to_dict(env: MemoryEnvelope) -> dict[str, Any]:
    return json.loads(envelope_to_json(env))


def _roundtrip_hash(envelope: dict[str, Any], payload_b64: str) -> str:
    canonical_env = json.dumps(envelope, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256()
    digest.update(canonical_env.encode("utf-8"))
    digest.update(b"\n")
    digest.update(payload_b64.encode("utf-8"))
    return digest.hexdigest()


def _remote_memory_id(item: dict[str, Any]) -> str | None:
    for key in ("id", "remote_id", "memory_id"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _constant_compare(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    result = 0
    for lch, rch in zip(left.encode("utf-8"), right.encode("utf-8")):
        result |= lch ^ rch
    return result == 0
