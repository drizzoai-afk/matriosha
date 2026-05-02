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


def test_local_vector_index_content_vector_beats_metadata_noise(monkeypatch, tmp_path) -> None:
    _patch_data_dir(monkeypatch, tmp_path)
    idx = LocalVectorIndex("default")

    query = np.zeros(384, dtype=np.float32)
    query[0] = 1.0

    content_vec = np.zeros(384, dtype=np.float32)
    content_vec[0] = 1.0

    metadata_vec = np.zeros(384, dtype=np.float32)
    metadata_vec[1] = 1.0

    idx.add("content-memory", content_vec)
    idx.add("metadata-noise", metadata_vec)

    results = idx.search(query, k=2)

    assert [memory_id for memory_id, _ in results] == ["content-memory", "metadata-noise"]
    assert results[0][1] > results[1][1]


def test_local_vector_index_encrypted_persist_reload(monkeypatch, tmp_path) -> None:
    data_root = _patch_data_dir(monkeypatch, tmp_path)
    data_key = b"k" * 32

    embedder = HashEmbedder()
    idx = LocalVectorIndex("default", data_key=data_key)
    idx.add("secret", embedder.embed("secret semantic text"))
    idx.save()

    profile_dir = data_root / "default"
    assert (profile_dir / "vectors.npz.enc").exists()
    assert (profile_dir / "ids.json.enc").exists()
    assert (profile_dir / "vector_meta.json.enc").exists()
    assert not (profile_dir / "vectors.npz").exists()
    assert not (profile_dir / "ids.json").exists()
    assert not (profile_dir / "vector_meta.json").exists()
    assert b"secret" not in (profile_dir / "ids.json.enc").read_bytes()

    reloaded = LocalVectorIndex("default", data_key=data_key)
    results = reloaded.search(embedder.embed("secret semantic text"), k=1)

    assert results[0][0] == "secret"


def test_local_vector_index_encrypted_files_require_key(monkeypatch, tmp_path) -> None:
    _patch_data_dir(monkeypatch, tmp_path)

    idx = LocalVectorIndex("default", data_key=b"k" * 32)
    idx.add("secret", HashEmbedder().embed("secret semantic text"))
    idx.save()

    try:
        LocalVectorIndex("default")
    except ValueError as exc:
        assert "data key required" in str(exc)
    else:
        raise AssertionError("encrypted vector index should require data key")


def test_local_vector_index_with_key_can_read_legacy_plaintext(monkeypatch, tmp_path) -> None:
    _patch_data_dir(monkeypatch, tmp_path)

    embedder = HashEmbedder()
    legacy = LocalVectorIndex("default")
    legacy.add("legacy", embedder.embed("legacy semantic text"))
    legacy.save()

    reloaded = LocalVectorIndex("default", data_key=b"k" * 32)
    results = reloaded.search(embedder.embed("legacy semantic text"), k=1)

    assert results[0][0] == "legacy"

    reloaded.save()
    profile_dir = tmp_path / ".local" / "share" / "matriosha" / "default"
    assert (profile_dir / "vectors.npz.enc").exists()


def test_search_can_filter_candidate_ids(tmp_path, monkeypatch):
    _patch_data_dir(monkeypatch, tmp_path)
    embedder = HashEmbedder()
    idx = LocalVectorIndex("test")

    idx.add("alpha-id", embedder.embed("alpha document"))
    idx.add("beta-id", embedder.embed("beta document"))

    results = idx.search(
        embedder.embed("alpha document"),
        k=5,
        candidate_ids={"beta-id"},
    )

    assert [memory_id for memory_id, _ in results] == ["beta-id"]
