"""Local PostgreSQL/pgvector-backed semantic index.

This module is optional and local-only. The default local vector backend is PostgreSQL/pgvector.
When MATRIOSHA_LOCAL_DATABASE_URL is not set, Matriosha uses its default local Docker URL
and can auto-start the default pgvector container if Docker is installed and running.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any, Literal

import numpy as np

from matriosha.core.local_db import DEFAULT_LOCAL_DATABASE_URL, ensure_default_local_pgvector, local_db_auto_start_enabled
from matriosha.core.vectors import _VECTOR_DIM


LOCAL_VECTOR_BACKEND_ENV = "MATRIOSHA_LOCAL_VECTOR_BACKEND"
LOCAL_DATABASE_URL_ENV = "MATRIOSHA_LOCAL_DATABASE_URL"
LOCAL_VECTOR_INDEX_ENV = "MATRIOSHA_LOCAL_VECTOR_INDEX"

LocalVectorBackend = Literal["npz", "pgvector"]


def resolve_local_vector_backend(value: str | None = None) -> LocalVectorBackend:
    """Resolve the local vector backend.

    Defaults to "pgvector" for launch-grade scalability.
    """

    raw = value if value is not None else os.getenv(LOCAL_VECTOR_BACKEND_ENV)
    backend = (raw or "pgvector").strip().lower()
    if backend in {"", "npz", "file", "files"}:
        return "npz"
    if backend in {"pg", "postgres", "postgresql", "pgvector"}:
        return "pgvector"
    raise ValueError(f"{LOCAL_VECTOR_BACKEND_ENV} must be either 'npz' or 'pgvector'")


def get_local_database_url(value: str | None = None) -> str:
    """Return the configured or default local PostgreSQL database URL."""

    url = value if value is not None else os.getenv(LOCAL_DATABASE_URL_ENV)
    if url and url.strip():
        return url.strip()
    if local_db_auto_start_enabled():
        return ensure_default_local_pgvector()
    return DEFAULT_LOCAL_DATABASE_URL


class LocalPgVectorIndex:
    """PostgreSQL/pgvector-backed local vector index.

    The plaintext memory payload is never stored here. This table stores only:
    - profile name
    - memory id
    - embedding vector
    - entry type
    - active flag
    """

    def __init__(self, profile: str, *, database_url: str | None = None):
        self.profile = profile
        self.database_url = get_local_database_url(database_url)
        self._ensure_schema()

    def add(
        self,
        memory_id: str,
        vec: Iterable[float],
        *,
        entry_type: str = "memory",
        is_active: bool = True,
    ) -> None:
        vector = self._validate_and_normalize(vec)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO matriosha_local_vectors
                        (profile, memory_id, embedding, entry_type, active)
                    VALUES
                        (%s, %s, %s, %s, %s)
                    ON CONFLICT (profile, memory_id)
                    DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        entry_type = EXCLUDED.entry_type,
                        active = EXCLUDED.active,
                        updated_at = now()
                    """,
                    (self.profile, memory_id, vector.tolist(), entry_type, bool(is_active)),
                )

    def save(self) -> None:
        """Compatibility no-op for LocalVectorIndex callers."""

    def remove(self, memory_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM matriosha_local_vectors WHERE profile = %s AND memory_id = %s",
                    (self.profile, memory_id),
                )

    def set_active(self, memory_id: str, is_active: bool) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE matriosha_local_vectors
                    SET active = %s, updated_at = now()
                    WHERE profile = %s AND memory_id = %s
                    """,
                    (bool(is_active), self.profile, memory_id),
                )

    def get_vector(self, memory_id: str) -> np.ndarray | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT embedding::text
                    FROM matriosha_local_vectors
                    WHERE profile = %s AND memory_id = %s
                    """,
                    (self.profile, memory_id),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._parse_pgvector_text(str(row[0]))

    def get_meta(self, memory_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT memory_id, entry_type, active
                    FROM matriosha_local_vectors
                    WHERE profile = %s AND memory_id = %s
                    """,
                    (self.profile, memory_id),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {"memory_id": row[0], "entry_type": row[1], "active": bool(row[2])}

    def memory_ids(self) -> set[str]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT memory_id FROM matriosha_local_vectors WHERE profile = %s",
                    (self.profile,),
                )
                rows = cur.fetchall()
        return {str(row[0]) for row in rows}

    def active_vectors(self) -> dict[str, np.ndarray]:
        """Return active memory vectors for local clustering."""

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT memory_id, embedding::text
                    FROM matriosha_local_vectors
                    WHERE profile = %s AND active = true AND entry_type = 'memory'
                    """,
                    (self.profile,),
                )
                rows = cur.fetchall()
        return {str(memory_id): self._parse_pgvector_text(str(vector)) for memory_id, vector in rows}

    def search(
        self,
        q: Iterable[float],
        *,
        k: int = 5,
        include_inactive: bool = False,
        entry_types: set[str] | None = None,
        candidate_ids: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        if k < 1:
            return []

        query_vector = self._validate_and_normalize(q)
        where = ["profile = %s"]
        params: list[Any] = [self.profile]

        if not include_inactive:
            where.append("active = true")

        if entry_types is not None:
            if not entry_types:
                return []
            where.append("entry_type = ANY(%s)")
            params.append(list(entry_types))

        if candidate_ids is not None:
            if not candidate_ids:
                return []
            where.append("memory_id = ANY(%s)")
            params.append(list(candidate_ids))

        where_sql = " AND ".join(where)
        sql = f"""
            SELECT
                memory_id,
                1 - (embedding <=> %s::vector) AS score
            FROM matriosha_local_vectors
            WHERE {where_sql}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        vector = query_vector.tolist()
        final_params = [vector, *params, vector, int(k)]

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, final_params)
                rows = cur.fetchall()

        return [(str(memory_id), float(score)) for memory_id, score in rows]

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                vectorscale_available = False
                try:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE")
                    vectorscale_available = True
                except Exception:
                    conn.rollback()
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS matriosha_local_vectors (
                        profile text NOT NULL,
                        memory_id text NOT NULL,
                        embedding vector({_VECTOR_DIM}) NOT NULL,
                        entry_type text NOT NULL DEFAULT 'memory',
                        active boolean NOT NULL DEFAULT true,
                        created_at timestamptz NOT NULL DEFAULT now(),
                        updated_at timestamptz NOT NULL DEFAULT now(),
                        PRIMARY KEY (profile, memory_id)
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS matriosha_local_vectors_profile_active_idx
                    ON matriosha_local_vectors (profile, active)
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS matriosha_local_vectors_profile_entry_type_idx
                    ON matriosha_local_vectors (profile, entry_type)
                    """
                )

                index_mode = os.getenv(LOCAL_VECTOR_INDEX_ENV, "auto").strip().lower()
                if index_mode not in {"auto", "hnsw", "diskann"}:
                    raise ValueError(f"{LOCAL_VECTOR_INDEX_ENV} must be one of: auto, hnsw, diskann")

                if index_mode in {"auto", "diskann"} and vectorscale_available:
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS matriosha_local_vectors_embedding_diskann_idx
                        ON matriosha_local_vectors
                        USING diskann (embedding vector_cosine_ops)
                        """
                    )
                elif index_mode == "diskann":
                    raise RuntimeError(
                        "MATRIOSHA_LOCAL_VECTOR_INDEX=diskann requires the vectorscale extension. "
                        "Use a PostgreSQL image/database with pgvectorscale installed."
                    )
                else:
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS matriosha_local_vectors_embedding_hnsw_idx
                        ON matriosha_local_vectors
                        USING hnsw (embedding vector_cosine_ops)
                        """
                    )

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - dependency is optional
            raise RuntimeError(
                "Local pgvector backend requires installing Matriosha with the postgres extra: "
                "pip install 'matriosha[postgres]'"
            ) from exc

        return psycopg.connect(self.database_url)

    @staticmethod
    def _validate_and_normalize(vec: Iterable[float]) -> np.ndarray:
        arr = np.asarray(list(vec), dtype=np.float32)
        if arr.shape != (_VECTOR_DIM,):
            raise ValueError(f"expected vector dimension {_VECTOR_DIM}, got {arr.shape}")
        norm = float(np.linalg.norm(arr))
        if norm == 0.0:
            return arr
        return arr / norm

    @staticmethod
    def _parse_pgvector_text(value: str) -> np.ndarray:
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            stripped = stripped[1:-1]
        if not stripped:
            return np.zeros((_VECTOR_DIM,), dtype=np.float32)
        return np.asarray([float(part) for part in stripped.split(",")], dtype=np.float32)
