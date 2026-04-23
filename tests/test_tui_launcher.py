from __future__ import annotations

from typer.testing import CliRunner

from cli.main import app
import cli.main as cli_main
import cli.tui.launcher as launcher


runner = CliRunner()


class _FakePrompt:
    def __init__(self, value):
        self._value = value

    def ask(self):
        return self._value


class _FakeQuestionary:
    @staticmethod
    def select(*args, **kwargs):
        return _FakePrompt("quit")


def test_launcher_quit_returns_zero(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(launcher, "questionary", _FakeQuestionary)

    exit_code = launcher.launch_interactive_launcher(lambda _: 99)

    assert exit_code == 0


def test_non_tty_stdout_does_not_launch_tui(monkeypatch) -> None:
    launched = False

    def _fake_launch(_runner):
        nonlocal launched
        launched = True
        return 0

    class _Stdout:
        @staticmethod
        def isatty() -> bool:
            return False

    monkeypatch.setattr(cli_main, "launch_interactive_launcher", _fake_launch)
    monkeypatch.setattr(cli_main.sys, "argv", ["matriosha"])
    monkeypatch.setattr(cli_main.sys, "stdout", _Stdout())

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert launched is False
