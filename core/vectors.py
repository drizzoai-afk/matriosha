"""Embedding backends and local vector index for semantic memory lookup."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Protocol

import numpy as np
import platformdirs

_VALID_PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{1,128}$")
_VECTOR_DIM = 384


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

    def __init__(self, profile: str):
        if not _VALID_PROFILE_PATTERN.fullmatch(profile):
            raise ValueError("invalid profile")

        data_dir = Path(platformdirs.user_data_dir("matriosha"))
        self._root = data_dir / profile
        self._vectors_path = self._root / "vectors.npz"
        self._ids_path = self._root / "ids.json"

        self._ids: list[str] = []
        self._vectors = np.zeros((0, _VECTOR_DIM), dtype=np.float32)
        self.load()

    def add(self, memory_id: str, vec: np.ndarray) -> None:
        normalized = self._validate_and_normalize(vec)
        if memory_id in self._ids:
            idx = self._ids.index(memory_id)
            self._vectors[idx] = normalized
            return

        self._ids.append(memory_id)
        self._vectors = np.vstack([self._vectors, normalized])

    def remove(self, memory_id: str) -> None:
        if memory_id not in self._ids:
            return
        idx = self._ids.index(memory_id)
        self._ids.pop(idx)
        self._vectors = np.delete(self._vectors, idx, axis=0)

    def search(self, q: np.ndarray, k: int = 10) -> list[tuple[str, float]]:
        if k < 1 or self._vectors.shape[0] == 0:
            return []

        qn = self._validate_and_normalize(q)
        sims = self._vectors @ qn

        top_k = min(k, len(self._ids))
        top_indices = np.argsort(-sims)[:top_k]
        return [(self._ids[i], float(sims[i])) for i in top_indices]

    def load(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

        ids: list[str]
        vectors: np.ndarray

        if self._ids_path.exists():
            ids = json.loads(self._ids_path.read_text(encoding="utf-8"))
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                raise ValueError("ids.json must contain a JSON array of strings")
        else:
            ids = []

        if self._vectors_path.exists():
            with np.load(self._vectors_path) as data:
                if "vectors" not in data:
                    raise ValueError("vectors.npz missing 'vectors' array")
                vectors = np.asarray(data["vectors"], dtype=np.float32)
        else:
            vectors = np.zeros((0, _VECTOR_DIM), dtype=np.float32)

        if vectors.ndim != 2 or vectors.shape[1] != _VECTOR_DIM:
            raise ValueError(f"vectors must have shape (N, {_VECTOR_DIM})")
        if vectors.shape[0] != len(ids):
            raise ValueError("vectors row count must match ids length")

        self._ids = ids
        self._vectors = vectors

    def save(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

        vectors_tmp = self._root / "vectors.npz.tmp"
        ids_tmp = self._root / "ids.json.tmp"

        with vectors_tmp.open("wb") as f:
            np.savez_compressed(f, vectors=self._vectors)
        ids_tmp.write_text(json.dumps(self._ids, separators=(",", ":")), encoding="utf-8")

        os.replace(vectors_tmp, self._vectors_path)
        os.replace(ids_tmp, self._ids_path)

        if os.name != "nt":
            os.chmod(self._vectors_path, 0o600)
            os.chmod(self._ids_path, 0o600)

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
