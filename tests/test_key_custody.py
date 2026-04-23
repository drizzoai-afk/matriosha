from __future__ import annotations

import base64
import json

from nacl.public import PrivateKey
from typer.testing import CliRunner

from cli.main import app
from core import config as config_module
from core.binary_protocol import decode_envelope
from core.config import MatrioshaConfig, Profile, save_config
from core.crypto import derive_key
from core.managed.key_custody import double_unwrap, double_wrap
from core.storage_local import LocalStore
from core.vault import Vault

runner = CliRunner()


def _patch_dirs(monkeypatch, tmp_path):
    config_root = tmp_path / ".config" / "matriosha"
    data_root = tmp_path / ".local" / "share" / "matriosha"

    monkeypatch.setattr(config_module.platformdirs, "user_config_dir", lambda appname: str(config_root))

    import core.storage_local as store_module
    import core.vault as vault_module
    import core.vectors as vectors_module

    monkeypatch.setattr(vault_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(store_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(vectors_module.platformdirs, "user_data_dir", lambda appname: str(data_root))

    return config_root, data_root


def _remember(text: str, *, passphrase: str) -> str:
    result = runner.invoke(
        app,
        ["memory", "remember", text, "--json"],
        env={"MATRIOSHA_PASSPHRASE": passphrase},
    )
    assert result.exit_code == 0
    return json.loads(result.stdout)["memory_id"]


def test_double_wrap_unwrap_roundtrip() -> None:
    server_priv = PrivateKey.generate()
    server_pub = server_priv.public_key

    data_key = b"d" * 32
    kek = b"k" * 32

    blob = double_wrap(data_key, kek, server_pub)
    unwrapped = double_unwrap(blob, kek, server_priv)

    assert unwrapped == data_key


def test_rotate_kek_only_keeps_existing_memories_decryptable(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    Vault.init("default", "old-pass")

    memory_id = _remember("rotate-kek-only", passphrase="old-pass")
    store = LocalStore("default")
    _, before_payload = store.get(memory_id)

    rotated = runner.invoke(
        app,
        ["vault", "rotate", "--new-passphrase", "new-pass", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "old-pass"},
    )
    assert rotated.exit_code == 0

    _, after_payload = store.get(memory_id)
    assert after_payload == before_payload

    recall = runner.invoke(
        app,
        ["memory", "recall", memory_id],
        env={"MATRIOSHA_PASSPHRASE": "new-pass"},
    )
    assert recall.exit_code == 0
    assert recall.stdout == "rotate-kek-only"


def test_rotate_data_key_reencrypts_atomically(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    Vault.init("default", "old-pass")

    memory_ids = [_remember("alpha", passphrase="old-pass"), _remember("beta", passphrase="old-pass")]
    store = LocalStore("default")
    before_payloads = {memory_id: store.get(memory_id)[1] for memory_id in memory_ids}

    rotated = runner.invoke(
        app,
        ["vault", "rotate", "--rotate-data-key", "--confirm-bulk", "--new-passphrase", "new-pass", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "old-pass"},
    )
    assert rotated.exit_code == 0

    result = json.loads(rotated.stdout)
    assert result["reencrypted_memories"] == 2

    for memory_id in memory_ids:
        _, payload_after = store.get(memory_id)
        assert payload_after != before_payloads[memory_id]

    root = store.root
    assert not (root / "memories.rotate.tmp").exists()
    assert not (root / "rotate.marker.json").exists()


def test_rotate_data_key_crash_and_resume(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    Vault.init("default", "old-pass")

    memory_ids = [
        _remember("one", passphrase="old-pass"),
        _remember("two", passphrase="old-pass"),
        _remember("three", passphrase="old-pass"),
    ]

    import cli.commands.vault as vault_cmd

    monkeypatch.setattr(vault_cmd.os, "urandom", lambda n: b"\x33" * n)

    crash = runner.invoke(
        app,
        ["vault", "rotate", "--rotate-data-key", "--confirm-bulk", "--new-passphrase", "new-pass", "--json"],
        env={
            "MATRIOSHA_PASSPHRASE": "old-pass",
            "MATRIOSHA_ROTATE_CRASH_AFTER": "1",
        },
    )
    assert crash.exit_code == 2

    store = LocalStore("default")
    root = store.root
    marker_path = root / "rotate.marker.json"
    tmp_dir = root / "memories.rotate.tmp"

    assert marker_path.exists()
    assert tmp_dir.exists()

    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    completed_ids = marker["completed"]
    assert len(completed_ids) == 1

    old_vault = Vault.unlock("default", "old-pass")
    for memory_id in memory_ids:
        env, payload = store.get(memory_id)
        plaintext = decode_envelope(env, payload, old_vault.data_key)
        assert plaintext

    resumed_key = b"\x33" * 32
    completed_id = completed_ids[0]
    env, _ = store.get(completed_id)
    rotated_payload = (tmp_dir / f"{completed_id}.bin.b64").read_bytes()
    rotated_plaintext = decode_envelope(env, rotated_payload, resumed_key)
    assert rotated_plaintext

    resumed = runner.invoke(
        app,
        ["vault", "rotate", "--rotate-data-key", "--confirm-bulk", "--new-passphrase", "new-pass", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "old-pass"},
    )
    assert resumed.exit_code == 0
    resumed_payload = json.loads(resumed.stdout)
    assert resumed_payload["resumed"] is True


def test_managed_rotate_uploads_new_wrapped_key(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    save_config(
        MatrioshaConfig(
            profiles={"default": Profile(name="default", mode="managed", managed_endpoint="https://managed.example")},
            active_profile="default",
        )
    )
    Vault.init("default", "old-pass")
    _remember("managed-rotate", passphrase="old-pass")

    captured: dict[str, bytes] = {}

    async def _fake_upload(remote, kek_salt: bytes, wrapped_key_bytes: bytes) -> None:
        _ = remote
        captured["kek_salt"] = kek_salt
        captured["wrapped"] = wrapped_key_bytes

    class _FakeManagedClient:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    import cli.commands.vault as vault_cmd

    monkeypatch.setattr(vault_cmd, "upload_wrapped_key", _fake_upload)
    monkeypatch.setattr(vault_cmd, "ManagedClient", _FakeManagedClient)

    server_priv = PrivateKey.generate()
    server_pub_b64 = base64.b64encode(bytes(server_priv.public_key)).decode("ascii")

    rotated = runner.invoke(
        app,
        ["vault", "rotate", "--new-passphrase", "new-pass", "--json"],
        env={
            "MATRIOSHA_PASSPHRASE": "old-pass",
            "MATRIOSHA_MANAGED_TOKEN": "token-ok",
            "MATRIOSHA_VAULT_SERVER_PUBKEY": server_pub_b64,
            "MATRIOSHA_MANAGED_ENDPOINT": "https://managed.example",
        },
    )

    assert rotated.exit_code == 0
    assert len(captured["kek_salt"]) == 16
    assert captured["wrapped"]

    kek = derive_key("new-pass", captured["kek_salt"])
    roundtrip_key = double_unwrap(captured["wrapped"], kek, server_priv)
    assert len(roundtrip_key) == 32
