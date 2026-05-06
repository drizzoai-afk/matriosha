"""Audit command group."""

from __future__ import annotations

import json

import typer

from matriosha.cli.brand.theme import console as make_console
from matriosha.cli.utils.errors import EXIT_INTEGRITY
from matriosha.cli.utils.output import resolve_output
from matriosha.core.audit import AuditJournal
from matriosha.core.config import get_active_profile, load_config

app = typer.Typer(help="Inspect and verify local audit trail integrity.")


@app.command("verify")
def verify(
    ctx: typer.Context,
    json_output_flag: bool = typer.Option(
        False, "--json", help="Show JSON output for scripts and automation."
    ),
) -> None:
    """Verify the local audit journal hash chain for the active profile."""

    output = resolve_output(ctx, json_flag=json_output_flag)
    gctx = output.ctx
    cfg = load_config()
    profile = get_active_profile(cfg, gctx.profile)
    journal = AuditJournal(profile.name)
    ok, reason = journal.verify()

    data = {
        "profile": profile.name,
        "path": str(journal.path),
        "valid": ok,
        "reason": reason,
    }

    if gctx.json_output:
        typer.echo(
            json.dumps(
                {
                    "status": "ok" if ok else "error",
                    "operation": "audit.verify",
                    "data": data,
                    "error": None
                    if ok
                    else {"category": "INTEGRITY", "code": "INT-901", "message": reason},
                }
            )
        )
    elif gctx.plain:
        typer.echo(f"valid: {str(ok).lower()}")
        typer.echo(f"path: {journal.path}")
        if reason:
            typer.echo(f"reason: {reason}")
    else:
        console = make_console()
        if ok:
            console.print("[bold green]✓ Audit journal valid[/bold green]")
            console.print(f"profile: {profile.name}")
            console.print(f"path: {journal.path}")
        else:
            console.print("[bold red]✖ Audit journal invalid[/bold red]")
            console.print(f"profile: {profile.name}")
            console.print(f"path: {journal.path}")
            console.print(f"reason: {reason}")

    if not ok:
        raise typer.Exit(code=EXIT_INTEGRITY)
