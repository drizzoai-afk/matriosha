from __future__ import annotations

import pytest
from typer.testing import CliRunner

from matriosha.cli.main import app

runner = CliRunner()


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_completion_script_output_contains_command_names(shell: str) -> None:
    result = runner.invoke(app, ["completion", shell])

    assert result.exit_code == 0
    assert result.stdout.strip()
    assert "matriosha" in result.stdout
    assert "memory" in result.stdout
    assert "vault" in result.stdout
