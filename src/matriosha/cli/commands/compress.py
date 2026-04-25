"""Top-level `matriosha compress` shortcut."""

from __future__ import annotations

import typer

from matriosha.cli.commands.memory.compress import compress


def register(app: typer.Typer) -> None:
    """Register the quota-management compression shortcut."""

    app.command(
        "compress",
        help="Shortcut for `matriosha memory compress --deduplicate`.",
    )(compress)
