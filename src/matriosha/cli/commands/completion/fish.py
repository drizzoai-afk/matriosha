"""Fish completion command."""

from __future__ import annotations

import typer

from .common import completion_script


def completion_fish() -> None:
    """Print Fish completion script."""

    typer.echo(completion_script("fish"))


def register(app: typer.Typer) -> None:
    app.command("fish")(completion_fish)
