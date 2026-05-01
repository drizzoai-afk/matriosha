"""Embedding backends and local vector index for semantic memory lookup."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
from pathlib import Path
from typing import Literal, Protocol

import numpy as np
import platformdirs

from matriosha.core.crypto import decrypt, encrypt

_VALID_PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{1,128}$")
_VECTOR_DIM = 384
_ENTRY_TYPES = {"memory", "parent"}


class Embedder(Protocol):
    """Protocol for text embedders used by local vector search."""

    dim: int

    def embed(self, text: str) -> np.ndarray:
        """Embed one text input into a float32 vector."""


class HashEmbedder:
    """Offline-safe deterministic embedding via hashed trigrams."""

    dim = _VECTOR_DIM

    def embed(self, text: str) -> np.ndarray:
        normalized = (text or "").lower()
        padded = f"  {normalized}  "

        vec = np.zeros(self.dim, dtype=np.float32)
        if len(padded) < 3:
            return _l2_normalize(vec)

        for i in range(len(padded) - 2):
            trigram = padded[i : i + 3]
            digest = hashlib.sha256(trigram.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if (digest[4] & 1) == 0 else -1.0
            vec[idx] += sign

        return _l2_normalize(vec)


class SBERTEmbedder:
    """Sentence-transformers embedding backend."""

    dim = _VECTOR_DIM

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - dependency optional
                raise RuntimeError(
                    "sentence-transformers is not installed. Install with: pip install 'matriosha[embeddings]'"
                ) from exc
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, text: str) -> np.ndarray:
        model = self._get_model()
        vector = model.encode(text or "", convert_to_numpy=True)
        vector = np.asarray(vector, dtype=np.float32)
        if vector.shape != (self.dim,):
            raise ValueError(f"unexpected embedding shape {vector.shape}; expected ({self.dim},)")
        return _l2_normalize(vector)


def get_default_embedder() -> Embedder:
    """Resolve default embedder backend from MATRIOSHA_EMBEDDER env var."""

    backend = os.getenv("MATRIOSHA_EMBEDDER", "hash").strip().lower()
    if backend == "sbert":
        return SBERTEmbedder()
    return HashEmbedder()


class LocalVectorIndex:
    """Persistent profile-scoped in-memory cosine-search vector index."""

    def __init__(self, profile: str, data_key: bytes | None = None):
        if not _VALID_PROFILE_PATTERN.fullmatch(profile):
            raise ValueError("invalid profile")

        data_dir = Path(platformdirs.user_data_dir("matriosha"))
        self._root = data_dir / profile
        self._vectors_path = self._root / "vectors.npz"
        self._ids_path = self._root / "ids.json"
        self._meta_path = self._root / "vector_meta.json"
        self._vectors_enc_path = self._root / "vectors.npz.enc"
        self._ids_enc_path = self._root / "ids.json.enc"
        self._meta_enc_path = self._root / "vector_meta.json.enc"
        self._data_key = data_key

        self._ids: list[str] = []
        self._vectors = np.zeros((0, _VECTOR_DIM), dtype=np.float32)
        self._kinds: list[str] = []
        self._active: list[bool] = []
        self.load()

    def add(
        self,
        memory_id: str,
        vec: np.ndarray,
        *,
        entry_type: Literal["memory", "parent"] = "memory",
        is_active: bool = True,
    ) -> None:
        if entry_type not in _ENTRY_TYPES:
            raise ValueError("entry_type must be 'memory' or 'parent'")

        normalized = self._validate_and_normalize(vec)
        if memory_id in self._ids:
            idx = self._ids.index(memory_id)
            self._vectors[idx] = normalized
            self._kinds[idx] = entry_type
            self._active[idx] = bool(is_active)
            return

        self._ids.append(memory_id)
        self._vectors = np.vstack([self._vectors, normalized])
        self._kinds.append(entry_type)
        self._active.append(bool(is_active))

    def remove(self, memory_id: str) -> None:
        if memory_id not in self._ids:
            return
        idx = self._ids.index(memory_id)
        self._ids.pop(idx)
        self._vectors = np.delete(self._vectors, idx, axis=0)
        self._kinds.pop(idx)
        self._active.pop(idx)

    def set_active(self, memory_id: str, is_active: bool) -> None:
        if memory_id not in self._ids:
            return
        idx = self._ids.index(memory_id)
        self._active[idx] = bool(is_active)

    def get_vector(self, memory_id: str) -> np.ndarray | None:
        if memory_id not in self._ids:
            return None
        idx = self._ids.index(memory_id)
        return np.asarray(self._vectors[idx], dtype=np.float32)

    def get_meta(self, memory_id: str) -> dict[str, object] | None:
        if memory_id not in self._ids:
            return None
        idx = self._ids.index(memory_id)
        return {
            "memory_id": memory_id,
            "entry_type": self._kinds[idx],
            "active": self._active[idx],
        }

    def search(
        self,
        q: np.ndarray,
        k: int = 10,
        *,
        include_inactive: bool = False,
        entry_types: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        if k < 1 or self._vectors.shape[0] == 0:
            return []

        qn = self._validate_and_normalize(q)
        sims = self._vectors @ qn

        candidate_mask = np.ones(len(self._ids), dtype=bool)
        if not include_inactive:
            candidate_mask &= np.asarray(self._active, dtype=bool)
        if entry_types is not None:
            candidate_mask &= np.asarray([kind in entry_types for kind in self._kinds], dtype=bool)

        candidate_indices = np.flatnonzero(candidate_mask)
        if candidate_indices.size == 0:
            return []

        candidate_scores = sims[candidate_indices]
        limit = min(k, candidate_indices.size)

        if limit < candidate_indices.size:
            top_positions = np.argpartition(-candidate_scores, limit - 1)[:limit]
            ranked_positions = top_positions[np.argsort(-candidate_scores[top_positions], kind='stable')]
        else:
            ranked_positions = np.argsort(-candidate_scores, kind='stable')

        return [
            (self._ids[int(candidate_indices[pos])], float(candidate_scores[pos]))
            for pos in ranked_positions
        ]

    def load(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

        ids: list[str]
        vectors: np.ndarray

        ids_payload = self._read_index_file(
            self._ids_enc_path,
            self._ids_path,
            b"matriosha:vectors:ids",
        )
        if ids_payload is not None:
            ids = json.loads(ids_payload.decode("utf-8"))
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                raise ValueError("ids.json must contain a JSON array of strings")
        else:
            ids = []

        vectors_payload = self._read_index_file(
            self._vectors_enc_path,
            self._vectors_path,
            b"matriosha:vectors:data",
        )
        if vectors_payload is not None:
            with np.load(io.BytesIO(vectors_payload)) as data:
                if "vectors" not in data:
                    raise ValueError("vectors.npz missing 'vectors' array")
                vectors = np.asarray(data["vectors"], dtype=np.float32)
        else:
            vectors = np.zeros((0, _VECTOR_DIM), dtype=np.float32)

        if vectors.ndim != 2 or vectors.shape[1] != _VECTOR_DIM:
            raise ValueError(f"vectors must have shape (N, {_VECTOR_DIM})")
        if vectors.shape[0] != len(ids):
            raise ValueError("vectors row count must match ids length")

        kinds, active_flags = self._load_meta_defaults(ids)

        self._ids = ids
        self._vectors = vectors
        self._kinds = kinds
        self._active = active_flags

    def save(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

        vectors_tmp = self._root / "vectors.npz.tmp"
        ids_tmp = self._root / "ids.json.tmp"
        meta_tmp = self._root / "vector_meta.json.tmp"

        vectors_buffer = io.BytesIO()
        np.savez_compressed(vectors_buffer, vectors=np.asarray(self._vectors, dtype=np.float32))
        self._write_index_file(vectors_tmp, vectors_buffer.getvalue(), b"matriosha:vectors:data")
        self._write_index_file(
            ids_tmp,
            json.dumps(self._ids, separators=(",", ":")).encode("utf-8"),
            b"matriosha:vectors:ids",
        )

        meta_payload = [
            {"memory_id": memory_id, "entry_type": kind, "active": active}
            for memory_id, kind, active in zip(self._ids, self._kinds, self._active)
        ]
        self._write_index_file(
            meta_tmp,
            json.dumps(meta_payload, separators=(",", ":")).encode("utf-8"),
            b"matriosha:vectors:meta",
        )

        vectors_path = self._vectors_enc_path if self._data_key is not None else self._vectors_path
        ids_path = self._ids_enc_path if self._data_key is not None else self._ids_path
        meta_path = self._meta_enc_path if self._data_key is not None else self._meta_path

        os.replace(vectors_tmp, vectors_path)
        os.replace(ids_tmp, ids_path)
        os.replace(meta_tmp, meta_path)

        if os.name != "nt":
            os.chmod(vectors_path, 0o600)
            os.chmod(ids_path, 0o600)
            os.chmod(meta_path, 0o600)

        if self._data_key is not None:
            for legacy_path in (self._vectors_path, self._ids_path, self._meta_path):
                if legacy_path.exists():
                    legacy_path.unlink()

    def _read_index_file(self, encrypted_path: Path, plaintext_path: Path, aad: bytes) -> bytes | None:
        if self._data_key is None:
            if plaintext_path.exists():
                return plaintext_path.read_bytes()
            if encrypted_path.exists():
                raise ValueError("data key required to read encrypted vector index")
            return None

        if encrypted_path.exists():
            payload = encrypted_path.read_bytes()
            if len(payload) < 12:
                raise ValueError("encrypted vector index file is truncated")
            nonce, ciphertext = payload[:12], payload[12:]
            return decrypt(nonce, ciphertext, self._data_key, aad=aad)

        if plaintext_path.exists():
            return plaintext_path.read_bytes()

        return None

    def _write_index_file(self, path: Path, payload: bytes, aad: bytes) -> None:
        if self._data_key is None:
            path.write_bytes(payload)
            return

        nonce, ciphertext = encrypt(payload, self._data_key, aad=aad)
        path.write_bytes(nonce + ciphertext)

    def _load_meta_defaults(self, ids: list[str]) -> tuple[list[str], list[bool]]:
        meta_payload = self._read_index_file(
            self._meta_enc_path,
            self._meta_path,
            b"matriosha:vectors:meta",
        )
        if meta_payload is None:
            return (["memory"] * len(ids), [True] * len(ids))
        parsed = json.loads(meta_payload.decode("utf-8"))
        if not isinstance(parsed, list):
            raise ValueError("vector_meta.json must contain an array")
        if len(parsed) != len(ids):
            raise ValueError("vector_meta.json length must match ids length")

        kinds: list[str] = []
        active_flags: list[bool] = []

        for idx, item in enumerate(parsed):
            if not isinstance(item, dict):
                raise ValueError("vector_meta.json entries must be objects")
            memory_id = item.get("memory_id")
            if memory_id != ids[idx]:
                raise ValueError("vector_meta.json memory_id order must match ids.json")

            entry_type = item.get("entry_type", "memory")
            if entry_type not in _ENTRY_TYPES:
                raise ValueError("vector_meta.json entry_type must be memory or parent")
            active = item.get("active", True)
            if not isinstance(active, bool):
                raise ValueError("vector_meta.json active must be boolean")

            kinds.append(entry_type)
            active_flags.append(active)

        return kinds, active_flags

    @staticmethod
    def _validate_and_normalize(vec: np.ndarray) -> np.ndarray:
        arr = np.asarray(vec, dtype=np.float32)
        if arr.shape != (_VECTOR_DIM,):
            raise ValueError(f"vector must have shape ({_VECTOR_DIM},)")
        return _l2_normalize(arr)


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    if norm <= 0.0:
        return vec.astype(np.float32, copy=True)
    return (vec / norm).astype(np.float32, copy=False)
