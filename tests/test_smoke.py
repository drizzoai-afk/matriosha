"""Smoke tests for CLI skeleton wiring."""

from matriosha.cli.main import app


def test_app_exists() -> None:
    assert app is not None


def test_command_groups_import() -> None:
    import matriosha.cli.commands.mode  # noqa: F401
    import matriosha.cli.commands.auth  # noqa: F401
    import matriosha.cli.commands.billing  # noqa: F401
    import matriosha.cli.commands.quota  # noqa: F401
    import matriosha.cli.commands.vault  # noqa: F401
    import matriosha.cli.commands.memory  # noqa: F401
    import matriosha.cli.commands.token  # noqa: F401
    import matriosha.cli.commands.agent  # noqa: F401
    import matriosha.cli.commands.status  # noqa: F401
    import matriosha.cli.commands.doctor  # noqa: F401
    import matriosha.cli.commands.completion  # noqa: F401
    import matriosha.cli.commands.init  # noqa: F401
