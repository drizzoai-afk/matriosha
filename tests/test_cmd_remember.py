"""Command tests for `matriosha memory remember` (P2.6)."""

from __future__ import annotations

import json

from matriosha.core.config import MatrioshaConfig, Profile, save_config
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


def test_remember_drains_profile_inbox_before_storing_explicit_memory(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    inbox = tmp_path / ".local" / "share" / "matriosha" / "default" / "inbox"
    inbox.mkdir(parents=True)
    drop = inbox / "note.txt"
    drop.write_text("dropped file", encoding="utf-8")

    result = runner.invoke(
        app,
        ["memory", "remember", "explicit", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["inbox_ingested"] == 1
    assert not drop.exists()
    assert (inbox / ".processed" / "note.txt").exists()

    store = LocalStore("default")
    memories = store.list(limit=10)
    assert len(memories) == 2
    assert any(env.source == "cli" and env.filename == "note.txt" and "inbox" in env.tags for env in memories)


def test_remember_inbox_local_mode_does_not_require_managed_token(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    cfg = MatrioshaConfig(
        profiles={"default": Profile(name="default", mode="local", managed_endpoint="https://managed.example")},
        active_profile="default",
    )
    save_config(cfg)

    inbox = tmp_path / ".local" / "share" / "matriosha" / "default" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "local.txt").write_text("local inbox", encoding="utf-8")

    result = runner.invoke(
        app,
        ["memory", "remember", "explicit local", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["inbox_ingested"] == 1


def test_remember_inbox_managed_mode_requires_token_before_ingesting(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    cfg = MatrioshaConfig(
        profiles={"default": Profile(name="default", mode="managed", managed_endpoint="https://managed.example")},
        active_profile="default",
    )
    save_config(cfg)

    inbox = tmp_path / ".local" / "share" / "matriosha" / "default" / "inbox"
    inbox.mkdir(parents=True)
    drop = inbox / "managed.txt"
    drop.write_text("managed inbox", encoding="utf-8")

    result = runner.invoke(
        app,
        ["memory", "remember", "explicit managed", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 20
    payload = json.loads(result.stdout)
    assert payload["code"] == "AUTH-010"
    assert drop.exists()
    assert not (inbox / ".processed" / "managed.txt").exists()


def test_remember_without_payload_ingests_inbox_only(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    inbox = tmp_path / ".local" / "share" / "matriosha" / "default" / "inbox"
    inbox.mkdir(parents=True)
    first = inbox / "first.txt"
    second = inbox / "second.txt"
    first.write_text("first inbox", encoding="utf-8")
    second.write_text("second inbox", encoding="utf-8")

    result = runner.invoke(
        app,
        ["memory", "remember", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    data = payload["data"]
    assert data["memory_id"] is None
    assert data["inbox_ingested"] == 2
    assert len(data["inbox_memory_ids"]) == 2
    assert not first.exists()
    assert not second.exists()
    assert (inbox / ".processed" / "first.txt").exists()
    assert (inbox / ".processed" / "second.txt").exists()

    store = LocalStore("default")
    memories = store.list(limit=10)
    assert len(memories) == 2
    assert all(env.source == "cli" and "inbox" in env.tags for env in memories)


def test_remember_without_payload_and_empty_inbox_still_fails(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _init_vault()

    result = runner.invoke(
        app,
        ["memory", "remember", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["code"] == "VAL-001"
