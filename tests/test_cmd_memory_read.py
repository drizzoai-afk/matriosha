"""Command tests for memory recall/list/delete lifecycle."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from cli.main import app
from core import config as config_module
from core.vault import Vault

runner = CliRunner()


def _patch_dirs(monkeypatch, tmp_path):
    config_root = tmp_path / ".config" / "matriosha"
    data_root = tmp_path / ".local" / "share" / "matriosha"

    monkeypatch.setattr(config_module.platformdirs, "user_config_dir", lambda appname: str(config_root))

    import cli.commands.memory as memory_cmd_module
    import core.storage_local as store_module
    import core.vault as vault_module

    monkeypatch.setattr(vault_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(store_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(memory_cmd_module, "_resolve_passphrase", lambda: "correct-pass")

    return config_root, data_root


def _init_vault() -> None:
    Vault.init("default", "correct-pass")


def test_memory_recall_list_delete_roundtrip(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    remember = runner.invoke(
        app,
        ["memory", "remember", "hello-memory", "--tag", "unit", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert remember.exit_code == 0
    memory_id = json.loads(remember.stdout)["data"]["memory_id"]

    recall = runner.invoke(app, ["memory", "recall", memory_id], env={"MATRIOSHA_PASSPHRASE": "correct-pass"})
    assert recall.exit_code == 0
    assert recall.stdout == "hello-memory"

    list_result = runner.invoke(app, ["memory", "list", "--json"], env={"MATRIOSHA_PASSPHRASE": "correct-pass"})
    assert list_result.exit_code == 0
    memories = json.loads(list_result.stdout)["data"]["items"]
    assert any(entry["memory_id"] == memory_id for entry in memories)

    delete_result = runner.invoke(app, ["memory", "delete", memory_id, "--yes", "--json"])
    assert delete_result.exit_code == 0
    assert json.loads(delete_result.stdout)["data"]["deleted"] == 1

    recall_missing = runner.invoke(app, ["memory", "recall", memory_id, "--json"], env={"MATRIOSHA_PASSPHRASE": "correct-pass"})
    assert recall_missing.exit_code == 2
