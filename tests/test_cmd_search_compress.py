"""Command tests for `matriosha memory search` and `memory compress` (P3.2)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from cli.main import app
from core import config as config_module
from core.storage_local import LocalStore
from core.vault import Vault

runner = CliRunner()


def _patch_dirs(monkeypatch, tmp_path):
    config_root = tmp_path / ".config" / "matriosha"
    data_root = tmp_path / ".local" / "share" / "matriosha"

    monkeypatch.setattr(config_module.platformdirs, "user_config_dir", lambda appname: str(config_root))

    import cli.commands.memory as memory_cmd_module
    import core.storage_local as store_module
    import core.vault as vault_module
    import core.vectors as vectors_module

    monkeypatch.setattr(vault_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(store_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(vectors_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(memory_cmd_module, "_resolve_passphrase", lambda: "correct-pass")


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
