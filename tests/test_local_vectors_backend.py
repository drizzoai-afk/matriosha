from __future__ import annotations

import pytest


def test_resolve_local_vector_backend_defaults_to_pgvector(monkeypatch) -> None:
    from matriosha.core.local_pgvector import resolve_local_vector_backend

    monkeypatch.delenv("MATRIOSHA_LOCAL_VECTOR_BACKEND", raising=False)

    assert resolve_local_vector_backend() == "pgvector"


def test_resolve_local_vector_backend_accepts_pgvector_aliases() -> None:
    from matriosha.core.local_pgvector import resolve_local_vector_backend

    assert resolve_local_vector_backend("pg") == "pgvector"
    assert resolve_local_vector_backend("postgres") == "pgvector"
    assert resolve_local_vector_backend("postgresql") == "pgvector"
    assert resolve_local_vector_backend("pgvector") == "pgvector"


def test_resolve_local_vector_backend_rejects_unknown() -> None:
    from matriosha.core.local_pgvector import resolve_local_vector_backend

    with pytest.raises(ValueError, match="MATRIOSHA_LOCAL_VECTOR_BACKEND"):
        resolve_local_vector_backend("sqlite")


def test_get_local_vector_index_explicit_npz_uses_legacy_file_backend(
    monkeypatch, tmp_path
) -> None:
    from matriosha.core.local_vectors import get_local_vector_index
    from matriosha.core.vectors import LocalVectorIndex

    monkeypatch.setenv("MATRIOSHA_LOCAL_VECTOR_BACKEND", "npz")
    monkeypatch.setenv("MATRIOSHA_HOME", str(tmp_path))

    index = get_local_vector_index("default", data_key=None)

    assert isinstance(index, LocalVectorIndex)


def test_pgvector_backend_uses_default_local_db_when_env_missing(monkeypatch) -> None:
    import matriosha.core.local_pgvector as local_pgvector
    import matriosha.core.local_vectors as local_vectors
    from matriosha.core.local_db import DEFAULT_LOCAL_DATABASE_URL

    class FakePgVectorIndex:
        profile: str
        database_url: str

        def __init__(self, profile: str):
            self.profile = profile
            self.database_url = DEFAULT_LOCAL_DATABASE_URL

    monkeypatch.setenv("MATRIOSHA_LOCAL_VECTOR_BACKEND", "pgvector")
    monkeypatch.delenv("MATRIOSHA_LOCAL_DATABASE_URL", raising=False)
    monkeypatch.setenv("MATRIOSHA_LOCAL_DB_AUTO_START", "0")
    monkeypatch.setattr(local_pgvector, "LocalPgVectorIndex", FakePgVectorIndex)

    index = local_vectors.get_local_vector_index("default", data_key=None)

    assert isinstance(index, FakePgVectorIndex)
    assert index.profile == "default"
    assert index.database_url == DEFAULT_LOCAL_DATABASE_URL


def test_pgvector_backend_uses_remote_database_url_without_docker(monkeypatch) -> None:
    import matriosha.core.local_pgvector as local_pgvector
    import matriosha.core.local_vectors as local_vectors

    remote_url = "postgresql://matriosha:secret@example.com:5432/matriosha"

    class FakePgVectorIndex:
        profile: str
        database_url: str

        def __init__(self, profile: str):
            self.profile = profile
            self.database_url = local_pgvector.get_local_database_url()

    monkeypatch.setenv("MATRIOSHA_LOCAL_VECTOR_BACKEND", "pgvector")
    monkeypatch.setenv("MATRIOSHA_LOCAL_DATABASE_URL", remote_url)
    monkeypatch.setenv("MATRIOSHA_LOCAL_DB_AUTO_START", "0")
    monkeypatch.setattr(local_pgvector, "LocalPgVectorIndex", FakePgVectorIndex)

    index = local_vectors.get_local_vector_index("default", data_key=None)

    assert isinstance(index, FakePgVectorIndex)
    assert index.profile == "default"
    assert index.database_url == remote_url
