from __future__ import annotations

import json

from typer.testing import CliRunner

from matriosha.cli.main import app
import matriosha.cli.main as cli_main


runner = CliRunner()


def test_zero_arg_launcher_uses_tui_in_interactive_context(monkeypatch) -> None:
    calls = {"launch": 0}

    monkeypatch.setattr(cli_main, "should_launch_tui", lambda *args, **kwargs: True)

    def _fake_launch(_runner):
        calls["launch"] += 1
        return 0

    monkeypatch.setattr(cli_main, "launch_interactive_launcher", _fake_launch)

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert calls["launch"] == 1


def test_zero_arg_plain_bypasses_tui(monkeypatch) -> None:
    observed: dict[str, bool] = {"plain": False}

    def _capture_should_launch(argv, stdout_is_tty, *, json_output: bool, plain: bool):
        observed["plain"] = plain
        return False

    monkeypatch.setattr(cli_main, "should_launch_tui", _capture_should_launch)

    def _fail_launch(_runner):  # pragma: no cover - should never execute
        raise AssertionError("launcher should be bypassed in plain mode")

    monkeypatch.setattr(cli_main, "launch_interactive_launcher", _fail_launch)

    result = runner.invoke(app, ["--plain"])

    assert result.exit_code == 0
    assert observed["plain"] is True
    assert "Usage:" in result.stdout


def test_mode_show_json_is_deterministic(monkeypatch, tmp_path) -> None:
    from matriosha.core import config as config_module

    config_root = tmp_path / ".config" / "matriosha"
    monkeypatch.setattr(config_module.platformdirs, "user_config_dir", lambda _app: str(config_root))

    first = runner.invoke(app, ["--json", "mode", "show"])
    second = runner.invoke(app, ["--json", "mode", "show"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first_payload == second_payload
