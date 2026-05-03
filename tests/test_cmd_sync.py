from __future__ import annotations

import hashlib
import json
import re
import tarfile
from pathlib import Path
from typing import Literal

import httpx
import respx
from typer.testing import CliRunner

from matriosha.cli.main import app
from matriosha.core import config as config_module
from matriosha.core.binary_protocol import encode_envelope, envelope_to_json
from matriosha.core.config import MatrioshaConfig, Profile, save_config
from matriosha.core.storage_local import LocalStore
from matriosha.core.managed.token_store import TokenStore
from matriosha.core.vault import Vault

runner = CliRunner()


def _patch_dirs(monkeypatch, tmp_path):
    config_root = tmp_path / ".config" / "matriosha"
    data_root = tmp_path / ".local" / "share" / "matriosha"

    monkeypatch.setattr(config_module.platformdirs, "user_config_dir", lambda appname: str(config_root))

    import matriosha.core.storage_local as store_module
    import matriosha.core.vault as vault_module
    import matriosha.core.vectors as vectors_module
    import matriosha.core.managed.auth as managed_auth_module

    monkeypatch.setattr(vault_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(store_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(vectors_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(managed_auth_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(managed_auth_module.platformdirs, "user_config_dir", lambda appname: str(config_root))

    return config_root, data_root


def _set_profile_mode(mode: Literal["local", "managed"], endpoint: str = "https://managed.example") -> None:
    cfg = MatrioshaConfig(
        profiles={"default": Profile(name="default", mode=mode, managed_endpoint=endpoint)},
        active_profile="default",
    )
    save_config(cfg)
    if mode == "managed":
        TokenStore("default").save(
            {
                "access_token": "token-ok",
                "refresh_token": "refresh-ok",
                "expires_at": "2999-01-01T00:00:00Z",
                "endpoint": endpoint,
                "profile": "default",
            }
        )


def _remember(text: str, passphrase: str = "correct-pass") -> str:
    result = runner.invoke(
        app,
        ["memory", "remember", text, "--json"],
        env={"MATRIOSHA_PASSPHRASE": passphrase, "MATRIOSHA_MANAGED_TOKEN": "token-ok"},
    )
    assert result.exit_code == 0
    return json.loads(result.stdout)["data"]["memory_id"]


def _roundtrip_hash(envelope: dict[str, object], payload_b64: str) -> str:
    canonical_env = json.dumps(envelope, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256()
    digest.update(canonical_env.encode("utf-8"))
    digest.update(b"\n")
    digest.update(payload_b64.encode("utf-8"))
    return digest.hexdigest()


def _build_server_routes(server_items: dict[str, dict[str, object]], *, tampered_ids: set[str] | None = None):
    tampered_ids = tampered_ids or set()

    def _whoami(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"user_id": "u_sync", "email": "sync@example.com"})

    def _upload(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        remote_id = f"srv_{len(server_items) + 1}"
        envelope = payload["envelope"]
        payload_b64 = payload["payload_b64"]
        server_items[remote_id] = {
            "id": remote_id,
            "envelope": envelope,
            "payload_b64": payload_b64,
            "roundtrip_hash": _roundtrip_hash(envelope, payload_b64),
        }
        return httpx.Response(200, json={"id": remote_id})

    def _list(_: httpx.Request) -> httpx.Response:
        items = []
        for item in server_items.values():
            items.append(
                {
                    "id": item["id"],
                    "envelope": item["envelope"],
                    "roundtrip_hash": item["roundtrip_hash"],
                }
            )
        return httpx.Response(200, json={"items": items})

    def _fetch(request: httpx.Request) -> httpx.Response:
        remote_id = request.url.path.split("/")[-1]
        item = server_items[remote_id]
        payload = str(item["payload_b64"])
        if remote_id in tampered_ids:
            tampered = "A" if payload[-1] != "A" else "B"
            payload = payload[:-1] + tampered
        return httpx.Response(
            200,
            json={
                "id": item["id"],
                "envelope": item["envelope"],
                "payload_b64": payload,
            },
        )

    return _whoami, _upload, _list, _fetch


def test_sync_push_pull_idempotent_and_pull_new(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _set_profile_mode("managed")
    Vault.init("default", "correct-pass")

    for idx in range(5):
        _remember(f"local memory {idx}")

    server_items: dict[str, dict[str, object]] = {}
    embedded_texts: list[str] = []

    class RecordingEmbedder:
        def embed(self, text: str):
            embedded_texts.append(text)
            return [1.0] * 384

    monkeypatch.setattr("matriosha.cli.commands.vault.sync.get_default_embedder", lambda: RecordingEmbedder())

    whoami, upload, list_handler, fetch = _build_server_routes(server_items)

    with respx.mock(assert_all_mocked=True) as mock:
        mock.get("https://managed.example/managed/whoami").mock(side_effect=whoami)
        mock.post("https://managed.example/managed/memories").mock(side_effect=upload)
        mock.get("https://managed.example/managed/memories").mock(side_effect=list_handler)
        mock.get(url__regex=re.compile(r"https://managed\.example/managed/memories/.+")).mock(side_effect=fetch)

        env = {
            "MATRIOSHA_PASSPHRASE": "correct-pass",
            "MATRIOSHA_MANAGED_TOKEN": "token-ok",
            "MATRIOSHA_MANAGED_ENDPOINT": "https://managed.example",
        }

        first = runner.invoke(app, ["vault", "sync", "--json"], env=env)
        assert first.exit_code == 0
        first_payload = json.loads(first.stdout)
        assert first_payload["pushed"] == 5
        assert first_payload["pulled"] == 0
        assert len(server_items) == 5
        assert embedded_texts == []

        second = runner.invoke(app, ["vault", "sync", "--json"], env=env)
        assert second.exit_code == 0
        second_payload = json.loads(second.stdout)
        assert second_payload["pushed"] == 0
        assert second_payload["pulled"] == 0

        # Add 3 server-only memories and ensure pull ingests them.
        vault = Vault.unlock("default", "correct-pass")
        for idx in range(3):
            env_obj, payload_b64 = encode_envelope(
                f"server memory {idx}".encode("utf-8"),
                vault.data_key,
                mode="managed",
                tags=["server"],
            )
            envelope_dict = json.loads(envelope_to_json(env_obj))
            payload_text = payload_b64.decode("utf-8")
            remote_id = f"srv_extra_{idx}"
            server_items[remote_id] = {
                "id": remote_id,
                "envelope": envelope_dict,
                "payload_b64": payload_text,
                "roundtrip_hash": _roundtrip_hash(envelope_dict, payload_text),
            }

        third = runner.invoke(app, ["vault", "pull", "--json"], env=env)
        assert third.exit_code == 0
        third_payload = json.loads(third.stdout)
        assert third_payload["pushed"] == 0
        assert third_payload["pulled"] == 3
        assert not any(f"server memory {idx}" in embedded_texts for idx in range(3))

        store = LocalStore("default")
        assert len(store.list(limit=1_000_000)) == 8


def test_sync_pull_rejects_tampered_payload(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _set_profile_mode("managed")
    Vault.init("default", "correct-pass")

    _remember("baseline")

    vault = Vault.unlock("default", "correct-pass")
    env_obj, payload_b64 = encode_envelope(
        b"remote tampered",
        vault.data_key,
        mode="managed",
        tags=["server"],
    )
    envelope_dict = json.loads(json.dumps(env_obj.__dict__))
    payload_text = payload_b64.decode("utf-8")

    server_items = {
        "srv_tamper": {
            "id": "srv_tamper",
            "envelope": envelope_dict,
            "payload_b64": payload_text,
            "roundtrip_hash": _roundtrip_hash(envelope_dict, payload_text),
        }
    }

    whoami, upload, list_handler, fetch = _build_server_routes(server_items, tampered_ids={"srv_tamper"})

    with respx.mock(assert_all_mocked=True, assert_all_called=False) as mock:
        mock.get("https://managed.example/managed/whoami").mock(side_effect=whoami)
        mock.post("https://managed.example/managed/memories").mock(side_effect=upload)
        mock.get("https://managed.example/managed/memories").mock(side_effect=list_handler)
        mock.get(url__regex=re.compile(r"https://managed\.example/managed/memories/.+")).mock(side_effect=fetch)

        env = {
            "MATRIOSHA_PASSPHRASE": "correct-pass",
            "MATRIOSHA_MANAGED_TOKEN": "token-ok",
            "MATRIOSHA_MANAGED_ENDPOINT": "https://managed.example",
        }

        result = runner.invoke(app, ["vault", "pull", "--json"], env=env)
        assert result.exit_code == 10
        payload = json.loads(result.stdout)
        assert payload["errors"]


def test_vault_export_writes_manifest_tarball(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _set_profile_mode("local")
    Vault.init("default", "correct-pass")

    _remember("export one")
    _remember("export two")

    out = tmp_path / "vault_export.tar.gz"
    result = runner.invoke(
        app,
        ["vault", "export", "--out", str(out), "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert Path(payload["path"]).exists()
    assert payload["memory_count"] == 2

    with tarfile.open(out, "r:gz") as archive:
        names = set(archive.getnames())
        assert "manifest.json" in names
        assert "envelope_index.json" in names
        manifest_file = archive.extractfile("manifest.json")
        assert manifest_file is not None
        manifest = json.loads(manifest_file.read().decode("utf-8"))

    assert manifest["memory_count"] == 2
    assert isinstance(manifest["merkle_root"], str)
    assert len(manifest["merkle_root"]) == 64
