from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from matriosha.cli.commands.auth import common as auth_common
from matriosha.cli.commands.auth import whoami as auth_whoami_cmd
from matriosha.cli.commands.billing import common as billing_common
from matriosha.cli.commands.billing import status as billing_status_cmd
from matriosha.cli.commands.token import common as token_common
from matriosha.cli.commands.token import generate as token_generate_cmd
from matriosha.cli.main import app
from matriosha.cli.utils import mode_guard
from matriosha.core import config as config_module
from matriosha.core.config import MatrioshaConfig, Profile
from matriosha.core.vault import Vault

runner = CliRunner()
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


def _load_snapshot(name: str) -> dict:
    return json.loads((SNAPSHOT_DIR / name).read_text(encoding="utf-8"))


def _patch_local_dirs(monkeypatch, tmp_path):
    config_root = tmp_path / ".config" / "matriosha"
    data_root = tmp_path / ".local" / "share" / "matriosha"

    monkeypatch.setattr(config_module.platformdirs, "user_config_dir", lambda appname: str(config_root))

    import matriosha.cli.commands.memory as memory_cmd_module
    import matriosha.core.storage_local as store_module
    import matriosha.core.vault as vault_module
    import matriosha.core.vectors as vectors_module

    monkeypatch.setattr(vault_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(store_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(vectors_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(
        memory_cmd_module,
        "_resolve_passphrase",
        lambda **_kwargs: "correct-pass",
    )


def _patch_managed_mode(monkeypatch, profile: Profile) -> None:
    cfg = MatrioshaConfig(profiles={"default": profile}, active_profile="default")
    monkeypatch.setattr(mode_guard, "load_config", lambda: cfg)
    monkeypatch.setattr(mode_guard, "get_active_profile", lambda _cfg, _override: profile)


def _normalize_snapshot(payload: dict, snapshot_name: str) -> dict:
    normalized = json.loads(json.dumps(payload))

    if snapshot_name == "remember.json":
        return {
            "status": normalized["status"],
            "operation": normalized["operation"],
            "error": normalized["error"],
            "data": {
                "memory_id": "<memory_id>",
                "bytes": normalized["data"]["bytes"],
                "blocks": normalized["data"]["blocks"],
                "merkle_root": "<merkle_root>",
                "tags": normalized["data"]["tags"],
                "path": "<path>",
                "backup_key": normalized["data"].get("backup_key"),
                "backup_warning": normalized["data"].get("backup_warning"),
            },
        }

    if snapshot_name == "list.json":
        items = []
        for item in normalized["data"]["items"]:
            items.append(
                {
                    "memory_id": "<memory_id>",
                    "mode": item["mode"],
                    "encoding": item["encoding"],
                    "hash_algo": item["hash_algo"],
                    "merkle_root": "<merkle_root>",
                    "tags": item["tags"],
                    "source": item["source"],
                }
            )
        return {
            "status": normalized["status"],
            "operation": normalized["operation"],
            "error": normalized["error"],
            "data": {
                "tag": normalized["data"]["tag"],
                "limit": normalized["data"]["limit"],
                "since": normalized["data"]["since"],
                "items": items,
            },
        }

    if snapshot_name == "search.json":
        results = []
        for item in normalized["data"]["results"]:
            semantic = item.get("semantic") or {}
            results.append(
                {
                    "memory_id": "<memory_id>",
                    "score": "<score>",
                    "tags": item["tags"],
                    "created_at": "<created_at>",
                    "preview": item["preview"],
                    "integrity_warning": item.get("integrity_warning"),
                    "restored_from_backup": item.get("restored_from_backup"),
                    "semantic": {
                        "kind": semantic.get("kind"),
                        "mime_type": semantic.get("mime_type"),
                        "filename": semantic.get("filename"),
                        "preview": semantic.get("preview"),
                        "warnings": semantic.get("warnings"),
                    },
                }
            )
        return {
            "status": normalized["status"],
            "operation": normalized["operation"],
            "error": normalized["error"],
            "data": {
                "query": normalized["data"]["query"],
                "k": normalized["data"]["k"],
                "threshold": normalized["data"]["threshold"],
                "tag": normalized["data"]["tag"],
                "results": results,
            },
        }

    if snapshot_name == "token_generate.json":
        normalized["token"] = "<redacted>"
        return normalized

    return normalized


def test_json_contract_and_snapshots(monkeypatch, tmp_path) -> None:
    _patch_local_dirs(monkeypatch, tmp_path)
    Vault.init("default", "correct-pass")

    remember = runner.invoke(app, ["memory", "remember", "hello snapshot", "--json"], env={"MATRIOSHA_PASSPHRASE": "correct-pass"})
    assert remember.exit_code == 0
    remember_payload = json.loads(remember.stdout)
    memory_id = remember_payload["data"]["memory_id"]

    listed = runner.invoke(app, ["memory", "list", "--json"], env={"MATRIOSHA_PASSPHRASE": "correct-pass"})
    assert listed.exit_code == 0
    list_payload = json.loads(listed.stdout)

    search = runner.invoke(app, ["memory", "search", "hello", "--json"], env={"MATRIOSHA_PASSPHRASE": "correct-pass"})
    assert search.exit_code == 0
    search_payload = json.loads(search.stdout)

    managed_profile = Profile(
        name="default",
        mode="managed",
        managed_endpoint="https://managed.example",
        created_at=datetime.now(timezone.utc),
    )
    _patch_managed_mode(monkeypatch, managed_profile)
    monkeypatch.setattr(auth_common, "require_mode", lambda _mode: (lambda _ctx: None))
    monkeypatch.setattr(auth_common, "load_config", lambda: MatrioshaConfig(profiles={"default": managed_profile}, active_profile="default"))
    monkeypatch.setattr(auth_common, "get_active_profile", lambda _cfg, _override: managed_profile)
    monkeypatch.setattr(auth_common, "resolve_access_token", lambda _profile_name: "token-ok")

    class _AuthManagedClient:
        def __init__(self, **_: object):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def whoami(self):
            return {"user_id": "user-123", "email": "user@example.com", "subscription_status": "active"}

    monkeypatch.setattr(auth_whoami_cmd, "ManagedClient", _AuthManagedClient)

    whoami = runner.invoke(app, ["--json", "--mode", "managed", "auth", "whoami"])
    assert whoami.exit_code == 0
    whoami_payload = json.loads(whoami.stdout)

    monkeypatch.setattr(billing_common, "load_config", lambda: MatrioshaConfig(profiles={"default": managed_profile}, active_profile="default"))
    monkeypatch.setattr(billing_common, "get_active_profile", lambda _cfg, _override: managed_profile)

    class _FakeManagedClient:
        def __init__(self, **_: object):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get_subscription(self):
            return {
                "status": "active",
                "plan_code": "eur_monthly",
                "current_period_end": "2026-05-22T00:00:00Z",
                "agent_quota": 3,
                "agent_in_use": 1,
                "storage_cap_bytes": 3 * 1024**3,
                "storage_used_bytes": 1024,
                "quantity": 1,
            }

    monkeypatch.setattr(billing_common, "ManagedClient", _FakeManagedClient)
    billing = runner.invoke(app, ["--mode", "managed", "billing", "status", "--json"], env={"MATRIOSHA_MANAGED_TOKEN": "token-ok"})
    assert billing.exit_code == 0
    billing_payload = json.loads(billing.stdout)

    monkeypatch.setattr(token_generate_cmd, "load_config", lambda: MatrioshaConfig(profiles={"default": managed_profile}, active_profile="default"))
    monkeypatch.setattr(token_generate_cmd, "get_active_profile", lambda _cfg, _override: managed_profile)
    monkeypatch.setattr(token_common, "load_config", lambda: MatrioshaConfig(profiles={"default": managed_profile}, active_profile="default"))
    monkeypatch.setattr(token_common, "get_active_profile", lambda _cfg, _override: managed_profile)
    monkeypatch.setattr(token_generate_cmd, "_validate_backend_credentials", lambda _json, _plain: None)
    async def _fake_generate_token(**_: object) -> dict[str, str]:
        return {
            "id": "12345678-90ab-cdef-1234-567890abcdef",
            "token_plaintext": "mt_secret_token",
            "name": "ci-agent",
            "scope": "write",
            "expires_at": "2026-04-30T10:00:00Z",
        }

    monkeypatch.setattr(token_generate_cmd, "_generate_token", _fake_generate_token)
    token_result = runner.invoke(
        app,
        ["--mode", "managed", "token", "generate", "ci-agent", "--json"],
        env={"MATRIOSHA_MANAGED_TOKEN": "token-ok", "SUPABASE_URL": "x", "SUPABASE_SERVICE_ROLE_KEY": "y"},
    )
    assert token_result.exit_code == 0
    token_payload = json.loads(token_result.stdout)

    snapshots = {
        "remember.json": _normalize_snapshot(remember_payload, "remember.json"),
        "list.json": _normalize_snapshot(list_payload, "list.json"),
        "search.json": _normalize_snapshot(search_payload, "search.json"),
        "whoami.json": _normalize_snapshot(whoami_payload, "whoami.json"),
        "billing_status.json": _normalize_snapshot(billing_payload, "billing_status.json"),
        "token_generate.json": _normalize_snapshot(token_payload, "token_generate.json"),
    }

    for name, actual in snapshots.items():
        assert actual == _load_snapshot(name)

    # deterministic JSON output for repeated invocations (post-normalization)
    again = runner.invoke(app, ["memory", "list", "--json"], env={"MATRIOSHA_PASSPHRASE": "correct-pass"})
    assert again.exit_code == 0
    again_payload = _normalize_snapshot(json.loads(again.stdout), "list.json")
    assert again_payload == snapshots["list.json"]

    # sanity check command output can still find created memory
    assert any(item["memory_id"] == memory_id for item in list_payload["data"]["items"])


def test_plain_mode_has_no_ansi_and_rich_mode_uses_visual_format(monkeypatch, tmp_path) -> None:
    _patch_local_dirs(monkeypatch, tmp_path)
    Vault.init("default", "correct-pass")

    remember = runner.invoke(app, ["memory", "remember", "plain-rich", "--json"], env={"MATRIOSHA_PASSPHRASE": "correct-pass"})
    memory_id = json.loads(remember.stdout)["data"]["memory_id"]

    plain = runner.invoke(app, ["--plain", "memory", "list"], env={"MATRIOSHA_PASSPHRASE": "correct-pass"})
    assert plain.exit_code == 0
    assert "\x1b[" not in plain.stdout

    rich = runner.invoke(app, ["memory", "recall", memory_id, "--out", str(tmp_path / "out.txt")], env={"MATRIOSHA_PASSPHRASE": "correct-pass"})
    assert rich.exit_code == 0
    assert "✓" in rich.stdout


def test_json_memory_prompt_goes_to_stderr_and_stdout_is_valid_json(monkeypatch, tmp_path) -> None:
    config_root = tmp_path / ".config" / "matriosha"
    data_root = tmp_path / ".local" / "share" / "matriosha"

    monkeypatch.setattr(config_module.platformdirs, "user_config_dir", lambda appname: str(config_root))

    import matriosha.core.storage_local as store_module
    import matriosha.core.vault as vault_module
    import matriosha.core.vectors as vectors_module

    monkeypatch.setattr(vault_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(store_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(vectors_module.platformdirs, "user_data_dir", lambda appname: str(data_root))

    Vault.init("default", "correct-pass")

    stderr_runner = CliRunner(mix_stderr=False)
    result = stderr_runner.invoke(
        app,
        ["memory", "remember", "stdout purity", "--json"],
        input="correct-pass\n",
    )

    assert result.exit_code == 0
    assert "Vault passphrase" not in result.stdout
    assert "Vault passphrase" in result.stderr

    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["operation"] == "memory.remember"
    assert payload["data"]["bytes"] == len("stdout purity".encode("utf-8"))
