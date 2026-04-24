"""Tests for persistent profile configuration and mode command behavior."""

from __future__ import annotations

import os
import stat

from typer.testing import CliRunner

from matriosha.cli.main import app
from matriosha.core import config as config_module
from matriosha.core.config import load_config


runner = CliRunner()


def _patch_config_dir(monkeypatch, tmp_path):
    root = tmp_path / ".config" / "matriosha"
    monkeypatch.setattr(
        config_module.platformdirs,
        "user_config_dir",
        lambda appname: str(root if appname == "matriosha" else tmp_path / ".config" / appname),
    )
    return root


def test_fresh_dir_creates_default_profile_local(monkeypatch, tmp_path) -> None:
    _patch_config_dir(monkeypatch, tmp_path)

    cfg = load_config()

    assert cfg.active_profile == "default"
    assert "default" in cfg.profiles
    assert cfg.profiles["default"].mode == "local"


def test_mode_set_managed_persists_across_reload(monkeypatch, tmp_path) -> None:
    _patch_config_dir(monkeypatch, tmp_path)

    result = runner.invoke(app, ["mode", "set", "managed"])
    assert result.exit_code == 0

    cfg = load_config()
    assert cfg.profiles[cfg.active_profile].mode == "managed"

    show_result = runner.invoke(app, ["mode", "show"])
    assert show_result.exit_code == 0
    assert "mode: managed" in show_result.stdout


def test_mode_set_garbage_returns_usage_exit_code(monkeypatch, tmp_path) -> None:
    _patch_config_dir(monkeypatch, tmp_path)

    result = runner.invoke(app, ["mode", "set", "garbage"])

    assert result.exit_code == 2


def test_profile_override_mode_show(monkeypatch, tmp_path) -> None:
    _patch_config_dir(monkeypatch, tmp_path)

    set_result = runner.invoke(app, ["--profile", "work", "mode", "set", "managed"])
    assert set_result.exit_code == 0

    show_result = runner.invoke(app, ["--profile", "work", "mode", "show"])
    assert show_result.exit_code == 0
    assert "profile: work" in show_result.stdout
    assert "mode: managed" in show_result.stdout


def test_config_file_permissions_0600_on_unix(monkeypatch, tmp_path) -> None:
    config_dir = _patch_config_dir(monkeypatch, tmp_path)

    _ = load_config()

    cfg_path = config_dir / "config.toml"
    assert cfg_path.exists()

    if os.name != "nt":
        file_mode = stat.S_IMODE(cfg_path.stat().st_mode)
        assert file_mode == 0o600
