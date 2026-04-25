"""Zsh completion command."""

from __future__ import annotations

import typer

from .common import completion_script


def completion_zsh() -> None:
    """Print Zsh completion script."""

    typer.echo(completion_script("zsh"))


def register(app: typer.Typer) -> None:
    app.command("zsh")(completion_zsh)
