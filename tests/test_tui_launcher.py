from __future__ import annotations

from typer.testing import CliRunner

from matriosha.cli.main import app
import matriosha.cli.main as cli_main
import matriosha.cli.tui.launcher as launcher


runner = CliRunner()


class _FakeApp:
    def __init__(self, selected_command=None):
        self.selected_command = selected_command
        self.run_called = False

    def run(self):
        self.run_called = True


def test_launcher_quit_returns_zero() -> None:
    fake = _FakeApp(selected_command=None)

    exit_code = launcher.launch_interactive_launcher(lambda _: 99, app_factory=lambda: fake)

    assert fake.run_called is True
    assert exit_code == 0


def test_launcher_dispatches_selected_command() -> None:
    fake = _FakeApp(selected_command=["status"])
    invoked: list[list[str]] = []

    def _runner(args: list[str]) -> int:
        invoked.append(args)
        return 7

    exit_code = launcher.launch_interactive_launcher(_runner, app_factory=lambda: fake)

    assert exit_code == 7
    assert invoked == [["status"]]


def test_should_launch_tui_gating() -> None:
    assert launcher.should_launch_tui(["matriosha"], True, json_output=False, plain=False) is True
    assert launcher.should_launch_tui(["matriosha", "status"], True, json_output=False, plain=False) is False
    assert launcher.should_launch_tui(["matriosha"], False, json_output=False, plain=False) is False
    assert launcher.should_launch_tui(["matriosha"], True, json_output=True, plain=False) is False
    assert launcher.should_launch_tui(["matriosha"], True, json_output=False, plain=True) is False


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
