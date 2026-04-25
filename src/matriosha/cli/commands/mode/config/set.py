"""Set mode configuration values command."""

from __future__ import annotations

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_USAGE
from matriosha.cli.utils.output import resolve_output
from matriosha.core.config import load_config, save_config


def set_config(ctx: typer.Context, key: str, value: str) -> None:
    """Set supported config key values (currently managed.auto_sync)."""

    out = resolve_output(ctx)
    get_global_context(ctx)
    cfg = load_config()

    if key != "managed.auto_sync":
        raise typer.Exit(code=EXIT_USAGE)

    lowered = value.strip().lower()
    if lowered not in {"true", "false"}:
        raise typer.Exit(code=EXIT_USAGE)

    cfg.managed.auto_sync = lowered == "true"
    save_config(cfg)

    payload = {
        "status": "ok",
        "operation": "mode.config.set",
        "data": {"key": key, "value": cfg.managed.auto_sync},
        "error": None,
    }
    if out.ctx.json_output:
        out.json(payload)
        return

    out.ok("config updated", {"key": key, "value": str(cfg.managed.auto_sync).lower()})


def register(app: typer.Typer) -> None:
    app.command("set")(set_config)
