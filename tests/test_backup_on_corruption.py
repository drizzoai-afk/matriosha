from __future__ import annotations

import base64
import json

from typer.testing import CliRunner

from cli.main import app
from core import config as config_module
from core.storage_local import LocalStore
from core.vault import Vault
from core.binary_protocol import decode_envelope as decode_envelope_impl
from core.crypto import IntegrityError

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


def _remember(text: str) -> str:
    remembered = runner.invoke(
        app,
        ["memory", "remember", text, "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert remembered.exit_code == 0, remembered.stdout
    return json.loads(remembered.stdout)["data"]["memory_id"]


def test_local_corruption_emits_warning_enriched_recall(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    Vault.init("default", "correct-pass")

    memory_id = _remember("local corruption payload")

    store = LocalStore("default")
    env_path, _ = store._memory_paths(memory_id)  # noqa: SLF001
    env_payload = json.loads(env_path.read_text(encoding="utf-8"))
    env_payload["merkle_root"] = "ff" * 32
    env_path.write_text(json.dumps(env_payload, separators=(",", ":")), encoding="utf-8")

    recalled = runner.invoke(
        app,
        ["memory", "recall", memory_id, "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert recalled.exit_code == 0, recalled.stdout
    payload = json.loads(recalled.stdout)["data"]

    assert payload["restored_from_backup"] is False
    assert payload["plaintext_b64"] is None
    assert payload["integrity_warning"]
    assert "Merkle corruption detected" in payload["integrity_warning"]
    assert payload["semantic"]["warnings"]


def test_managed_corruption_uses_backup_only_after_merkle_detection(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    Vault.init("default", "correct-pass")

    backup_objects: dict[str, bytes] = {}
    upload_calls: list[str] = []
    download_calls: list[str] = []

    class _FakeBackupStore:
        bucket = "vault"

        @staticmethod
        def backup_key(memory_id: str) -> str:
            return f"{memory_id}.bin.b64.backup"

        def upload_backup(self, memory_id: str, payload_b64: bytes) -> str:
            key = self.backup_key(memory_id)
            backup_objects[key] = payload_b64
            upload_calls.append(memory_id)
            return key

        def download_backup(self, memory_id: str) -> bytes:
            key = self.backup_key(memory_id)
            download_calls.append(memory_id)
            return backup_objects[key]

    import cli.commands.memory as memory_cmd_module

    monkeypatch.setattr(memory_cmd_module, "ManagedBackupStore", _FakeBackupStore)

    mode_set = runner.invoke(app, ["--json", "mode", "set", "managed"])
    assert mode_set.exit_code == 0, mode_set.stdout

    merkle_memory_id = _remember("managed backup payload")
    expected_key = f"{merkle_memory_id}.bin.b64.backup"
    assert expected_key in backup_objects
    assert upload_calls == [merkle_memory_id]

    store = LocalStore("default")

    _, payload_path = store._memory_paths(merkle_memory_id)  # noqa: SLF001
    payload_path.write_bytes(b"corrupted-merkle-payload")

    def _decode_with_forced_merkle(env, b64_payload, key):  # noqa: ANN001
        if b64_payload == b"corrupted-merkle-payload":
            raise IntegrityError("Merkle root mismatch")
        return decode_envelope_impl(env, b64_payload, key)

    monkeypatch.setattr(memory_cmd_module, "decode_envelope", _decode_with_forced_merkle)

    recalled_merkle = runner.invoke(
        app,
        ["memory", "recall", merkle_memory_id, "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert recalled_merkle.exit_code == 0, recalled_merkle.stdout
    merkle_payload = json.loads(recalled_merkle.stdout)["data"]

    assert merkle_payload["restored_from_backup"] is True
    assert "restored from managed backup" in str(merkle_payload["integrity_warning"])
    assert download_calls == [merkle_memory_id]
    assert base64.b64decode(merkle_payload["plaintext_b64"]).decode("utf-8") == "managed backup payload"

    monkeypatch.setattr(memory_cmd_module, "decode_envelope", decode_envelope_impl)

    non_merkle_memory_id = _remember("base64 corruption payload")
    assert upload_calls == [merkle_memory_id, non_merkle_memory_id]

    store.replace_payload(non_merkle_memory_id, b"not-valid-base64")

    recalled_non_merkle = runner.invoke(
        app,
        ["memory", "recall", non_merkle_memory_id, "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert recalled_non_merkle.exit_code == 0, recalled_non_merkle.stdout
    non_merkle_payload = json.loads(recalled_non_merkle.stdout)["data"]

    assert non_merkle_payload["restored_from_backup"] is False
    assert non_merkle_payload["plaintext_b64"] is None
    assert "Payload is not valid base64" in str(non_merkle_payload["integrity_warning"])
    assert download_calls == [merkle_memory_id]
