"""Shared CLI context and global flag parsing for Matriosha."""

from __future__ import annotations

from typing import Literal, cast
from typing import Optional

import typer
from pydantic import BaseModel


class GlobalContext(BaseModel):
    """Global flags shared across all CLI command groups."""

    mode: Literal["local", "managed"] = "local"
    json_output: bool = False
    plain: bool = False
    verbose: bool = False
    debug: bool = False
    profile: Optional[str] = None


def build_global_context(
    json_output: bool = typer.Option(
        False, "--json", help="Show JSON output for scripts and automation."
    ),
    plain: bool = typer.Option(False, "--plain", help="Use simple text without colors or boxes."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
    debug: bool = typer.Option(False, "--debug", help="Enable debug output."),
    profile: Optional[str] = typer.Option(None, "--profile", help="Use a named profile."),
    mode: str = typer.Option(
        "local", "--mode", help="Override runtime mode for this command invocation."
    ),
) -> GlobalContext:
    """Dependency function to parse and construct global CLI context."""

    if mode not in ("local", "managed"):
        mode = "local"
    mode_literal = cast(Literal["local", "managed"], mode)

    return GlobalContext(
        mode=mode_literal,
        json_output=json_output,
        plain=plain,
        verbose=verbose,
        debug=debug,
        profile=profile,
    )


def get_global_context(ctx: typer.Context) -> GlobalContext:
    """Fetch shared context from Typer context object."""

    if isinstance(ctx.obj, GlobalContext):
        return ctx.obj
    return GlobalContext()
