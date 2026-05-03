"""Get mode configuration values command."""

from __future__ import annotations

import typer

from matriosha.cli.utils.errors import EXIT_USAGE
from matriosha.cli.utils.output import resolve_output
from matriosha.core.config import load_config


def get_config(ctx: typer.Context, key: str) -> None:
    """Get supported config key values (currently managed.auto_sync)."""

    out = resolve_output(ctx)
    cfg = load_config()

    value: bool
    if key == "managed.auto_sync":
        value = cfg.managed.auto_sync
    else:
        raise typer.Exit(code=EXIT_USAGE)

    payload = {
        "status": "ok",
        "operation": "mode.config.get",
        "data": {"key": key, "value": value},
        "error": None,
    }
    if out.ctx.json_output:
        out.json(payload)
        return

    out.ok("config", {"key": key, "value": str(value).lower()})


def register(app: typer.Typer) -> None:
    app.command("get")(get_config)
