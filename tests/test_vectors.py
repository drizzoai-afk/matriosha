"""Tests for local embedding and vector index behavior."""

from __future__ import annotations

import numpy as np

from matriosha.core.vectors import HashEmbedder, LocalVectorIndex


def _patch_data_dir(monkeypatch, tmp_path):
    data_root = tmp_path / ".local" / "share" / "matriosha"
    monkeypatch.setattr(
        "matriosha.core.vectors.platformdirs.user_data_dir",
        lambda appname: str(
            data_root if appname == "matriosha" else tmp_path / ".local" / "share" / appname
        ),
    )
    return data_root


def test_hash_embedder_deterministic_and_normalized() -> None:
    embedder = HashEmbedder()

    first = embedder.embed("x")
    second = embedder.embed("x")

    assert np.array_equal(first, second)
    assert np.isclose(float(np.linalg.norm(first)), 1.0, atol=1e-6)


def test_local_vector_index_add_and_search_identical_query(monkeypatch, tmp_path) -> None:
    _patch_data_dir(monkeypatch, tmp_path)
    idx = LocalVectorIndex("default")

    vec = HashEmbedder().embed("hello world")
    idx.add("m1", vec)

    results = idx.search(vec, k=1)

    assert len(results) == 1
    memory_id, sim = results[0]
    assert memory_id == "m1"
    assert np.isclose(sim, 1.0, atol=1e-6)


def test_local_vector_index_persist_reload(monkeypatch, tmp_path) -> None:
    _patch_data_dir(monkeypatch, tmp_path)

    embedder = HashEmbedder()
    idx = LocalVectorIndex("default")
    idx.add("a", embedder.embed("alpha"))
    idx.add("b", embedder.embed("beta"))
    idx.save()

    reloaded = LocalVectorIndex("default")
    results = reloaded.search(embedder.embed("alpha"), k=5)

    assert {memory_id for memory_id, _ in results} == {"a", "b"}
    assert results[0][0] == "a"


def test_local_vector_index_remove(monkeypatch, tmp_path) -> None:
    _patch_data_dir(monkeypatch, tmp_path)

    embedder = HashEmbedder()
    idx = LocalVectorIndex("default")
    vec = embedder.embed("to remove")

    idx.add("to-delete", vec)
    assert idx.search(vec, k=1)[0][0] == "to-delete"

    idx.remove("to-delete")
    assert idx.search(vec, k=1) == []
