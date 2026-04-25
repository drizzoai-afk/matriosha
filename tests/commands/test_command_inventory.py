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
