from __future__ import annotations


class FakeIndex:
    def memory_ids(self) -> set[str]:
        return {"mem-1", "mem-2"}


def test_check_local_vector_index_pgvector_ok(monkeypatch) -> None:
    import matriosha.core.diagnostics as diagnostics

    monkeypatch.setattr(diagnostics, "resolve_local_vector_backend", lambda: "pgvector")
    monkeypatch.setattr(diagnostics, "get_local_vector_index", lambda *_args, **_kwargs: FakeIndex())

    result = diagnostics._check_local_vector_index(profile_name="default", data_key=None)

    assert result.name == "vector.index"
    assert result.status == "ok"
    assert "local pgvector index reachable" in result.detail
    assert "2 vector" in result.detail


def test_check_local_vector_index_npz_warns_legacy(monkeypatch) -> None:
    import matriosha.core.diagnostics as diagnostics

    monkeypatch.setattr(diagnostics, "resolve_local_vector_backend", lambda: "npz")
    monkeypatch.setattr(diagnostics, "get_local_vector_index", lambda *_args, **_kwargs: FakeIndex())

    result = diagnostics._check_local_vector_index(profile_name="default", data_key=None)

    assert result.name == "vector.index"
    assert result.status == "warn"
    assert "legacy npz vector backend" in result.detail


def test_check_local_vector_index_pgvector_missing_url(monkeypatch) -> None:
    import matriosha.core.diagnostics as diagnostics

    monkeypatch.setattr(diagnostics, "resolve_local_vector_backend", lambda: "pgvector")

    def fail_missing_url(*_args, **_kwargs):
        raise ValueError("MATRIOSHA_LOCAL_DATABASE_URL is required when using pgvector backend")

    monkeypatch.setattr(diagnostics, "get_local_vector_index", fail_missing_url)

    result = diagnostics._check_local_vector_index(profile_name="default", data_key=None)

    assert result.name == "vector.index"
    assert result.status == "fail"
    assert "MATRIOSHA_LOCAL_DATABASE_URL" in result.detail
