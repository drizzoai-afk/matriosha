"""Managed/local synchronization engine for encrypted memories."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np

from matriosha.core.binary_protocol import MemoryEnvelope, decode_envelope, envelope_from_json, envelope_to_json
from matriosha.core.managed.client import ManagedClient
from matriosha.core.search_terms import build_retrieval_index_text, extract_search_terms, keyed_search_tokens
from matriosha.core.storage_local import LocalStore
from matriosha.core.vectors import Embedder

logger = logging.getLogger(__name__)

_SYNC_UPLOAD_TIMEOUT_SECONDS = 15.0
_SYNC_BULK_UPLOAD_TIMEOUT_SECONDS = 30.0
_SYNC_PROGRESS_EVERY = 25


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
    ):
        self.local = local
        self.remote = remote
        self.embedder = embedder
        self.data_key = data_key
        self._embedding_text_by_memory_id: dict[str, str] = {}
        self._state_path = Path(self.local.root) / "sync_state.json"

    async def push(self, *, since: datetime | None = None) -> SyncReport:
        report = SyncReport()
        state = self._load_state()
        await self._push_deleted_local_memories(state, report)

        envelopes = self.local.list(limit=1_000_000)
        ordered = sorted(envelopes, key=lambda env: (env.created_at, env.memory_id))
        pending = [
            env for env in ordered
            if (since is None or _parse_created_at(env.created_at) >= since)
            and env.memory_id not in state.local_to_remote
        ]

        batch_size = _resolve_sync_bulk_batch_size()
        logger.info("sync push starting pending=%s bulk_batch_size=%s", len(pending), batch_size)

        for batch_start in range(0, len(pending), batch_size):
            batch = pending[batch_start : batch_start + batch_size]
            upload_items: list[dict[str, Any]] = []
            local_rows: list[tuple[str, dict[str, Any], str]] = []

            for env in batch:
                local_id = env.memory_id
                try:
                    local_env, payload_b64 = self.local.get(local_id)
                    payload_text = payload_b64.decode("utf-8")
                    envelope_dict = _envelope_to_dict(local_env)

                    plaintext = ""
                    metadata_hashes: list[str] = []
                    if self.data_key is not None:
                        plaintext = self._semantic_text_for_embedding(local_env, payload_b64)
                        terms = extract_search_terms(
                            build_retrieval_index_text(plaintext),
                            *(local_env.tags or []),
                            local_env.mime_type,
                            local_env.content_kind,
                        )
                        metadata_hashes = keyed_search_tokens(terms, self.data_key)

                    embedding: list[float] | None = None

                    upload_items.append(
                        {
                            "envelope": envelope_dict,
                            "payload_b64": payload_text,
                            "embedding": embedding,
                            "metadata_hashes": metadata_hashes,
                        }
                    )
                    local_rows.append((local_id, envelope_dict, payload_text))
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"push prepare failed local_id={local_id}: {type(exc).__name__}: {exc}")

            if not upload_items:
                continue

            try:
                logger.info(
                    "sync push bulk upload start batch_start=%s batch_size=%s",
                    batch_start,
                    len(upload_items),
                )
                if hasattr(self.remote, "upload_memories"):
                    bulk_timeout = min(
                        _SYNC_BULK_UPLOAD_TIMEOUT_SECONDS,
                        max(_SYNC_UPLOAD_TIMEOUT_SECONDS, _SYNC_UPLOAD_TIMEOUT_SECONDS * len(upload_items) / 10),
                    )
                    remote_ids = await asyncio.wait_for(
                        self.remote.upload_memories(upload_items),
                        timeout=bulk_timeout,
                    )
                else:
                    remote_ids = []
                    for item in upload_items:
                        remote_ids.append(
                            await asyncio.wait_for(
                                self.remote.upload_memory(
                                    envelope=item["envelope"],
                                    payload_b64=item["payload_b64"],
                                    embedding=item.get("embedding"),
                                    metadata_hashes=item.get("metadata_hashes"),
                                ),
                                timeout=_SYNC_UPLOAD_TIMEOUT_SECONDS,
                            )
                        )
                logger.info(
                    "sync push bulk upload complete batch_start=%s uploaded=%s",
                    batch_start,
                    len(remote_ids),
                )
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "sync push bulk upload failed; falling back to single uploads batch_start=%s error=%s",
                    batch_start,
                    f"{type(exc).__name__}: {exc}",
                )
                remote_ids = []
                fallback_failed = False
                for item, (local_id, _envelope_dict, _payload_text) in zip(upload_items, local_rows, strict=True):
                    try:
                        remote_ids.append(
                            await asyncio.wait_for(
                                self.remote.upload_memory(
                                    envelope=item["envelope"],
                                    payload_b64=item["payload_b64"],
                                    embedding=item.get("embedding"),
                                    metadata_hashes=item.get("metadata_hashes"),
                                ),
                                timeout=_SYNC_UPLOAD_TIMEOUT_SECONDS,
                            )
                        )
                    except asyncio.TimeoutError:
                        fallback_failed = True
                        report.errors.append(
                            f"push failed local_id={local_id}: TimeoutError: upload exceeded {_SYNC_UPLOAD_TIMEOUT_SECONDS:.0f}s"
                        )
                    except Exception as single_exc:  # noqa: BLE001
                        fallback_failed = True
                        report.errors.append(
                            f"push failed local_id={local_id}: {type(single_exc).__name__}: {single_exc}"
                        )

                if fallback_failed:
                    continue

            if len(remote_ids) != len(local_rows):
                for local_id, _envelope_dict, _payload_text in local_rows:
                    report.errors.append(f"push failed local_id={local_id}: bulk response length mismatch")
                continue

            for (local_id, envelope_dict, payload_text), remote_id in zip(local_rows, remote_ids, strict=True):
                roundtrip_hash = _roundtrip_hash(envelope_dict, payload_text)
                state.local_to_remote[local_id] = remote_id
                state.remote_to_local[remote_id] = local_id
                state.roundtrip_hashes[remote_id] = roundtrip_hash
                report.pushed += 1

            self._save_state(state)
            logger.info(
                "sync push progress pushed=%s pending=%s bulk_batch_size=%s",
                report.pushed,
                len(pending),
                batch_size,
            )

        self._save_state(state)
        return report

    async def pull(self, *, since: datetime | None = None) -> SyncReport:
        report = SyncReport()
        state = self._load_state()

        remote_items = await self.remote.list_memories(limit=1_000)
        ordered_items = sorted(remote_items, key=self._remote_sort_key)
        local_index = self.local.index_metadata()
        local_index_dirty = False

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
                    # Pull is intentionally append-only/fast. Local semantic vectors
                    # are built later by `matriosha memory index` so restore does not
                    # block on embedding generation or pgvector writes.
                    self.local.put(env_obj, payload_bytes, update_index=False)
                    local_index[local_id] = self.local._build_safe_metadata(env_obj, list(env_obj.tags))
                    local_index_dirty = True
                    report.pulled += 1

                state.local_to_remote[local_id] = remote_id
                state.remote_to_local[remote_id] = local_id
                state.roundtrip_hashes[remote_id] = actual_hash
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"pull failed remote_id={remote_id}: {type(exc).__name__}: {exc}")

        if local_index_dirty:
            self.local._write_index_atomic(local_index)

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
                update_index=False,
            )
            rebuilt += 1
        return rebuilt

    async def sync(self) -> SyncReport:
        """Push local encrypted memories to managed storage.

        `vault sync` is intentionally push-only. Pull/restore should be exposed
        through an explicit restore/pull command so normal sync never performs
        an expensive remote scan or imports unrelated remote rows.
        """
        return await self.push()

    async def _push_deleted_local_memories(self, state: _SyncState, report: SyncReport) -> None:
        deleted_local_ids: list[str] = []
        for local_id, remote_id in list(state.local_to_remote.items()):
            try:
                self.local.get(local_id)
                continue
            except FileNotFoundError:
                deleted_local_ids.append(local_id)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"delete sync inspect failed local_id={local_id}: {type(exc).__name__}: {exc}")

        for local_id in deleted_local_ids:
            remote_id = state.local_to_remote.get(local_id)
            if not remote_id:
                continue
            try:
                await asyncio.wait_for(self.remote.delete_memory(remote_id), timeout=_SYNC_UPLOAD_TIMEOUT_SECONDS)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"delete sync failed local_id={local_id} remote_id={remote_id}: {type(exc).__name__}: {exc}")
                continue

            state.local_to_remote.pop(local_id, None)
            state.remote_to_local.pop(remote_id, None)
            state.roundtrip_hashes.pop(remote_id, None)

        if deleted_local_ids:
            self._save_state(state)

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


def _resolve_sync_bulk_batch_size() -> int:
    raw = os.getenv("MATRIOSHA_SYNC_BULK_BATCH_SIZE", "10")
    try:
        value = int(raw)
    except ValueError:
        return 10
    return max(1, min(value, 100))


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
