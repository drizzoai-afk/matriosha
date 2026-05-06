from __future__ import annotations

from typing import Literal

import json
import signal

from typer.testing import CliRunner

import matriosha.cli.commands.memory.common as memory_common
from matriosha.cli.commands import vault as vault_cmd
from matriosha.cli.main import app
from matriosha.core import config as config_module
from matriosha.core.config import MatrioshaConfig, Profile, save_config
from matriosha.core.managed.sync import SyncReport
from matriosha.core.vault import Vault

runner = CliRunner()


def _patch_dirs(monkeypatch, tmp_path):
    config_root = tmp_path / ".config" / "matriosha"
    data_root = tmp_path / ".local" / "share" / "matriosha"

    monkeypatch.setattr(
        config_module.platformdirs, "user_config_dir", lambda appname: str(config_root)
    )

    import matriosha.core.storage_local as store_module
    import matriosha.core.vault as vault_module
    import matriosha.core.vectors as vectors_module

    monkeypatch.setattr(vault_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(store_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(
        vectors_module.platformdirs, "user_data_dir", lambda appname: str(data_root)
    )

    return config_root, data_root


def _set_mode(mode: Literal["local", "managed"], *, auto_sync: bool = False) -> None:
    cfg = MatrioshaConfig(
        profiles={
            "default": Profile(
                name="default", mode=mode, managed_endpoint="https://managed.example"
            )
        },
        active_profile="default",
    )
    cfg.managed.auto_sync = auto_sync
    save_config(cfg)


def test_billing_status_in_local_mode_exits_30(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _set_mode("local")

    result = runner.invoke(app, ["billing", "status"])

    assert result.exit_code == 30
    normalized = result.stdout.lower().replace("\n", " ")
    assert "requires managed mode" in normalized
    assert "matriosha mode set" in normalized and "managed" in normalized


def test_memory_remember_local_succeeds_managed_without_token_fails(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    Vault.init("default", "correct-pass")

    _set_mode("local")
    local_result = runner.invoke(
        app,
        ["memory", "remember", "hello local", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert local_result.exit_code == 0

    _set_mode("managed")
    managed_result = runner.invoke(
        app,
        ["memory", "remember", "hello managed", "--json"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )
    assert managed_result.exit_code == 20
    payload = json.loads(managed_result.stdout)
    assert payload["category"] == "AUTH"
    assert payload["code"] == "AUTH-010"
    assert "auth login" in payload["fix"]


def test_vault_sync_watch_cancels_cleanly_on_sigint(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _set_mode("managed")

    captured_handler: dict[str, object] = {}

    def fake_signal(sig, handler):
        captured_handler["handler"] = handler
        return signal.SIG_DFL

    monkeypatch.setattr(vault_cmd.signal, "signal", fake_signal)
    monkeypatch.setattr(vault_cmd.signal, "getsignal", lambda _sig: signal.SIG_DFL)

    class FakeManagedClient:
        def __init__(self, **_: object):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def whoami(self):
            return {"user_id": "u1"}

    class FakeSyncEngine:
        calls = 0

        def __init__(self, **_: object):
            pass

        async def sync(self):
            self.__class__.calls += 1
            handler = captured_handler.get("handler")
            if callable(handler):
                handler(signal.SIGINT, None)
            return SyncReport(pushed=1, pulled=0)

    monkeypatch.setattr(vault_cmd, "ManagedClient", FakeManagedClient)
    monkeypatch.setattr(vault_cmd, "SyncEngine", FakeSyncEngine)

    result = runner.invoke(
        app,
        ["vault", "sync", "--watch", "1", "--json"],
        env={"MATRIOSHA_MANAGED_TOKEN": "token-ok"},
    )

    assert result.exit_code == 0
    assert FakeSyncEngine.calls == 1
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["pushed"] == 1


def test_remember_auto_sync_true_schedules_background_sync(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _set_mode("managed", auto_sync=True)
    Vault.init("default", "correct-pass")

    popen_calls: list[dict[str, object]] = []

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            popen_calls.append({"cmd": cmd, "kwargs": kwargs})

    monkeypatch.setattr(
        memory_common.shutil,
        "which",
        lambda name: "/usr/local/bin/matriosha" if name == "matriosha" else None,
    )
    monkeypatch.setattr(memory_common.subprocess, "Popen", FakePopen)

    result = runner.invoke(
        app,
        ["memory", "remember", "autosync payload", "--json"],
        env={
            "MATRIOSHA_PASSPHRASE": "correct-pass",
            "MATRIOSHA_MANAGED_TOKEN": "token-ok",
        },
    )

    assert result.exit_code == 0
    assert len(popen_calls) == 1
    assert popen_calls[0]["cmd"] == [
        "/usr/local/bin/matriosha",
        "--profile",
        "default",
        "--json",
        "vault",
        "sync",
    ]
    assert popen_calls[0]["kwargs"]["start_new_session"] is True
    assert popen_calls[0]["kwargs"]["stdin"] is memory_common.subprocess.DEVNULL
    assert popen_calls[0]["kwargs"]["stdout"] is memory_common.subprocess.DEVNULL
    assert popen_calls[0]["kwargs"]["stderr"] is memory_common.subprocess.DEVNULL


def test_memory_remember_missing_profile_returns_usage_error(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)

    result = runner.invoke(
        app,
        ["--profile", "missing-profile", "--json", "memory", "remember", "payload"],
        env={"MATRIOSHA_PASSPHRASE": "correct-pass"},
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["category"] == "VAL"
    assert payload["code"] == "VAL-002"
    assert payload["title"] == "Profile 'missing-profile' not found"
    assert "STORE-001" not in result.stdout


def test_remember_auto_sync_missing_executable_is_best_effort(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _set_mode("managed", auto_sync=True)
    Vault.init("default", "correct-pass")

    popen_called = False

    def fake_popen(*args, **kwargs):
        nonlocal popen_called
        popen_called = True
        raise AssertionError("Popen should not be called when executable is missing")

    monkeypatch.setattr(memory_common.shutil, "which", lambda name: None)
    monkeypatch.setattr(memory_common.subprocess, "Popen", fake_popen)

    result = runner.invoke(
        app,
        ["memory", "remember", "autosync missing executable payload", "--json"],
        env={
            "MATRIOSHA_PASSPHRASE": "correct-pass",
            "MATRIOSHA_MANAGED_TOKEN": "token-ok",
        },
    )

    assert result.exit_code == 0
    assert popen_called is False
