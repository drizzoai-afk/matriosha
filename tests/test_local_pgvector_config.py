from __future__ import annotations

from matriosha.core.local_db import DEFAULT_LOCAL_DATABASE_URL
from matriosha.core.local_pgvector import get_local_database_url


def test_get_local_database_url_uses_explicit_value(monkeypatch) -> None:
    monkeypatch.delenv("MATRIOSHA_LOCAL_DATABASE_URL", raising=False)

    assert get_local_database_url("postgresql://custom/db") == "postgresql://custom/db"


def test_get_local_database_url_uses_env_value(monkeypatch) -> None:
    monkeypatch.setenv("MATRIOSHA_LOCAL_DATABASE_URL", "postgresql://env/db")

    assert get_local_database_url() == "postgresql://env/db"


def test_get_local_database_url_auto_starts_default_when_missing(monkeypatch) -> None:
    import matriosha.core.local_pgvector as local_pgvector

    monkeypatch.delenv("MATRIOSHA_LOCAL_DATABASE_URL", raising=False)
    monkeypatch.setenv("MATRIOSHA_LOCAL_DB_AUTO_START", "1")
    monkeypatch.setattr(
        local_pgvector, "ensure_default_local_pgvector", lambda: DEFAULT_LOCAL_DATABASE_URL
    )

    assert get_local_database_url() == DEFAULT_LOCAL_DATABASE_URL


def test_get_local_database_url_returns_default_when_auto_start_disabled(monkeypatch) -> None:
    monkeypatch.delenv("MATRIOSHA_LOCAL_DATABASE_URL", raising=False)
    monkeypatch.setenv("MATRIOSHA_LOCAL_DB_AUTO_START", "0")

    assert get_local_database_url() == DEFAULT_LOCAL_DATABASE_URL
