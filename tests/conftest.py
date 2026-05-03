from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _use_legacy_npz_vector_backend_for_unit_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests use the legacy file vector backend unless a test overrides it.

    Production defaults to local PostgreSQL/pgvector. This fixture keeps existing
    unit tests independent from a local PostgreSQL service.
    """

    monkeypatch.setenv("MATRIOSHA_LOCAL_VECTOR_BACKEND", "npz")
