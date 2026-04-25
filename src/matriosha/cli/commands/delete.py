"""Top-level `matriosha delete` shortcut."""

from __future__ import annotations

import typer

from matriosha.cli.commands.memory.delete import delete


def register(app: typer.Typer) -> None:
    """Register the memory delete shortcut."""

    app.command(
        "delete",
        help="Delete saved memories.",
    )(delete)
