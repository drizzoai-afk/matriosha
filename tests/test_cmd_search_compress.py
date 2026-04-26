"""Command tests for `matriosha memory search` and `memory compress` (P3.2)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from matriosha.cli.main import app
from matriosha.core import config as config_module
from matriosha.core.storage_local import LocalStore
from matriosha.core.vault import Vault

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


def test_memory_search_empty_profile_requires_initialized_vault(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)

    result = runner.invoke(
        app,
        ["memory", "search", "nothing stored yet", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 20
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["title"] == "Vault not initialized"
    assert payload["category"] == "AUTH"
    assert payload["code"] == "AUTH-001"


def test_memory_search_ranks_similar_memories_top(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()
    similar_ids, _ = _seed_memories()

    result = runner.invoke(
        app,
        ["memory", "search", "project roadmap release milestones", "--k", "5", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)["data"]["results"]

    top_three = [row["memory_id"] for row in payload[:3]]
    assert set(top_three) == set(similar_ids)
    assert all("semantic" in row for row in payload)
    assert all("preview" in row for row in payload)


def test_memory_compress_creates_one_parent_for_three_similar(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()
    similar_ids, _ = _seed_memories()

    compress_result = runner.invoke(
        app,
        ["memory", "compress", "--threshold", "0.7", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert compress_result.exit_code == 0
    payload = json.loads(compress_result.stdout)
    assert payload["cluster_count"] == 1

    store = LocalStore("default")
    all_envs = store.list(limit=100)
    assert len(all_envs) == 6

    parents = [env for env in all_envs if env.children]
    assert len(parents) == 1

    parent = parents[0]
    assert set(parent.children or []) == set(similar_ids)
    assert "compressed" in parent.tags
    assert "parent" in parent.tags


def test_memory_compress_dry_run_creates_nothing(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()
    _seed_memories()

    store = LocalStore("default")
    before = store.list(limit=100)
    assert len(before) == 5

    dry_result = runner.invoke(
        app,
        ["memory", "compress", "--threshold", "0.7", "--dry-run", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert dry_result.exit_code == 0
    payload = json.loads(dry_result.stdout)
    assert payload["cluster_count"] == 1
    assert payload["dry_run"] is True

    after = store.list(limit=100)
    assert len(after) == 5
    assert all(env.children is None for env in after)


def test_top_level_compress_shortcut_uses_memory_compress(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()
    similar_ids, _ = _seed_memories()

    compress_result = runner.invoke(
        app,
        ["compress", "--threshold", "0.7", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert compress_result.exit_code == 0
    payload = json.loads(compress_result.stdout)
    assert payload["cluster_count"] == 1
    assert payload["deduplicate"] is True

    store = LocalStore("default")
    parents = [env for env in store.list(limit=100) if env.children]
    assert len(parents) == 1
    assert set(parents[0].children or []) == set(similar_ids)


def test_top_level_delete_shortcut_deletes_memory(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()
    memory_id = _remember("temporary memory to delete", tags=["tmp"])

    result = runner.invoke(
        app,
        ["delete", memory_id, "--yes", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["memory_id"] == memory_id
    assert payload["data"]["deleted"] == 1

    store = LocalStore("default")
    assert all(env.memory_id != memory_id for env in store.list(limit=100))


def _set_created_at(memory_id: str, created_at: str) -> None:
    store = LocalStore("default")
    env, payload = store.get(memory_id)
    env.created_at = created_at
    store.put(env, payload)


def test_memory_delete_older_than_deletes_only_old_memories(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    old_id = _remember("ancient archive note", tags=["old"])
    recent_id = _remember("fresh active note", tags=["new"])
    _set_created_at(old_id, "2001-01-01T00:00:00Z")

    result = runner.invoke(
        app,
        ["memory", "delete", "--older-than", "30", "--yes", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)["data"]
    assert payload["selector"]["type"] == "older_than"
    assert payload["deleted"] == 1
    assert payload["memory_ids"] == [old_id]

    remaining_ids = {env.memory_id for env in LocalStore("default").list(limit=100)}
    assert old_id not in remaining_ids
    assert recent_id in remaining_ids


def test_top_level_delete_older_than_shortcut(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    old_id = _remember("old shortcut delete note", tags=["old"])
    _set_created_at(old_id, "2001-01-01T00:00:00Z")

    result = runner.invoke(
        app,
        ["delete", "--older-than", "30", "--yes", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)["data"]
    assert payload["deleted"] == 1
    assert payload["memory_ids"] == [old_id]


def test_memory_delete_query_deletes_semantic_matches(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()
    similar_ids, distinct_ids = _seed_memories()

    result = runner.invoke(
        app,
        ["memory", "delete", "--query", "project roadmap release milestones", "--threshold", "0.7", "--yes", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)["data"]
    assert payload["selector"]["type"] == "query"
    assert payload["deleted"] == 3
    assert set(payload["memory_ids"]) == set(similar_ids)

    remaining_ids = {env.memory_id for env in LocalStore("default").list(limit=100)}
    assert not set(similar_ids) & remaining_ids
    assert set(distinct_ids) <= remaining_ids


def test_memory_delete_requires_exactly_one_selector(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    result = runner.invoke(
        app,
        ["memory", "delete", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["code"] == "VAL-004"


def test_memory_delete_bulk_json_requires_yes(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()
    old_id = _remember("old unsafe delete note", tags=["old"])
    _set_created_at(old_id, "2001-01-01T00:00:00Z")

    result = runner.invoke(
        app,
        ["memory", "delete", "--older-than", "30", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["code"] == "VAL-004"

    remaining_ids = {env.memory_id for env in LocalStore("default").list(limit=100)}
    assert old_id in remaining_ids
