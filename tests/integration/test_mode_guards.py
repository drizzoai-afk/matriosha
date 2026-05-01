from __future__ import annotations
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from tests.integration.conftest import IntegrationCliRunner
import pytest


@pytest.mark.integration
@pytest.mark.adversarial
def test_managed_only_commands_rejected_in_local_mode_with_exit_30(
    initialized_vault: str,
    cli_runner: IntegrationCliRunner,
) -> None:
    guarded_commands = [
        ["auth", "login", "--json"],
        ["vault", "sync", "--json"],
        ["billing", "status", "--json"],
    ]

    expected_hint = "this command requires managed mode; run `matriosha mode set managed`"

    for command in guarded_commands:
        result = cli_runner.invoke(command)
        assert result.exit_code == 30, f"{command} should exit 30, got {result.exit_code}: {result.stdout}"
        assert expected_hint in result.stdout.lower(), f"missing explicit mode-guard hint for {command}: {result.stdout}"
