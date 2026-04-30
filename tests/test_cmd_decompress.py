"""Command tests for `matriosha memory decompress` (P3.3)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from matriosha.cli.main import app
from matriosha.core import config as config_module
from matriosha.core.binary_protocol import decode_envelope, encode_envelope
from matriosha.core.storage_local import LocalStore
from matriosha.core.vault import Vault
from matriosha.core.vectors import get_default_embedder

runner = CliRunner()


def _patch_dirs(monkeypatch, tmp_path):
    config_root = tmp_path / ".config" / "matriosha"
    data_root = tmp_path / ".local" / "share" / "matriosha"

    monkeypatch.setattr(config_module.platformdirs, "user_config_dir", lambda appname: str(config_root))

    import matriosha.cli.commands.memory as memory_cmd_module
    import matriosha.core.storage_local as store_module
    import matriosha.core.vault as vault_module
    import matriosha.core.vectors as vectors_module

    monkeypatch.setattr(vault_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(store_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(vectors_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(memory_cmd_module, "_resolve_passphrase", lambda **_kwargs: "correct-pass")


def _init_vault() -> None:
    Vault.init("default", "correct-pass")


def _remember(text: str, *, tags: list[str] | None = None) -> str:
    args = ["memory", "remember", text, "--json"]
    for tag in tags or []:
        args.extend(["--tag", tag])

    result = runner.invoke(app, args, env={"MATRIOSHA_PASSPHRASE": "correct-pass"})
    assert result.exit_code == 0
    return json.loads(result.stdout)["data"]["memory_id"]


def _seed_memories() -> tuple[list[str], list[str]]:
    similar_ids = [
        _remember("project roadmap milestones and release plan", tags=["work"]),
        _remember("project roadmap milestones and release planning", tags=["work"]),
        _remember("project roadmap milestones for release plan", tags=["work"]),
    ]
    distinct_ids = [
        _remember("grocery list apples bananas milk", tags=["home"]),
        _remember("weather forecast heavy rain tomorrow", tags=["home"]),
    ]
    return similar_ids, distinct_ids


def _compress_cluster() -> tuple[str, list[str]]:
    result = runner.invoke(
        app,
        ["memory", "compress", "--threshold", "0.7", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert result.exit_code == 0

    payload = json.loads(result.stdout)
    assert payload["cluster_count"] == 1
    parent = payload["created_parents"][0]
    return parent["parent_id"], parent["children"]


def test_memory_decompress_restores_children_and_deletes_parent(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()
    _seed_memories()

    parent_id, children = _compress_cluster()

    result = runner.invoke(
        app,
        ["memory", "decompress", parent_id, "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert result.exit_code == 0

    payload = json.loads(result.stdout)
    assert set(payload["restored"]) == set(children)
    assert payload["parent_deleted"] is True

    store = LocalStore("default")
    all_ids = {env.memory_id for env in store.list(limit=100)}
    assert parent_id not in all_ids

    for child_id in children:
        recall = runner.invoke(
            app,
            ["memory", "recall", child_id, "--json"],
            env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
        )
        assert recall.exit_code == 0


def test_memory_decompress_refuses_when_child_similarity_below_threshold(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()
    _seed_memories()

    parent_id, children = _compress_cluster()
    tampered_id = children[0]

    vault = Vault.unlock("default", "correct-pass")
    store = LocalStore("default", data_key=vault.data_key)

    original_env, _ = store.get(tampered_id)
    tampered_plaintext = b"completely unrelated tampered payload for integrity failure"
    tampered_env, tampered_payload = encode_envelope(
        tampered_plaintext,
        vault.data_key,
        mode=original_env.mode,
        tags=original_env.tags,
        source=original_env.source,
    )
    tampered_env.memory_id = original_env.memory_id
    tampered_env.created_at = original_env.created_at

    tampered_embedding = get_default_embedder().embed(tampered_plaintext.decode("utf-8", errors="replace"))
    store.put(tampered_env, tampered_payload, embedding=tampered_embedding, embedding_kind="memory", is_active=True)

    result = runner.invoke(
        app,
        ["memory", "decompress", parent_id, "--min-similarity", "0.9"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert result.exit_code == 10
    assert tampered_id in result.stdout

    parent_env, parent_payload = store.get(parent_id)
    parent_plaintext = decode_envelope(parent_env, parent_payload, vault.data_key)
    assert len(parent_plaintext) > 0


def test_memory_decompress_keep_parent_flag(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()
    _seed_memories()

    parent_id, children = _compress_cluster()

    result = runner.invoke(
        app,
        ["memory", "decompress", parent_id, "--keep-parent", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert result.exit_code == 0

    payload = json.loads(result.stdout)
    assert set(payload["restored"]) == set(children)
    assert payload["parent_deleted"] is False

    store = LocalStore("default")
    kept_parent_env, _ = store.get(parent_id)
    assert kept_parent_env.memory_id == parent_id
