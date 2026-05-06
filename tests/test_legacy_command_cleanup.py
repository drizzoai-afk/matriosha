"""Regression tests for removed legacy command modules.

Matriosha v2 uses grouped commands such as `memory remember` and `vault verify`.
The old top-level command modules must stay out of the active command tree.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from matriosha.cli.main import app


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_COMMAND_FILES = [
    PROJECT_ROOT / "src/matriosha/cli/commands/remember.py",
    PROJECT_ROOT / "src/matriosha/cli/commands/recall.py",
    PROJECT_ROOT / "src/matriosha/cli/commands/verify.py",
    PROJECT_ROOT / "src/matriosha/cli/commands/sync.py",
]


def test_legacy_top_level_command_modules_are_removed() -> None:
    """Dead legacy command modules must not remain in the importable source tree."""

    assert [path for path in LEGACY_COMMAND_FILES if path.exists()] == []


def test_legacy_top_level_commands_are_not_registered() -> None:
    """Old top-level commands must not appear in the root CLI command inventory."""

    command_names = {group.name for group in app.registered_groups} | {
        command.name for command in app.registered_commands
    }

    assert "memory" in command_names
    assert "vault" in command_names
    assert "remember" not in command_names
    assert "recall" not in command_names
    assert "verify" not in command_names
    assert "sync" not in command_names


def test_canonical_grouped_commands_remain_available() -> None:
    """The supported grouped commands remain available after legacy cleanup."""

    runner = CliRunner()

    checks = [
        ["memory", "--help", "remember"],
        ["memory", "--help", "recall"],
        ["vault", "--help", "verify"],
        ["vault", "--help", "sync"],
    ]

    for args in checks:
        expected = args[-1]
        result = runner.invoke(app, args[:-1])
        assert result.exit_code == 0
        assert expected in result.output
