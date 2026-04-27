"""Tests for Phase 2.5 vault initialization and unlock behavior."""

from __future__ import annotations

import json
import os
import stat

from typer.testing import CliRunner

from matriosha.cli.main import app
from matriosha.core import audit as audit_module
from matriosha.core import config as config_module
from matriosha.core.vault import AuthError, Vault, VaultAlreadyInitializedError

runner = CliRunner()


def _patch_dirs(monkeypatch, tmp_path):
    config_root = tmp_path / ".config" / "matriosha"
    data_root = tmp_path / ".local" / "share" / "matriosha"

    monkeypatch.setattr(config_module.platformdirs, "user_config_dir", lambda appname: str(config_root))

    import matriosha.core.vault as vault_module
    import matriosha.cli.commands.vault as vault_cmd_module

    monkeypatch.setattr(vault_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(audit_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(vault_cmd_module.platformdirs, "user_config_dir", lambda appname: str(config_root))

    return config_root, data_root


def test_happy_path_init_then_unlock(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)

    vault = Vault.init("default", "correct horse battery staple")
    unlocked = Vault.unlock("default", "correct horse battery staple")

    assert len(vault.data_key) == 32
    assert unlocked.data_key == vault.data_key


def test_wrong_passphrase_raises_auth_error(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)

    Vault.init("default", "passphrase-a")

    try:
        Vault.unlock("default", "passphrase-b")
        assert False, "Expected AuthError"
    except AuthError:
        pass


def test_double_init_without_force_refuses(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)

    Vault.init("default", "alpha")

    try:
        Vault.init("default", "beta")
        assert False, "Expected VaultAlreadyInitializedError"
    except VaultAlreadyInitializedError:
        pass


def test_force_overwrites_existing_material(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)

    first = Vault.init("default", "alpha")
    second = Vault.init("default", "beta", force=True)

    assert first.data_key != second.data_key


def test_vault_files_have_0600_permissions(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)

    vault = Vault.init("default", "perm-check")

    if os.name != "nt":
        key_mode = stat.S_IMODE(vault.key_file.stat().st_mode)
        salt_mode = stat.S_IMODE(vault.salt_file.stat().st_mode)
        assert key_mode == 0o600
        assert salt_mode == 0o600


def test_cli_json_output_schema(monkeypatch, tmp_path) -> None:
    _, data_root = _patch_dirs(monkeypatch, tmp_path)

    env = {"MATRIOSHA_PASSPHRASE": "json-passphrase"}
    result = runner.invoke(app, ["vault", "init", "--json"], env=env)

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"status", "profile", "salt_file", "key_file"}
    assert payload["status"] == "ok"
    assert payload["profile"] == "default"
    assert payload["salt_file"].endswith("vault.salt")
    assert payload["key_file"].endswith("vault.key.enc")
    audit_path = data_root / "default" / "audit" / "events.jsonl"
    audit_record = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit_record["action"] == "vault.init"
    assert audit_record["target_type"] == "vault"
    assert audit_record["metadata"]["force"] is False
    assert audit_record["metadata"]["passphrase_source"] == "[REDACTED]"


def test_cli_double_init_without_force_refuses(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)

    env = {"MATRIOSHA_PASSPHRASE": "first-pass"}
    first = runner.invoke(app, ["vault", "init", "--json"], env=env)
    second = runner.invoke(app, ["vault", "init", "--json"], env=env)

    assert first.exit_code == 0
    assert second.exit_code == 2


def test_cli_force_overwrites(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)

    env_a = {"MATRIOSHA_PASSPHRASE": "aaa"}
    env_b = {"MATRIOSHA_PASSPHRASE": "bbb"}

    first = runner.invoke(app, ["vault", "init", "--json"], env=env_a)
    assert first.exit_code == 0

    force = runner.invoke(app, ["vault", "init", "--json", "--force"], env=env_b)
    assert force.exit_code == 0

    # New passphrase unlocks; old one does not.
    _ = Vault.unlock("default", "bbb")
    try:
        Vault.unlock("default", "aaa")
        assert False, "Expected AuthError after force overwrite"
    except AuthError:
        pass
