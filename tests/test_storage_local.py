"""Tests for local filesystem storage backend."""

from __future__ import annotations

import json
import os
import stat

import pytest

from core.binary_protocol import MemoryEnvelope, encode_envelope
from core.crypto import derive_key, generate_salt
from core.storage_local import LocalStore


def _patch_data_dir(monkeypatch, tmp_path):
    data_root = tmp_path / ".local" / "share" / "matriosha"
    monkeypatch.setattr(
        "core.storage_local.platformdirs.user_data_dir",
        lambda appname: str(data_root if appname == "matriosha" else tmp_path / ".local" / "share" / appname),
    )
    return data_root


def _key() -> bytes:
    return derive_key("storage-local-tests", generate_salt())


def test_put_get_roundtrip(monkeypatch, tmp_path) -> None:
    _patch_data_dir(monkeypatch, tmp_path)
    store = LocalStore("default")

    key = _key()
    env, payload = encode_envelope(b"roundtrip", key, mode="local", tags=["unit"])

    stored_path = store.put(env, payload)
    loaded_env, loaded_payload = store.get(env.memory_id)

    assert stored_path.exists()
    assert loaded_env == env
    assert loaded_payload == payload


def test_list_filters_by_tag(monkeypatch, tmp_path) -> None:
    _patch_data_dir(monkeypatch, tmp_path)
    store = LocalStore("default")

    key = _key()
    env_work, payload_work = encode_envelope(b"work", key, mode="local", tags=["work"])
    env_home, payload_home = encode_envelope(b"home", key, mode="local", tags=["home"])
    store.put(env_work, payload_work)
    store.put(env_home, payload_home)

    work_only = store.list(tag="work")

    assert len(work_only) == 1
    assert work_only[0].memory_id == env_work.memory_id


def test_delete_removes_files_and_index_entry(monkeypatch, tmp_path) -> None:
    _patch_data_dir(monkeypatch, tmp_path)
    store = LocalStore("default")

    key = _key()
    env, payload = encode_envelope(b"delete me", key, mode="local", tags=["cleanup"])
    store.put(env, payload)

    env_path = store.root / "memories" / f"{env.memory_id}.env.json"
    payload_path = store.root / "memories" / f"{env.memory_id}.bin.b64"

    assert store.delete(env.memory_id) is True
    assert not env_path.exists()
    assert not payload_path.exists()

    index = json.loads((store.root / "index.json").read_text(encoding="utf-8"))
    assert env.memory_id not in index


def test_verify_true_then_false_after_tampering(monkeypatch, tmp_path) -> None:
    _patch_data_dir(monkeypatch, tmp_path)
    store = LocalStore("default")

    key = _key()
    env, payload = encode_envelope(b"verify me", key, mode="local", tags=["verify"])
    store.put(env, payload)

    assert store.verify(env.memory_id, key) is True

    payload_path = store.root / "memories" / f"{env.memory_id}.bin.b64"
    tampered = bytearray(payload_path.read_bytes())
    tampered[-1] = ord("A") if tampered[-1] != ord("A") else ord("B")
    payload_path.write_bytes(bytes(tampered))

    assert store.verify(env.memory_id, key) is False


def test_path_traversal_memory_id_rejected(monkeypatch, tmp_path) -> None:
    _patch_data_dir(monkeypatch, tmp_path)
    store = LocalStore("default")

    key = _key()
    valid_env, payload = encode_envelope(b"x", key, mode="local", tags=["ok"])
    bad_env = MemoryEnvelope(
        memory_id="../evil",
        mode=valid_env.mode,
        encoding=valid_env.encoding,
        hash_algo=valid_env.hash_algo,
        merkle_leaves=valid_env.merkle_leaves,
        merkle_root=valid_env.merkle_root,
        vector_dim=valid_env.vector_dim,
        created_at=valid_env.created_at,
        tags=valid_env.tags,
        source=valid_env.source,
    )

    with pytest.raises(ValueError):
        store.put(bad_env, payload)

    with pytest.raises(ValueError):
        store.get("../evil")


def test_permissions_0600_on_unix(monkeypatch, tmp_path) -> None:
    _patch_data_dir(monkeypatch, tmp_path)
    store = LocalStore("default")

    key = _key()
    env, payload = encode_envelope(b"perms", key, mode="local", tags=["perm"])
    store.put(env, payload)

    env_path = store.root / "memories" / f"{env.memory_id}.env.json"
    payload_path = store.root / "memories" / f"{env.memory_id}.bin.b64"

    if os.name != "nt":
        assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(payload_path.stat().st_mode) == 0o600
