"""`matriosha doctor` command implementation."""

from __future__ import annotations

import json

import typer
from rich import box
from rich.table import Table

from matriosha.cli.brand.theme import console as make_console
from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_INTEGRITY, EXIT_OK
from matriosha.core.diagnostics import CheckResult, run_diagnostics

app = typer.Typer(help="Run diagnostics and remediation checks.", no_args_is_help=False)

_HINTS: dict[str, str] = {
    "python.version": "Install Python 3.11+ and rerun `matriosha doctor`.",
    "dependencies": "Install project dependencies: `pip install -e .`.",
    "config.file": "Repair config via `matriosha mode show` or run `chmod 600 ~/.config/matriosha/config.toml`.",
    "vault.material": "Initialize or repair vault with `matriosha vault init` (use `--force` only if intentional).",
    "vector.index": "Check profile data dir permissions and remove corrupted vector files to regenerate.",
    "managed.endpoint": "Set a valid HTTPS managed endpoint in profile or MATRIOSHA_MANAGED_ENDPOINT.",
    "managed.auth": "Run `matriosha auth login` or export MATRIOSHA_MANAGED_TOKEN.",
    "managed.subscription": "Verify billing via `matriosha billing status` and reactivate subscription if needed.",
    "crypto.self_test": "Verify cryptography install and runtime CPU/OS crypto support.",
    "merkle.self_test": "Check for local code drift in `core/merkle.py` and reinstall package.",
    "time.drift": "Sync system clock (NTP) and rerun diagnostics.",
}


def _status_chip(status: str) -> str:
    if status == "ok":
        return "✓ ok"
    if status == "warn":
        return "⚠ warn"
    return "✖ fail"


def _hint_for(check: CheckResult) -> str:
    default_hint = "No action required."
    if check.status == "ok":
        return default_hint
    return _HINTS.get(check.name, "Review diagnostics detail and rerun with --debug.")


@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
    json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    test_passphrase: str | None = typer.Option(
        None,
        "--test-passphrase",
        help="Optional passphrase used to test vault unlock during diagnostics.",
    ),
) -> None:
    """Run full diagnostics with remediation hints."""

    gctx = get_global_context(ctx)
    json_output = gctx.json_output or json_output_flag

    result = run_diagnostics(
        profile_name_override=gctx.profile,
        include_passphrase_unlock=True,
        test_passphrase=test_passphrase,
    )

    fail_count = sum(1 for chk in result.checks if chk.status == "fail")
    exit_code = EXIT_INTEGRITY if fail_count > 0 else EXIT_OK

    checks_payload = [
        {
            "name": chk.name,
            "status": chk.status,
            "detail": chk.detail,
            "hint": _hint_for(chk),
        }
        for chk in result.checks
    ]

    if json_output:
        typer.echo(json.dumps({"checks": checks_payload}, sort_keys=True))
        raise typer.Exit(code=exit_code)

    if gctx.plain:
        typer.echo(f"mode: {result.profile.mode}")
        typer.echo(f"profile: {result.profile.name}")
        for check in checks_payload:
            typer.echo(f"{check['name']}: {check['status']}")
            typer.echo(f"  detail: {check['detail']}")
            typer.echo(f"  hint: {check['hint']}")
        raise typer.Exit(code=exit_code)

    console = make_console()
    status_line = "healthy" if exit_code == EXIT_OK else "integrity issues detected"
    badge = "✓ PASS" if exit_code == EXIT_OK else "✖ FAIL"
    badge_style = "success" if exit_code == EXIT_OK else "danger"
    console.print(
        f"[accent]MATRIOSHA DOCTOR[/accent] [muted]mode={result.profile.mode}  profile={result.profile.name}[/muted] "
        f"[{badge_style}]{badge}[/{badge_style}] [muted]{status_line}[/muted]"
    )

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="accent")
    table.add_column("Check", style="primary", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail", style="muted")
    table.add_column("Hint")

    for check in checks_payload:
        style = "success" if check["status"] == "ok" else "warning" if check["status"] == "warn" else "danger"
        table.add_row(
            check["name"],
            f"[{style}]{_status_chip(check['status'])}[/{style}]",
            check["detail"],
            check["hint"],
        )

    console.print(table)
    raise typer.Exit(code=exit_code)
