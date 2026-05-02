"""Local filesystem-backed storage for encrypted memory envelopes and payloads."""

from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
from typing import Literal, cast

import numpy as np
import platformdirs
from pydantic import BaseModel, Field, ValidationError

from matriosha.core.binary_protocol import MemoryEnvelope, decode_envelope, envelope_from_json, envelope_to_json
from matriosha.core.vectors import LocalVectorIndex

_VALID_ID_PATTERN = r"^[A-Za-z0-9_\-:.]{1,128}$"


class _MemoryIdInput(BaseModel):
    memory_id: str = Field(pattern=_VALID_ID_PATTERN)


class _TagInput(BaseModel):
    tag: str = Field(pattern=_VALID_ID_PATTERN)


class LocalStore:
    """Store encrypted memory envelopes and base64 payloads on local disk."""

    def __init__(self, profile_name: str, data_key: bytes | None = None):
        self._profile_name = self._validate_id(profile_name, field_name="profile_name")
        self._data_dir = Path(platformdirs.user_data_dir("matriosha"))
        self._root = self._data_dir / self._profile_name
        self._memories_dir = self._root / "memories"
        self._index_path = self._root / "index.json"
        self._data_key = data_key
        self._vectors: LocalVectorIndex | None = None
        self._ensure_layout()

    @property
    def root(self) -> Path:
        return self._root

    def _vector_index(self) -> LocalVectorIndex:
        if self._vectors is None:
            self._vectors = LocalVectorIndex(self._profile_name, data_key=self._data_key)
        return self._vectors

    def put(
        self,
        env: MemoryEnvelope,
        b64_payload: bytes,
        embedding: np.ndarray | None = None,
        *,
        embedding_kind: str = "memory",
        is_active: bool = True,
    ) -> Path:
        memory_id = self._validate_id(env.memory_id, field_name="memory_id")
        validated_tags = [self._validate_id(tag, field_name="tag") for tag in env.tags]
        env.tags = validated_tags

        env_path, payload_path = self._memory_paths(memory_id)
        self._safe_write_bytes(env_path, envelope_to_json(env).encode("utf-8"), mode=0o600)
        self._safe_write_bytes(payload_path, b64_payload, mode=0o600)

        index = self._load_index()
        metadata = self._build_safe_metadata(env, validated_tags)
        index[memory_id] = metadata
        self._write_index_atomic(index)

        if embedding is not None:
            if embedding_kind not in ("memory", "parent"):
                raise ValueError("embedding_kind must be memory or parent")
            embedding_kind_literal = cast(Literal["memory", "parent"], embedding_kind)
            vectors = self._vector_index()
            vectors.add(memory_id, embedding, entry_type=embedding_kind_literal, is_active=is_active)
            vectors.save()

        return env_path

    def get(self, memory_id: str) -> tuple[MemoryEnvelope, bytes]:
        memory_id = self._validate_id(memory_id, field_name="memory_id")
        env_path, payload_path = self._memory_paths(memory_id)

        env_json = self._safe_read_text(env_path)
        payload = self._safe_read_bytes(payload_path)
        return envelope_from_json(env_json), payload

    def replace_payload(self, memory_id: str, payload_b64: bytes) -> None:
        """Atomically replace a stored base64 payload for an existing memory."""
        memory_id = self._validate_id(memory_id, field_name="memory_id")
        _, payload_path = self._memory_paths(memory_id)
        self._safe_write_bytes(payload_path, payload_b64, mode=0o600)

    def _build_safe_metadata(self, env: MemoryEnvelope, validated_tags: list[str]) -> dict[str, object]:
        """Build non-sensitive metadata for filtering without storing decrypted content."""
        mime_type = getattr(env, "mime_type", None) or "application/octet-stream"
        file_type = self._file_type_from_mime(mime_type)
        content_kind = "text" if mime_type.startswith("text/") else "binary"

        keywords = sorted(set(validated_tags + [content_kind, file_type, mime_type]))

        return {
            "tags": validated_tags,
            "created_at": env.created_at,
            "content_kind": content_kind,
            "mime_type": mime_type,
            "file_type": file_type,
            "search_keywords": keywords,
        }

    @staticmethod
    def _file_type_from_mime(mime_type: str) -> str:
        extension = mimetypes.guess_extension(mime_type or "") or ""
        if extension.startswith("."):
            return extension[1:].lower()
        if "/" in mime_type:
            return mime_type.rsplit("/", 1)[-1].lower()
        return "unknown"

    def index_metadata(self) -> dict[str, dict[str, object]]:
        """Return local non-sensitive index metadata."""
        return dict(self._load_index())

    def list(self, *, tag: str | None = None, limit: int = 100) -> list[MemoryEnvelope]:
        if limit < 1:
            raise ValueError("limit must be >= 1")

        validated_tag = self._validate_id(tag, field_name="tag") if tag is not None else None

        index = self._load_index()
        sorted_items = sorted(index.items(), key=lambda item: str(item[1].get("created_at", "")), reverse=True)

        envelopes: list[MemoryEnvelope] = []
        for memory_id, entry in sorted_items:
            tags = cast(list[str], entry.get("tags", []))
            if validated_tag is not None and validated_tag not in tags:
                continue

            try:
                env, _ = self.get(memory_id)
            except (FileNotFoundError, ValueError, ValidationError):
                continue

            envelopes.append(env)
            if len(envelopes) >= limit:
                break

        return envelopes

    def delete(self, memory_id: str) -> bool:
        memory_id = self._validate_id(memory_id, field_name="memory_id")
        env_path, payload_path = self._memory_paths(memory_id)

        removed = False
        for file_path in (env_path, payload_path):
            try:
                self._validate_in_dir(file_path, self._memories_dir)
                if file_path.is_symlink():
                    raise ValueError("symlink file operation rejected")
                file_path.unlink(missing_ok=False)
                removed = True
            except FileNotFoundError:
                pass

        index = self._load_index()
        if memory_id in index:
            index.pop(memory_id, None)
            self._write_index_atomic(index)
            removed = True

        vectors = self._vector_index()
        vectors.remove(memory_id)
        vectors.save()

        return removed

    def verify(self, memory_id: str, key: bytes) -> bool:
        try:
            env, payload = self.get(memory_id)
            decode_envelope(env, payload, key)
            return True
        except Exception:
            return False

    def _ensure_layout(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._memories_dir.mkdir(parents=True, exist_ok=True)
        if self._root.is_symlink() or self._memories_dir.is_symlink():
            raise ValueError("symlink directory rejected")
        if not self._index_path.exists():
            self._write_index_atomic({})

    def _memory_paths(self, memory_id: str) -> tuple[Path, Path]:
        env_path = self._memories_dir / f"{memory_id}.env.json"
        payload_path = self._memories_dir / f"{memory_id}.bin.b64"

        self._validate_in_dir(env_path, self._memories_dir)
        self._validate_in_dir(payload_path, self._memories_dir)
        return env_path, payload_path

    def _validate_in_dir(self, target: Path, parent: Path) -> None:
        parent_resolved = parent.resolve(strict=False)
        target_resolved = target.resolve(strict=False)
        if target_resolved.parent != parent_resolved:
            raise ValueError("path traversal rejected")

    def _validate_id(self, value: str | None, *, field_name: str) -> str:
        if value is None:
            raise ValueError(f"{field_name} is required")
        try:
            if field_name in {"memory_id", "profile_name"}:
                return _MemoryIdInput(memory_id=value).memory_id
            return _TagInput(tag=value).tag
        except ValidationError as exc:
            raise ValueError(f"invalid {field_name}") from exc

    def _load_index(self) -> dict[str, dict[str, object]]:
        if not self._index_path.exists():
            return {}
        raw = self._safe_read_text(self._index_path)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("index.json is invalid") from exc
        if not isinstance(parsed, dict):
            raise ValueError("index.json must contain an object")
        return cast(dict[str, dict[str, object]], parsed)

    def _write_index_atomic(self, index_data: dict[str, dict[str, object]]) -> None:
        self._validate_in_dir(self._index_path, self._root)
        tmp_path = self._root / "index.json.tmp"
        self._validate_in_dir(tmp_path, self._root)

        payload = json.dumps(index_data, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self._safe_write_bytes(tmp_path, payload, mode=0o600)
        os.replace(tmp_path, self._index_path)
        if os.name != "nt":
            os.chmod(self._index_path, 0o600)

    def _safe_read_text(self, path: Path) -> str:
        return self._safe_read_bytes(path).decode("utf-8")

    def _safe_read_bytes(self, path: Path) -> bytes:
        self._validate_in_dir(path, path.parent)
        if path.is_symlink():
            raise ValueError("symlink file operation rejected")
        return self._read_no_follow(path)

    def _safe_write_bytes(self, path: Path, data: bytes, *, mode: int) -> None:
        self._validate_in_dir(path, path.parent)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.parent.is_symlink():
            raise ValueError("symlink directory rejected")
        self._write_no_follow(path, data, mode)
        if os.name != "nt":
            os.chmod(path, mode)

    @staticmethod
    def _write_no_follow(path: Path, data: bytes, mode: int) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, mode)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise

    @staticmethod
    def _read_no_follow(path: Path) -> bytes:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags)
        try:
            with os.fdopen(fd, "rb") as f:
                return f.read()
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
