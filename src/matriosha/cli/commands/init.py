"""`matriosha init` command: intelligent dependency bootstrap (P6.9)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.table import Table

from matriosha.cli.brand.theme import console as make_console
from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_OK, EXIT_UNKNOWN
from matriosha.core.dependency_checker import get_system_report
from matriosha.core.dependency_installer import (
    generate_manual_instructions,
    install_python_packages,
    install_system_package,
    verify_installation,
)


SYSTEM_DEPENDENCIES = ("tesseract-ocr", "poppler-utils", "libmagic1")


def _write_markdown_report(payload: dict[str, object]) -> Path:
    report_path = Path.home() / ".matriosha" / "init_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    generated_at = payload.get("generated_at") or datetime.now(timezone.utc).isoformat()
    summary = payload.get("summary", {})
    missing_system = summary.get("missing_system_packages", [])
    missing_python = summary.get("missing_python_packages", [])
    actions = payload.get("actions", [])

    lines = [
        "# Matriosha Init Report",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "## Summary",
        "",
        f"- Ready: **{summary.get('ready')}**",
        f"- Missing system packages: `{', '.join(missing_system) if missing_system else 'none'}`",
        f"- Missing python packages: `{', '.join(missing_python) if missing_python else 'none'}`",
        "",
        "## Actions",
        "",
    ]

    if not actions:
        lines.append("- No installation actions were required.")
    else:
        for action in actions:
            lines.append(
                f"- `{action.get('dependency')}` ({action.get('type')}): "
                f"decision={action.get('decision')} install_ok={action.get('install_ok')} "
                f"verified={action.get('verified')}"
            )
            manual = action.get("manual_instructions")
            if manual:
                lines.append(f"  - manual: `{manual}`")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def _render_human_summary(report: dict[str, object], *, plain: bool) -> None:
    summary = report["summary"]

    if plain:
        typer.echo("matriosha init system report")
        typer.echo(f"os_supported: {report['os'].get('supported')}")
        typer.echo(f"python_compatible: {report['python'].get('compatible')}")
        typer.echo(
            "missing_system: "
            + (", ".join(summary["missing_system_packages"]) if summary["missing_system_packages"] else "none")
        )
        typer.echo(
            "missing_python: "
            + (", ".join(summary["missing_python_packages"]) if summary["missing_python_packages"] else "none")
        )
        return

    console = make_console()
    table = Table(title="Matriosha Init · Dependency Report", show_header=True, header_style="accent")
    table.add_column("Area", style="primary")
    table.add_column("Status")
    table.add_column("Detail", style="muted")

    table.add_row(
        "OS support",
        "✓" if report["os"].get("supported") else "✖",
        str(report["os"].get("reason") or "supported"),
    )
    table.add_row(
        "Python",
        "✓" if report["python"].get("compatible") else "✖",
        f"current={report['python'].get('current')} required={report['python'].get('required')}",
    )
    table.add_row(
        "System deps",
        "✓" if not summary["missing_system_packages"] else "⚠",
        ", ".join(summary["missing_system_packages"]) if summary["missing_system_packages"] else "all present",
    )
    table.add_row(
        "Python deps",
        "✓" if not summary["missing_python_packages"] else "⚠",
        ", ".join(summary["missing_python_packages"]) if summary["missing_python_packages"] else "all present",
    )
    console.print(table)


def _should_auto_approve(*, yes: bool, gctx_json: bool) -> bool:
    _ = gctx_json
    return yes


def _is_interactive() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _confirm_install(*, dependency: str, dep_type: str, auto_approve: bool) -> bool:
    if auto_approve:
        return True
    prompt = (
        f"Install missing {dep_type} dependency '{dependency}' now? "
        "(Tip: use --yes/--auto-approve for non-interactive runs)"
    )
    return typer.confirm(prompt, default=False)


def init_cmd(
    ctx: typer.Context,
    yes: bool = typer.Option(
        False,
        "--yes",
        "--auto-approve",
        help="Install without asking for confirmation.",
    ),
    json_output_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
) -> None:
    """Scan system dependencies and optionally install missing requirements safely."""

    gctx = get_global_context(ctx)
    json_output = gctx.json_output or json_output_flag
    plain = gctx.plain
    auto_approve = _should_auto_approve(yes=yes, gctx_json=json_output)

    try:
        report = get_system_report()
        if not json_output:
            _render_human_summary(report, plain=plain)

        missing_system: list[str] = list(report["summary"]["missing_system_packages"])
        missing_python: list[str] = list(report["summary"]["missing_python_packages"])

        if (missing_system or missing_python) and not auto_approve and not _is_interactive():
            payload = {
                "status": "error",
                "category": "SYS",
                "code": "SYS-INIT-NONTTY",
                "message": "Missing dependencies detected in non-interactive mode. Re-run with --yes/--auto-approve.",
                "data": report,
            }
            if json_output:
                typer.echo(json.dumps(payload, sort_keys=True))
            else:
                typer.echo(payload["message"])
            raise typer.Exit(code=EXIT_UNKNOWN)

        actions: list[dict[str, object]] = []

        for dependency in missing_system:
            approved = _confirm_install(dependency=dependency, dep_type="system", auto_approve=auto_approve)
            action: dict[str, object] = {
                "dependency": dependency,
                "type": "system",
                "decision": "approved" if approved else "skipped",
                "install_ok": None,
                "verified": False,
                "manual_instructions": None,
            }

            if approved:
                install_result = install_system_package(dependency, report["os"])
                action["install_ok"] = bool(install_result.get("success"))
                verify = verify_installation(dependency, "system")
                action["verified"] = bool(verify.get("verified"))
                if not action["verified"]:
                    action["manual_instructions"] = generate_manual_instructions(dependency, report["os"])[
                        "instructions"
                    ]
            actions.append(action)

        approved_python_packages: list[str] = []
        for dependency in missing_python:
            approved = _confirm_install(dependency=dependency, dep_type="python", auto_approve=auto_approve)
            action = {
                "dependency": dependency,
                "type": "python",
                "decision": "approved" if approved else "skipped",
                "install_ok": None,
                "verified": False,
                "manual_instructions": None,
            }
            if approved:
                approved_python_packages.append(dependency)
            actions.append(action)

        if approved_python_packages:
            install_result = install_python_packages(approved_python_packages)
            installed_set = set(install_result.get("installed", []))
            for action in actions:
                if action["type"] != "python" or action["decision"] != "approved":
                    continue
                dependency = str(action["dependency"])
                action["install_ok"] = dependency in installed_set
                verify = verify_installation(dependency, "python")
                action["verified"] = bool(verify.get("verified"))
                if not action["verified"]:
                    action["manual_instructions"] = f"python -m pip install {dependency}"

        final_report = get_system_report()
        final_report["actions"] = actions
        final_report["auto_approve"] = auto_approve
        final_report["generated_at"] = datetime.now(timezone.utc).isoformat()

        report_path = _write_markdown_report(final_report)
        final_report["init_report_path"] = str(report_path)

        if json_output:
            typer.echo(json.dumps({"status": "ok", "operation": "init", "data": final_report}, sort_keys=True))
        elif plain:
            typer.echo("matriosha init complete")
            typer.echo(f"report: {report_path}")
            for action in actions:
                typer.echo(
                    f"{action['type']}:{action['dependency']} decision={action['decision']} "
                    f"install_ok={action['install_ok']} verified={action['verified']}"
                )
        else:
            console = make_console()
            console.print("[success]✓ matriosha init complete[/success]")
            console.print(f"[muted]Report written to {report_path}[/muted]")

        raise typer.Exit(code=EXIT_OK)

    except KeyboardInterrupt:
        payload = {
            "status": "interrupted",
            "message": "Initialization cancelled by user (Ctrl+C). No destructive changes were made.",
        }
        if json_output:
            typer.echo(json.dumps(payload, sort_keys=True))
        else:
            typer.echo(payload["message"])
        raise typer.Exit(code=130)
