"""Command tests for memory recall/list/delete lifecycle."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from matriosha.cli.main import app
from matriosha.core import config as config_module
from matriosha.core.vault import Vault

runner = CliRunner()


def _patch_dirs(monkeypatch, tmp_path):
    config_root = tmp_path / ".config" / "matriosha"
    data_root = tmp_path / ".local" / "share" / "matriosha"

    monkeypatch.setattr(config_module.platformdirs, "user_config_dir", lambda appname: str(config_root))

    import matriosha.cli.commands.memory as memory_cmd_module
    import matriosha.core.audit as audit_module
    import matriosha.core.storage_local as store_module
    import matriosha.core.vault as vault_module

    monkeypatch.setattr(vault_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(store_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(audit_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(memory_cmd_module, "_resolve_passphrase", lambda **_kwargs: "correct-pass")
    return config_root, data_root


def _init_vault() -> None:
    Vault.init("default", "correct-pass")


def test_memory_recall_empty_profile_requires_initialized_vault(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)

    result = runner.invoke(
        app,
        ["memory", "recall", "00000000-0000-4000-8000-000000000000", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 20
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["title"] == "Vault not initialized"
    assert payload["category"] == "AUTH"
    assert payload["code"] == "AUTH-001"


def test_memory_recall_list_delete_roundtrip(monkeypatch, tmp_path) -> None:
    _, data_root = _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    remember = runner.invoke(
        app,
        ["memory", "remember", "hello-memory", "--tag", "unit", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert remember.exit_code == 0
    memory_id = json.loads(remember.stdout)["data"]["memory_id"]
    audit_path = data_root / "default" / "audit" / "events.jsonl"
    assert audit_path.exists()
    audit_record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert audit_record["action"] == "memory.remember"
    assert audit_record["target_id"] == memory_id
    assert audit_record["outcome"] == "success"
    assert audit_record["metadata"]["bytes"] == len("hello-memory")

    recall = runner.invoke(app, ["memory", "recall", memory_id], env={"MATRIOSHA_PASSPHRASE": "correct-pass"})
    assert recall.exit_code == 0
    assert recall.stdout.strip() == "hello-memory"

    recall_json = runner.invoke(
        app,
        ["memory", "recall", memory_id, "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert recall_json.exit_code == 0
    recall_payload = json.loads(recall_json.stdout)["data"]
    assert recall_payload["semantic"]["kind"] == "text"
    assert recall_payload["preview"]
    assert recall_payload["integrity_warning"] is None

    list_result = runner.invoke(app, ["memory", "list", "--json"], env={"MATRIOSHA_PASSPHRASE": "correct-pass"})
    assert list_result.exit_code == 0
    memories = json.loads(list_result.stdout)["data"]["items"]
    assert any(entry["memory_id"] == memory_id for entry in memories)

    delete_result = runner.invoke(app, ["memory", "delete", memory_id, "--yes", "--json"], env={"MATRIOSHA_PASSPHRASE": "correct-pass"})
    assert delete_result.exit_code == 0
    assert json.loads(delete_result.stdout)["data"]["deleted"] == 1

    recall_missing = runner.invoke(app, ["memory", "recall", memory_id, "--json"], env={"MATRIOSHA_PASSPHRASE": "correct-pass"})
    assert recall_missing.exit_code == 2


def test_memory_recall_local_corruption_returns_warning(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    remember = runner.invoke(
        app,
        ["memory", "remember", "corruption-case", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert remember.exit_code == 0
    memory_id = json.loads(remember.stdout)["data"]["memory_id"]

    import matriosha.core.storage_local as store_module

    store = store_module.LocalStore("default")
    env_path, _ = store._memory_paths(memory_id)  # noqa: SLF001
    env_payload = json.loads(env_path.read_text(encoding="utf-8"))
    env_payload["merkle_root"] = "00" * 32
    env_path.write_text(json.dumps(env_payload, separators=(",", ":")), encoding="utf-8")

    recalled = runner.invoke(
        app,
        ["memory", "recall", memory_id, "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert recalled.exit_code == 0
    payload = json.loads(recalled.stdout)["data"]
    assert payload["integrity_warning"]
    assert payload["plaintext_b64"] is None
    assert payload["semantic"]["warnings"]
