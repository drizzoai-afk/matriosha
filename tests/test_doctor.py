"""Tests for `matriosha doctor` diagnostics command."""

from __future__ import annotations

import json
import time

from typer.testing import CliRunner

from matriosha.cli.main import app
from matriosha.core import config as config_module
from matriosha.core.config import MatrioshaConfig, Profile, save_config
from matriosha.core.vault import Vault

runner = CliRunner()


def _patch_dirs(monkeypatch, tmp_path):
    config_root = tmp_path / ".config" / "matriosha"
    data_root = tmp_path / ".local" / "share" / "matriosha"

    monkeypatch.setattr(config_module.platformdirs, "user_config_dir", lambda appname: str(config_root))

    import matriosha.core.vault as vault_module
    import matriosha.core.vectors as vectors_module

    monkeypatch.setattr(vault_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(vectors_module.platformdirs, "user_data_dir", lambda appname: str(data_root))

    return config_root, data_root


def test_doctor_all_checks_green_on_fresh_install(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)

    import matriosha.core.diagnostics as diagnostics_module

    monkeypatch.setattr(diagnostics_module, "_fetch_ntp_epoch", lambda _host, timeout: time.time())

    Vault.init("default", "correct-pass")

    result = runner.invoke(
        app,
        ["doctor", "--json", "--test-passphrase", "correct-pass"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["checks"]
    assert all(check["status"] == "ok" for check in payload["checks"])


def test_doctor_flags_corrupt_config_and_suggests_remediation(monkeypatch, tmp_path) -> None:
    config_root, _ = _patch_dirs(monkeypatch, tmp_path)

    import matriosha.core.diagnostics as diagnostics_module

    monkeypatch.setattr(diagnostics_module, "_fetch_ntp_epoch", lambda _host, timeout: time.time())

    Vault.init("default", "correct-pass")

    config_path = config_root / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("this is not valid toml = [", encoding="utf-8")

    result = runner.invoke(app, ["doctor", "--json", "--test-passphrase", "correct-pass"])

    assert result.exit_code == 10
    payload = json.loads(result.stdout)
    config_check = next(check for check in payload["checks"] if check["name"] == "config.file")
    assert config_check["status"] == "fail"
    assert "parse" in config_check["detail"]
    assert "chmod 600" in config_check["hint"]


def test_doctor_managed_mode_without_token_flags_auth(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)

    import matriosha.core.diagnostics as diagnostics_module

    monkeypatch.setattr(diagnostics_module, "_fetch_ntp_epoch", lambda _host, timeout: time.time())

    cfg = MatrioshaConfig(
        profiles={"default": Profile(name="default", mode="managed", managed_endpoint="https://example.com")},
        active_profile="default",
    )
    save_config(cfg)

    Vault.init("default", "correct-pass")

    result = runner.invoke(
        app,
        ["doctor", "--json", "--test-passphrase", "correct-pass"],
    )

    assert result.exit_code == 10
    payload = json.loads(result.stdout)
    auth_check = next(check for check in payload["checks"] if check["name"] == "managed.auth")
    assert auth_check["status"] == "fail"
    assert "MATRIOSHA_MANAGED_TOKEN" in auth_check["detail"]
    assert "auth login" in auth_check["hint"]
