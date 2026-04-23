"""`matriosha status` command implementation."""

from __future__ import annotations

import json

import typer
from rich import box
from rich.table import Table

from cli.brand.theme import console as make_console
from cli.utils.context import get_global_context
from core.diagnostics import CheckResult, run_diagnostics

app = typer.Typer(help="Show overall CLI/system status.", no_args_is_help=False)


def _counts(checks: list[CheckResult]) -> tuple[int, int, int]:
    ok = sum(1 for check in checks if check.status == "ok")
    warn = sum(1 for check in checks if check.status == "warn")
    fail = sum(1 for check in checks if check.status == "fail")
    return ok, warn, fail


def _status_chip(status: str) -> str:
    if status == "ok":
        return "✓ ok"
    if status == "warn":
        return "⚠ warn"
    return "✖ fail"


@app.callback(invoke_without_command=True)
def callback(ctx: typer.Context) -> None:
    """Run non-intrusive diagnostics and show a concise status summary."""

    gctx = get_global_context(ctx)
    result = run_diagnostics(profile_name_override=gctx.profile, include_passphrase_unlock=False)

    ok, warn, fail = _counts(result.checks)

    if gctx.json_output:
        payload = {
            "mode": result.profile.mode,
            "profile": result.profile.name,
            "summary": {"ok": ok, "warn": warn, "fail": fail},
            "checks": [{"name": chk.name, "status": chk.status, "detail": chk.detail} for chk in result.checks],
        }
        typer.echo(json.dumps(payload, sort_keys=True))
        raise typer.Exit(code=0)

    if gctx.plain:
        typer.echo(f"mode: {result.profile.mode}")
        typer.echo(f"profile: {result.profile.name}")
        typer.echo(f"summary: ok={ok} warn={warn} fail={fail}")
        for check in result.checks:
            typer.echo(f"{check.name}: {check.status} ({check.detail})")
        raise typer.Exit(code=0)

    console = make_console()
    summary = f"mode={result.profile.mode}  profile={result.profile.name}  ok={ok} warn={warn} fail={fail}"
    console.print(f"[accent]MATRIOSHA STATUS[/accent] [muted]{summary}[/muted]")

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="accent")
    table.add_column("Check", style="primary", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail", style="muted")

    for check in result.checks:
        style = "success" if check.status == "ok" else "warning" if check.status == "warn" else "danger"
        table.add_row(check.name, f"[{style}]{_status_chip(check.status)}[/{style}]", check.detail)

    console.print(table)
    raise typer.Exit(code=0)
