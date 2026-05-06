import json
from typing import cast
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import typer
from rich.table import Table

import matriosha.cli.commands.quota as quota_cmd
import matriosha.cli.commands.status as status_cmd
import matriosha.cli.utils.config as config_utils
from matriosha.cli.utils.context import GlobalContext
from matriosha.cli.utils.output import Output, _table_to_plain


def test_config_load_defaults_without_file_or_secrets(tmp_path, monkeypatch):
    monkeypatch.delenv("MATRIOSHA_VAULT_PATH", raising=False)
    monkeypatch.delenv("MATRIOSHA_MODE", raising=False)
    monkeypatch.delenv("MATRIOSHA_API_KEY", raising=False)
    monkeypatch.setitem(config_utils.DEFAULT_CONFIG["vault"], "mode", "local")
    monkeypatch.setattr(config_utils, "get_secret", lambda name: None)

    cfg = config_utils.load_config(tmp_path / "missing.toml")

    assert cfg["vault"]["mode"] == "local"
    assert cfg["auth"]["type"] == "keyring"
    assert cfg["supabase"]["url"] is None


def test_config_load_file_env_and_secret_overrides(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[vault]
path = "/from-file"
mode = "managed"

[auth]
api_key = "from-file"

[supabase]
url = "https://configured.example"
""".strip()
    )

    monkeypatch.setenv("MATRIOSHA_VAULT_PATH", "/from-env")
    monkeypatch.setenv("MATRIOSHA_MODE", "hybrid")
    monkeypatch.setenv("MATRIOSHA_API_KEY", "env-key")
    monkeypatch.setattr(
        config_utils,
        "get_secret",
        lambda name: "secret-anon" if name == "SUPABASE_ANON_KEY" else "secret-url",
    )

    cfg = config_utils.load_config(config_path)

    assert cfg["vault"]["path"] == "/from-env"
    assert cfg["vault"]["mode"] == "hybrid"
    assert cfg["auth"]["api_key"] == "env-key"
    assert cfg["supabase"]["url"] == "https://configured.example"
    assert cfg["supabase"]["anon_key"] == "secret-anon"


def test_config_load_invalid_file_warns_and_keeps_defaults(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "bad.toml"
    config_path.write_text("not valid toml = [")

    monkeypatch.delenv("MATRIOSHA_VAULT_PATH", raising=False)
    monkeypatch.delenv("MATRIOSHA_MODE", raising=False)
    monkeypatch.delenv("MATRIOSHA_API_KEY", raising=False)
    monkeypatch.setitem(config_utils.DEFAULT_CONFIG["vault"], "mode", "local")
    monkeypatch.setattr(config_utils, "get_secret", lambda name: None)

    cfg = config_utils.load_config(config_path)

    monkeypatch.delenv("MATRIOSHA_MODE", raising=False)

    captured = capsys.readouterr()
    assert "Warning: Could not load config" in captured.out
    assert cfg["vault"]["mode"] == "local"


def test_save_config_filters_none_and_get_vault_path(tmp_path):
    config_path = tmp_path / "nested" / "config.toml"
    vault_path = tmp_path / "vault"

    config_utils.save_config(
        {
            "vault": {"path": str(vault_path), "mode": "local"},
            "auth": {"type": "api_key", "api_key": None},
            "supabase": {"url": None, "anon_key": "anon"},
        },
        config_path,
    )

    saved = config_path.read_text()
    assert "api_key =" not in saved
    assert "url =" not in saved
    assert "anon_key" in saved

    path = config_utils.get_vault_path({"vault": {"path": str(vault_path)}})
    assert path == vault_path
    assert path.exists()


def test_output_json_ok_warn_and_error(capsys):
    out = Output(GlobalContext(json_output=True))

    out.ok("Done", {"count": 2})
    out.warn("Careful", reason="test")

    with pytest.raises(typer.Exit) as exc:
        out.error("Boom", exit_code=7, detail="x")

    lines = capsys.readouterr().out.strip().splitlines()
    assert json.loads(lines[0]) == {"data": {"count": 2}, "status": "ok", "title": "Done"}
    assert json.loads(lines[1]) == {
        "status": "warn",
        "warning": {"message": "Careful", "reason": "test"},
    }
    assert json.loads(lines[2]) == {
        "error": {"detail": "x", "exit_code": 7, "message": "Boom"},
        "status": "error",
    }
    assert exc.value.exit_code == 7


def test_output_plain_ok_warn_error_and_table(capsys):
    table = Table()
    table.add_column("Name")
    table.add_column("Value")
    table.add_row("mode", "local")

    out = Output(GlobalContext(plain=True))
    out.ok("Done", {"count": 2}, table=table)
    out.warn("Careful", reason="test")

    with pytest.raises(typer.Exit) as exc:
        out.error("Boom", exit_code=3, detail="x")

    output = capsys.readouterr().out
    assert "Done" in output
    assert "count: 2" in output
    assert "Name | Value" in output
    assert "mode | local" in output
    assert "Careful" in output
    assert "reason: test" in output
    assert "Boom" in output
    assert "detail: x" in output
    assert exc.value.exit_code == 3


def test_table_to_plain_handles_ragged_columns():
    table = Table()
    table.add_column("A")
    table.add_column("B")
    table.add_row("one", "two")

    rendered = _table_to_plain(table)

    assert rendered.splitlines() == ["A | B", "one | two"]


def test_status_helpers():
    checks = [
        SimpleNamespace(status="ok"),
        SimpleNamespace(status="warn"),
        SimpleNamespace(status="fail"),
        SimpleNamespace(status="ok"),
    ]

    assert status_cmd._counts(cast(list[status_cmd.CheckResult], checks)) == (2, 1, 1)
    assert status_cmd._status_chip("ok") == "✓ ok"
    assert status_cmd._status_chip("warn") == "⚠ warn"
    assert status_cmd._status_chip("fail") == "✖ fail"
    assert status_cmd._status_chip("other") == "✖ fail"


def test_status_callback_json(monkeypatch, capsys):
    ctx = Mock(spec=typer.Context)
    gctx = GlobalContext(json_output=True, profile="demo")
    profile = SimpleNamespace(mode="managed", name="demo")
    checks = [
        SimpleNamespace(name="config", status="ok", detail="ready"),
        SimpleNamespace(name="network", status="warn", detail="offline"),
    ]

    monkeypatch.setattr(status_cmd, "get_global_context", lambda _ctx: gctx)
    monkeypatch.setattr(
        status_cmd,
        "run_diagnostics",
        lambda profile_name_override, include_passphrase_unlock: SimpleNamespace(
            profile=profile,
            checks=checks,
        ),
    )

    with pytest.raises(typer.Exit) as exc:
        status_cmd.callback(ctx)

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "managed"
    assert payload["profile"] == "demo"
    assert payload["summary"] == {"ok": 1, "warn": 1, "fail": 0}
    assert payload["checks"][0]["name"] == "config"
    assert exc.value.exit_code == 0


def test_status_callback_plain(monkeypatch, capsys):
    ctx = Mock(spec=typer.Context)
    gctx = GlobalContext(plain=True, profile="demo")
    profile = SimpleNamespace(mode="local", name="demo")
    checks = [SimpleNamespace(name="vault", status="fail", detail="missing")]

    monkeypatch.setattr(status_cmd, "get_global_context", lambda _ctx: gctx)
    monkeypatch.setattr(
        status_cmd,
        "run_diagnostics",
        lambda profile_name_override, include_passphrase_unlock: SimpleNamespace(
            profile=profile,
            checks=checks,
        ),
    )

    with pytest.raises(typer.Exit) as exc:
        status_cmd.callback(ctx)

    output = capsys.readouterr().out
    assert "mode: local" in output
    assert "profile: demo" in output
    assert "summary: ok=0 warn=0 fail=1" in output
    assert "vault: fail (missing)" in output
    assert exc.value.exit_code == 0


def test_quota_format_bytes():
    assert quota_cmd._format_bytes(None) == "0B"
    assert quota_cmd._format_bytes("bad") == "0B"
    assert quota_cmd._format_bytes(12) == "12B"
    assert quota_cmd._format_bytes(2048) == "2.00KiB"
    assert quota_cmd._format_bytes(2 * 1024**2) == "2.00MiB"
    assert quota_cmd._format_bytes(3 * 1024**3) == "3.00GiB"


def test_quota_emit_error_json_and_plain(capsys):
    with pytest.raises(typer.Exit) as exc:
        quota_cmd._emit_error("missing", code=quota_cmd.EXIT_AUTH, json_output=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["category"] == "AUTH"
    assert payload["code"] == "AUTH-QUOTA-001"
    assert payload["exit"] == quota_cmd.EXIT_AUTH
    assert exc.value.exit_code == quota_cmd.EXIT_AUTH

    with pytest.raises(typer.Exit) as exc:
        quota_cmd._emit_error("wrong mode", code=quota_cmd.EXIT_MODE, json_output=False)

    output = capsys.readouterr().out
    assert "Quota status requires managed mode" in output
    assert "matriosha mode set managed" in output
    assert exc.value.exit_code == quota_cmd.EXIT_MODE


def test_quota_status_non_managed_json(monkeypatch, capsys):
    ctx = Mock(spec=typer.Context)
    gctx = GlobalContext(json_output=True, profile="demo")
    profile = SimpleNamespace(mode="local", name="demo", managed_endpoint=None)

    monkeypatch.setattr(quota_cmd, "get_global_context", lambda _ctx: gctx)
    monkeypatch.setattr(quota_cmd, "load_config", lambda: object())
    monkeypatch.setattr(quota_cmd, "get_active_profile", lambda cfg, profile_name: profile)

    with pytest.raises(typer.Exit) as exc:
        quota_cmd.status(ctx, json_flag=False)

    payload = json.loads(capsys.readouterr().out)
    assert payload["category"] == "MODE"
    assert payload["exit"] == quota_cmd.EXIT_MODE
    assert exc.value.exit_code == quota_cmd.EXIT_MODE


def test_quota_status_missing_profile_json(monkeypatch, capsys):
    ctx = Mock(spec=typer.Context)
    gctx = GlobalContext(json_output=True, profile="missing-profile")

    monkeypatch.setattr(quota_cmd, "get_global_context", lambda _ctx: gctx)
    monkeypatch.setattr(quota_cmd, "load_config", lambda: object())

    def _missing_profile(_cfg, _profile_name):
        raise ValueError("Profile 'missing-profile' not found")

    monkeypatch.setattr(quota_cmd, "get_active_profile", _missing_profile)

    with pytest.raises(typer.Exit) as exc:
        quota_cmd.status(ctx, json_flag=False)

    payload = json.loads(capsys.readouterr().out)
    assert payload["category"] == "MODE"
    assert payload["code"] == "MODE-QUOTA-001"
    assert payload["exit"] == quota_cmd.EXIT_MODE
    assert "missing-profile" in payload["debug"]
    assert exc.value.exit_code == quota_cmd.EXIT_MODE


def test_quota_status_missing_token_plain(monkeypatch, capsys):
    ctx = Mock(spec=typer.Context)
    gctx = GlobalContext(plain=True, profile="demo")
    profile = SimpleNamespace(
        mode="managed", name="demo", managed_endpoint="https://managed.example"
    )

    monkeypatch.setattr(quota_cmd, "get_global_context", lambda _ctx: gctx)
    monkeypatch.setattr(quota_cmd, "load_config", lambda: object())
    monkeypatch.setattr(quota_cmd, "get_active_profile", lambda cfg, profile_name: profile)
    monkeypatch.setattr(quota_cmd, "resolve_access_token", lambda profile_name: None)

    with pytest.raises(typer.Exit) as exc:
        quota_cmd.status(ctx, json_flag=False)

    output = capsys.readouterr().out
    assert "Managed session token missing" in output
    assert "matriosha auth login" in output
    assert exc.value.exit_code == quota_cmd.EXIT_AUTH


def test_mode_set_managed_without_token_does_not_mutate_profile(monkeypatch, capsys):
    import matriosha.cli.commands.mode.set as mode_set_cmd
    from matriosha.core.config import MatrioshaConfig, Profile
    from datetime import datetime, timezone

    ctx = Mock(spec=typer.Context)
    gctx = GlobalContext(json_output=True, profile=None)
    ctx.obj = gctx

    profile = Profile(name="default", mode="local", created_at=datetime.now(timezone.utc))
    cfg = MatrioshaConfig(profiles={"default": profile}, active_profile="default")
    saved = []

    monkeypatch.setattr(mode_set_cmd, "get_global_context", lambda _ctx: gctx)
    monkeypatch.setattr(mode_set_cmd, "load_config", lambda: cfg)
    monkeypatch.setattr(mode_set_cmd, "save_config", lambda new_cfg: saved.append(new_cfg))
    monkeypatch.setattr(mode_set_cmd, "resolve_access_token", lambda profile_name: None)

    with pytest.raises(typer.Exit) as exc:
        mode_set_cmd.set_mode(ctx, "managed")

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert "managed session token missing" in payload["error"]["message"]
    assert exc.value.exit_code == 20
    assert cfg.profiles["default"].mode == "local"
    assert saved == []


def test_mode_show_missing_profile_json_error(monkeypatch, capsys):
    import matriosha.cli.commands.mode.show as mode_show_cmd
    from matriosha.core.config import MatrioshaConfig

    ctx = Mock(spec=typer.Context)
    gctx = GlobalContext(json_output=True, profile="phase2-e2e")
    ctx.obj = gctx

    monkeypatch.setattr(mode_show_cmd, "get_global_context", lambda _ctx: gctx)
    monkeypatch.setattr(mode_show_cmd, "load_config", lambda: MatrioshaConfig())

    with pytest.raises(typer.Exit) as exc:
        mode_show_cmd.show(ctx)

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "error",
        "error": {"message": "Profile 'phase2-e2e' not found", "exit_code": 2},
    }
    assert exc.value.exit_code == 2
