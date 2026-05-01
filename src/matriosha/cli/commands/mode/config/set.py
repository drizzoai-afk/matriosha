"""Set mode configuration values command."""

from __future__ import annotations

import typer
from typing import Literal, cast

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_USAGE
from matriosha.cli.utils.output import resolve_output
from matriosha.core.config import load_config, save_config


def set_config(ctx: typer.Context, key: str, value: str) -> None:
    """Set supported config key values (currently managed.auto_sync and managed.vector_mode)."""

    out = resolve_output(ctx)
    get_global_context(ctx)
    cfg = load_config()

    lowered = value.strip().lower()
    if key == "managed.auto_sync":
        if lowered not in {"true", "false"}:
            raise typer.Exit(code=EXIT_USAGE)
        cfg.managed.auto_sync = lowered == "true"
        saved_value: bool | str = cfg.managed.auto_sync
    elif key == "managed.vector_mode":
        if lowered not in {"server", "local"}:
            raise typer.Exit(code=EXIT_USAGE)
        vector_mode = cast(Literal["server", "local"], lowered)
        cfg.managed.vector_mode = vector_mode
        saved_value = cfg.managed.vector_mode
    else:
        raise typer.Exit(code=EXIT_USAGE)

    save_config(cfg)

    payload = {
        "status": "ok",
        "operation": "mode.config.set",
        "data": {"key": key, "value": saved_value},
        "error": None,
    }
    if out.ctx.json_output:
        out.json(payload)
        return

    out.ok("config updated", {"key": key, "value": str(saved_value).lower()})


def register(app: typer.Typer) -> None:
    app.command("set")(set_config)
