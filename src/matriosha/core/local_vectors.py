"""Factory for local semantic vector indexes.

Production local retrieval uses PostgreSQL/pgvector by default.
The npz backend is retained only as a legacy/test compatibility path.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

import numpy as np

from matriosha.core.local_pgvector import resolve_local_vector_backend
from matriosha.core.vectors import LocalVectorIndex


class LocalSemanticIndex(Protocol):
    def add(
        self,
        memory_id: str,
        vec: Any,
        *,
        entry_type: str = "memory",
        is_active: bool = True,
    ) -> None: ...

    def save(self) -> None: ...

    def search(
        self,
        q,
        *,
        k: int = 5,
        include_inactive: bool = False,
        entry_types: set[str] | None = None,
        candidate_ids: set[str] | None = None,
    ) -> list[tuple[str, float]]: ...

    def remove(self, memory_id: str) -> None: ...

    def set_active(self, memory_id: str, is_active: bool) -> None: ...


def get_local_vector_index(profile_name: str, *, data_key: bytes | None = None) -> LocalSemanticIndex:
    """Return the configured local vector index implementation."""

    backend = resolve_local_vector_backend()
    if backend == "pgvector":
        from matriosha.core.local_pgvector import LocalPgVectorIndex

        return LocalPgVectorIndex(profile_name)

    return cast(LocalSemanticIndex, LocalVectorIndex(profile_name, data_key=data_key))


def existing_vector_ids(index: LocalSemanticIndex) -> set[str]:
    """Return vector ids for either backend."""

    if hasattr(index, "memory_ids"):
        return set(index.memory_ids())  # type: ignore[attr-defined]
    return set(getattr(index, "_ids", []))


def vector_count(index: LocalSemanticIndex) -> int:
    """Return vector count for either backend."""

    return len(existing_vector_ids(index))


def as_numpy_vector(vec) -> np.ndarray:
    return np.asarray(list(vec), dtype=np.float32)


def active_vector_map(index: LocalSemanticIndex) -> dict[str, np.ndarray]:
    """Return active memory vectors by id for clustering."""

    if hasattr(index, "active_vectors"):
        return dict(index.active_vectors())  # type: ignore[attr-defined]

    ids = list(getattr(index, "_ids", []))
    vectors = getattr(index, "_vectors", np.zeros((0, 0), dtype=np.float32))
    meta = getattr(index, "_meta", {})
    result: dict[str, np.ndarray] = {}
    for idx, memory_id in enumerate(ids):
        memory_meta = meta.get(memory_id, {})
        if memory_meta.get("entry_type", "memory") != "memory":
            continue
        if memory_meta.get("active", True) is False:
            continue
        result[str(memory_id)] = np.asarray(vectors[idx], dtype=np.float32)
    return result
