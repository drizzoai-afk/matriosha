"""Command tests for `matriosha memory remember` (P2.6)."""

from __future__ import annotations

import json
import os

from typer.testing import CliRunner

from matriosha.cli.main import app
from matriosha.core import config as config_module
from matriosha.core.binary_protocol import decode_envelope
from matriosha.core.storage_local import LocalStore
from matriosha.core.vault import Vault

runner = CliRunner()


def _patch_dirs(monkeypatch, tmp_path):
    config_root = tmp_path / ".config" / "matriosha"
    data_root = tmp_path / ".local" / "share" / "matriosha"

    monkeypatch.setattr(config_module.platformdirs, "user_config_dir", lambda appname: str(config_root))

    import matriosha.core.vault as vault_module
    import matriosha.core.storage_local as store_module

    monkeypatch.setattr(vault_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(store_module.platformdirs, "user_data_dir", lambda appname: str(data_root))

    return config_root, data_root


def _init_vault(passphrase: str = "correct-pass") -> None:
    Vault.init("default", passphrase)


def test_remember_without_initialized_vault_guides_user(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)

    result = runner.invoke(
        app,
        ["memory", "remember", "hello", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 20
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["title"] == "Vault not initialized"
    assert payload["category"] == "AUTH"
    assert payload["code"] == "AUTH-003"
    assert payload["fix"] == "Run: matriosha vault init"


def test_remember_hello_creates_memory_files(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    result = runner.invoke(
        app,
        ["memory", "remember", "hello", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    memory_id = payload["data"]["memory_id"]

    store_root = tmp_path / ".local" / "share" / "matriosha" / "default" / "memories"
    assert (store_root / f"{memory_id}.env.json").exists()
    assert (store_root / f"{memory_id}.bin.b64").exists()


def test_recall_via_store_and_decode_returns_hello(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    result = runner.invoke(
        app,
        ["memory", "remember", "hello", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert result.exit_code == 0
    memory_id = json.loads(result.stdout)["data"]["memory_id"]

    store = LocalStore("default")
    env, b64_payload = store.get(memory_id)
    unlocked = Vault.unlock("default", "correct-pass")
    plaintext = decode_envelope(env, b64_payload, unlocked.data_key)

    assert plaintext == b"hello"


def test_invalid_tag_exits_2(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    result = runner.invoke(
        app,
        ["memory", "remember", "hello", "--tag", "BadTag", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 2


def test_file_over_50mib_exits_2(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    oversized = tmp_path / "oversized.bin"
    oversized.write_bytes(b"a" * (50 * 1024 * 1024 + 1))

    result = runner.invoke(
        app,
        ["memory", "remember", "--file", str(oversized), "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 2


def test_wrong_passphrase_exits_20(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault(passphrase="real-pass")

    result = runner.invoke(
        app,
        ["memory", "remember", "hello", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "wrong-pass"},
    )

    assert result.exit_code == 20


def test_json_schema(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    result = runner.invoke(
        app,
        ["memory", "remember", "hello world", "--tag", "test", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"status", "operation", "data", "error"}
    data = payload["data"]
    assert data["bytes"] == len("hello world".encode("utf-8"))
    assert data["blocks"] == 1
    assert data["tags"] == ["test"]
    assert isinstance(data["merkle_root"], str) and len(data["merkle_root"]) == 64


def test_two_remembers_distinct_ids_and_merkle_roots(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    env = {"MATRIOSHA_PASSPHRASE": "correct-pass"}
    first = runner.invoke(app, ["memory", "remember", "first text", "--json"], env=env)
    second = runner.invoke(app, ["memory", "remember", "second text", "--json"], env=env)

    assert first.exit_code == 0
    assert second.exit_code == 0

    p1 = json.loads(first.stdout)
    p2 = json.loads(second.stdout)

    assert p1["data"]["memory_id"] != p2["data"]["memory_id"]
    assert p1["data"]["merkle_root"] != p2["data"]["merkle_root"]
