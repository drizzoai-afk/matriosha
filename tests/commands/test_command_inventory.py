import re
from typing import Any, cast
from typer.main import get_command
from typer.testing import CliRunner

from matriosha.cli.command_manifest import COMMAND_SPECS, GROUP_COMMANDS, ROOT_COMMANDS, launcher_commands
from matriosha.cli.main import app
from matriosha.cli.tui.launcher import ALL_COMMANDS


runner = CliRunner()


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _plain_help(output: str) -> str:
    return ANSI_RE.sub("", output)


EXPECTED_ROOT_GROUPS = list(ROOT_COMMANDS)


EXPECTED_GROUP_COMMANDS = {
    group: list(commands)
    for group, commands in GROUP_COMMANDS.items()
    if commands
}


def test_root_command_groups_are_registered():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0, result.output

    for group in EXPECTED_ROOT_GROUPS:
        assert group in result.output


def test_group_commands_are_registered():
    for group, commands in EXPECTED_GROUP_COMMANDS.items():
        result = runner.invoke(app, [group, "--help"])

        assert result.exit_code == 0, result.output

        for command in commands:
            assert command in result.output


def test_runtime_command_registry_matches_manifest():
    root = cast(Any, get_command(app))
    root_commands = cast(dict[str, Any], root.commands)

    assert set(root_commands) == set(ROOT_COMMANDS)

    for group, expected_commands in GROUP_COMMANDS.items():
        if not expected_commands:
            continue

        group_command = root_commands[group]
        group_commands = cast(dict[str, Any], group_command.commands)
        actual_commands = tuple(group_commands)

        assert actual_commands == expected_commands


def test_launcher_commands_match_manifest():
    assert ALL_COMMANDS == launcher_commands()


def test_manifest_flags_are_registered_in_help():
    for spec in COMMAND_SPECS:
        if not spec.flags:
            continue

        result = runner.invoke(app, [*spec.path, "--help"])

        assert result.exit_code == 0, result.output
        plain_output = _plain_help(result.output)
        for flag in spec.flags:
            assert flag in plain_output, f"{' '.join(spec.path)} missing {flag} in help:\n{plain_output}"


def test_command_modules_avoid_wildcard_common_imports_outside_memory():
    from pathlib import Path

    commands_root = Path("src/matriosha/cli/commands")
    offenders = sorted(
        str(path)
        for path in commands_root.rglob("*.py")
        if "from .common import *" in path.read_text(encoding="utf-8")
        and "src/matriosha/cli/commands/memory/" not in str(path)
    )

    assert offenders == []


def test_command_files_define_at_most_one_click_command():
    from pathlib import Path
    import re

    commands_root = Path("src/matriosha/cli/commands")
    offenders = {}

    for path in commands_root.rglob("*.py"):
        if path.name in {"__init__.py", "common.py"}:
            continue

        text = path.read_text(encoding="utf-8")
        command_decorators = re.findall(r"@(?:\w+\.)?(?:command|callback)\(", text)
        if len(command_decorators) > 1:
            offenders[str(path)] = len(command_decorators)

    assert offenders == {}
