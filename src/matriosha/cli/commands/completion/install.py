"""Shell completion install command."""

from __future__ import annotations

import typer

from matriosha.cli.utils.errors import EXIT_USAGE

from .common import install_script, resolve_shell


def install_completion(
    shell: str | None = typer.Option(
        None,
        "--shell",
        help="Target shell (bash|zsh|fish). Auto-detected from $SHELL when omitted or set to 'auto'.",
    ),
) -> None:
    """Install shell completion block in shell config file."""

    try:
        resolved_shell = resolve_shell(shell)
    except typer.BadParameter as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=EXIT_USAGE) from exc

    target, installed = install_script(resolved_shell)
    if installed:
        typer.echo(f"Installed {resolved_shell} completion in {target}")
    else:
        typer.echo(f"Completion already installed in {target}")


def register(app: typer.Typer) -> None:
    app.command("install")(install_completion)
