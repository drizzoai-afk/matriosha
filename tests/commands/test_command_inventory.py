from typer.testing import CliRunner

from matriosha.cli.main import app


runner = CliRunner()


EXPECTED_ROOT_GROUPS = [
    "mode",
    "auth",
    "billing",
    "quota",
    "vault",
    "memory",
    "token",
    "agent",
    "status",
    "doctor",
    "completion",
    "compress",
    "delete",
]


EXPECTED_GROUP_COMMANDS = {
    "mode": ["show", "set", "config"],
    "auth": ["login", "logout", "whoami", "switch"],
    "billing": ["status", "subscribe", "upgrade", "cancel"],
    "quota": ["status"],
    "vault": ["init", "verify", "rotate", "export", "sync"],
    "memory": ["remember", "recall", "search", "list", "delete", "compress", "decompress"],
    "token": ["generate", "list", "revoke", "inspect"],
    "agent": ["connect", "list", "remove"],
    "completion": ["bash", "zsh", "fish", "install"],
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
