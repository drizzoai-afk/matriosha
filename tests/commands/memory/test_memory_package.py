from typer.testing import CliRunner

from matriosha.cli.commands.memory import app


runner = CliRunner()


def test_memory_package_imports():
    assert app is not None


def test_memory_help_exits_zero():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Save, find, and manage encrypted memories." in result.output


def test_memory_expected_commands_registered():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0

    for command in [
        "remember",
        "recall",
        "search",
        "list",
        "delete",
        "compress",
        "decompress",
    ]:
        assert command in result.output
