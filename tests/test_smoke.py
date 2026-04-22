"""Smoke tests for CLI skeleton wiring."""

from cli.main import app


def test_app_exists() -> None:
    assert app is not None


def test_command_groups_import() -> None:
    import cli.commands.mode  # noqa: F401
    import cli.commands.auth  # noqa: F401
    import cli.commands.billing  # noqa: F401
    import cli.commands.quota  # noqa: F401
    import cli.commands.vault  # noqa: F401
    import cli.commands.memory  # noqa: F401
    import cli.commands.token  # noqa: F401
    import cli.commands.agent  # noqa: F401
    import cli.commands.status  # noqa: F401
    import cli.commands.doctor  # noqa: F401
    import cli.commands.completion  # noqa: F401
