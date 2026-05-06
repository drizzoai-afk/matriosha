"""Unified CLI output helper enforcing JSON/plain/rich visual standards."""

from __future__ import annotations

import json
from typing import Any

import typer
from rich.table import Table

from matriosha.cli.brand.theme import console as make_console
from matriosha.cli.utils.context import GlobalContext, get_global_context


class Output:
    """Single output surface for rich/plain/json command rendering."""

    def __init__(self, ctx: GlobalContext):
        self.ctx = ctx
        self._console = make_console()

    def json(self, payload: dict[str, Any]) -> None:
        """Emit deterministic machine-readable JSON payload."""

        typer.echo(json.dumps(payload, sort_keys=True, ensure_ascii=False))

    def plain(self, text: str) -> None:
        """Emit plain text only output."""

        typer.echo(text)

    def ok(
        self, title: str, body: dict[str, Any] | str = "", *, table: Table | None = None
    ) -> None:
        if self.ctx.json_output:
            payload: dict[str, Any] = {"status": "ok", "title": title}
            if isinstance(body, dict):
                payload["data"] = body
            elif body:
                payload["message"] = str(body)
            self.json(payload)
            return

        if self.ctx.plain:
            self.plain(title)
            if isinstance(body, dict):
                for key, value in body.items():
                    self.plain(f"{key}: {value}")
            elif body:
                self.plain(str(body))
            if table is not None:
                self.plain(_table_to_plain(table))
            return

        self._console.print(f"[success]✓ {title}[/success]")
        if isinstance(body, dict):
            for key, value in body.items():
                self._console.print(f"  [muted]{key}:[/muted] {value}")
        elif body:
            self._console.print(f"  {body}")
        if table is not None:
            self._console.print(table)

    def warn(self, msg: str, **data: Any) -> None:
        if self.ctx.json_output:
            self.json({"status": "warn", "warning": {"message": msg, **data}})
            return

        if self.ctx.plain:
            self.plain(msg)
            for key, value in data.items():
                self.plain(f"{key}: {value}")
            return

        self._console.print(f"[warning]⚠ {msg}[/warning]")
        for key, value in data.items():
            self._console.print(f"  [muted]{key}:[/muted] {value}")

    def error(self, msg: str, *, exit_code: int, **data: Any) -> None:
        if self.ctx.json_output:
            self.json(
                {"status": "error", "error": {"message": msg, "exit_code": exit_code, **data}}
            )
            raise typer.Exit(code=exit_code)

        if self.ctx.plain:
            self.plain(msg)
            for key, value in data.items():
                self.plain(f"{key}: {value}")
            raise typer.Exit(code=exit_code)

        self._console.print(f"[danger]✖ {msg}[/danger]")
        for key, value in data.items():
            self._console.print(f"  [muted]{key}:[/muted] {value}")
        raise typer.Exit(code=exit_code)


def resolve_output(ctx: typer.Context, *, json_flag: bool = False) -> Output:
    """Build Output with merged command-level and global flags."""

    gctx = get_global_context(ctx)
    effective_ctx = gctx.model_copy(update={"json_output": gctx.json_output or json_flag})
    return Output(effective_ctx)


def _table_to_plain(table: Table) -> str:
    headers = [str(column.header) for column in table.columns]
    rows: list[str] = []
    cell_columns = [getattr(column, "_cells", []) for column in table.columns]
    max_rows = max((len(col) for col in cell_columns), default=0)

    rows.append(" | ".join(headers))
    for idx in range(max_rows):
        row_values = []
        for col in cell_columns:
            row_values.append(str(col[idx]) if idx < len(col) else "")
        rows.append(" | ".join(row_values))
    return "\n".join(rows)
