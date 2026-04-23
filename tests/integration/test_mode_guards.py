from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.adversarial
def test_managed_only_commands_rejected_in_local_mode(initialized_vault: str, cli_runner: IntegrationCliRunner) -> None:
    commands = [
        ["auth", "login", "--json"],
        ["token", "list", "--json"],
        ["agent", "list", "--json"],
        ["vault", "sync", "--json"],
        ["billing", "status"],
    ]

    for command in commands:
        result = cli_runner.invoke(command)
        assert result.exit_code == 30, f"{command} should exit 30, got {result.exit_code}: {result.stdout}"
