from __future__ import annotations

import json
import signal

from typer.testing import CliRunner

from matriosha.cli.commands import memory as memory_cmd
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

    monkeypatch.setattr(config_module.platformdirs, "user_config_dir", lambda appname: str(config_root))

    import matriosha.core.storage_local as store_module
    import matriosha.core.vault as vault_module
    import matriosha.core.vectors as vectors_module

    monkeypatch.setattr(vault_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(store_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    monkeypatch.setattr(vectors_module.platformdirs, "user_data_dir", lambda appname: str(data_root))

    return config_root, data_root


def _set_mode(mode: str, *, auto_sync: bool = False) -> None:
    cfg = MatrioshaConfig(
        profiles={"default": Profile(name="default", mode=mode, managed_endpoint="https://managed.example")},
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
            if handler:
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


def test_remember_auto_sync_true_triggers_one_sync_call(monkeypatch, tmp_path) -> None:
    _patch_dirs(monkeypatch, tmp_path)
    _set_mode("managed", auto_sync=True)
    Vault.init("default", "correct-pass")

    class FakeManagedClient:
        def __init__(self, **_: object):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    class FakeSyncEngine:
        calls = 0

        def __init__(self, **_: object):
            pass

        async def sync(self):
            self.__class__.calls += 1
            return SyncReport()

    class ImmediateThread:
        def __init__(self, *, target, daemon=None, name=None):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(memory_cmd, "ManagedClient", FakeManagedClient)
    monkeypatch.setattr(memory_cmd, "SyncEngine", FakeSyncEngine)
    monkeypatch.setattr(memory_cmd.threading, "Thread", ImmediateThread)

    result = runner.invoke(
        app,
        ["memory", "remember", "autosync payload", "--json"],
        env={
            "MATRIOSHA_PASSPHRASE": "correct-pass",
            "MATRIOSHA_MANAGED_TOKEN": "token-ok",
        },
    )

    assert result.exit_code == 0
    assert FakeSyncEngine.calls == 1
