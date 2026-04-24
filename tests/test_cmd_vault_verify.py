"""Command tests for `matriosha vault verify`."""

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

    import matriosha.core.storage_local as store_module
    import matriosha.core.vault as vault_module

    monkeypatch.setattr(vault_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(store_module.platformdirs, "user_data_dir", lambda appname: str(data_root))

    return data_root


def _remember(text: str) -> str:
    result = runner.invoke(
        app,
        ["memory", "remember", text, "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert result.exit_code == 0
    return json.loads(result.stdout)["data"]["memory_id"]


def test_vault_verify_deep_all_ok_then_detects_tamper(monkeypatch, tmp_path) -> None:
    data_root = _patch_dirs(monkeypatch, tmp_path)
    Vault.init("default", "correct-pass")

    memory_ids = [_remember("alpha"), _remember("beta"), _remember("gamma")]

    verify_ok = runner.invoke(
        app,
        ["vault", "verify", "--deep", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert verify_ok.exit_code == 0
    payload_ok = json.loads(verify_ok.stdout)
    assert payload_ok["total"] == 3
    assert payload_ok["ok"] == 3
    assert payload_ok["failed"] == []

    tampered_id = memory_ids[1]
    payload_path = data_root / "default" / "memories" / f"{tampered_id}.bin.b64"
    original = payload_path.read_bytes()
    tampered = bytearray(original)
    tampered[-1] = ord("A") if tampered[-1] != ord("A") else ord("B")
    payload_path.write_bytes(bytes(tampered))

    verify_bad = runner.invoke(
        app,
        ["vault", "verify", "--deep", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert verify_bad.exit_code == 10
    payload_bad = json.loads(verify_bad.stdout)
    failed_ids = {entry["id"] for entry in payload_bad["failed"]}
    assert tampered_id in failed_ids
