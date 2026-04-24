from __future__ import annotations

import base64
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
    monkeypatch.setattr(memory_cmd_module, "_resolve_passphrase", lambda **_kwargs: "correct-pass")


def test_managed_mode_corruption_restores_from_backup(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    Vault.init("default", "correct-pass")

    backup_objects: dict[str, bytes] = {}

    class _FakeBackupStore:
        bucket = "vault"

        @staticmethod
        def backup_key(memory_id: str) -> str:
            return f"{memory_id}.bin.b64.backup"

        def upload_backup(self, memory_id: str, payload_b64: bytes) -> str:
            key = self.backup_key(memory_id)
            backup_objects[key] = payload_b64
            return key

        def download_backup(self, memory_id: str) -> bytes:
            key = self.backup_key(memory_id)
            return backup_objects[key]

    import cli.commands.memory as memory_cmd_module

    monkeypatch.setattr(memory_cmd_module, "ManagedBackupStore", _FakeBackupStore)

    mode_set = runner.invoke(app, ["--json", "mode", "set", "managed"])
    assert mode_set.exit_code == 0

    remembered = runner.invoke(
        app,
        ["memory", "remember", "managed backup payload", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert remembered.exit_code == 0
    remembered_payload = json.loads(remembered.stdout)["data"]
    memory_id = remembered_payload["memory_id"]

    expected_key = f"{memory_id}.bin.b64.backup"
    assert remembered_payload["backup_key"] == expected_key
    assert expected_key in backup_objects

    store = LocalStore("default")
    store.replace_payload(memory_id, b"not-valid-base64")

    recalled = runner.invoke(
        app,
        ["memory", "recall", memory_id, "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert recalled.exit_code == 0
    data = json.loads(recalled.stdout)["data"]

    assert data["restored_from_backup"] is True
    assert data["integrity_warning"] is not None
    plaintext = base64.b64decode(data["plaintext_b64"]).decode("utf-8")
    assert plaintext == "managed backup payload"
