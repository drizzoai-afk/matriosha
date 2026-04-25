"""Bash completion command."""

from __future__ import annotations

import typer

from .common import completion_script


def completion_bash() -> None:
    """Print Bash completion script."""

    typer.echo(completion_script("bash"))


def register(app: typer.Typer) -> None:
    app.command("bash")(completion_bash)
