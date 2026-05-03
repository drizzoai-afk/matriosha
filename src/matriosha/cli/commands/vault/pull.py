"""Vault pull command."""

from __future__ import annotations

import asyncio
import json
import os

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from matriosha.cli.brand.theme import console as make_console
from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_AUTH, EXIT_INTEGRITY, EXIT_OK
from matriosha.cli.utils.mode_guard import require_mode
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.managed.auth import resolve_access_token, resolve_managed_passphrase
from matriosha.core.managed.client import ManagedClient, resolve_managed_endpoint
from matriosha.core.managed.sync import SyncEngine, SyncReport
from matriosha.core.storage_local import LocalStore
from matriosha.core.vault import Vault
from matriosha.core.vectors import get_default_embedder

from .common import _emit_error, _resolve_passphrase


def _emit_pull_report(report: SyncReport, *, json_output: bool, plain: bool, console: Console) -> None:
    payload = report.to_dict()
    payload["status"] = "ok" if not report.errors else "error"
    payload["next"] = [
        "matriosha memory index-start",
        "matriosha memory index",
    ]

    if json_output:
        typer.echo(json.dumps(payload))
        return

    if plain:
        typer.echo(f"pulled: {report.pulled}")
        typer.echo(f"warnings: {len(report.warnings)}")
        typer.echo(f"errors: {len(report.errors)}")
        if report.pulled:
            typer.echo("next: matriosha memory index-start")
            typer.echo("next: matriosha memory index")
        for warning in report.warnings:
            typer.echo(f"warning: {warning}")
        for error in report.errors:
            typer.echo(f"error: {error}")
        return

    table = Table(title="Vault Pull Report", show_header=True, header_style="bold cyan")
    table.add_column("metric")
    table.add_column("value", justify="right")
    table.add_row("pulled", str(report.pulled))
    table.add_row("warnings", str(len(report.warnings)))
    table.add_row("errors", str(len(report.errors)))
    console.print(table)

    if report.pulled:
        console.print("[muted]Next:[/muted] matriosha memory index-start")
        console.print("[muted]Next:[/muted] matriosha memory index")

    if report.warnings:
        warning_table = Table(title="Pull Warnings", show_header=True, header_style="bold yellow")
        warning_table.add_column("warning")
        for warning in report.warnings:
            warning_table.add_row(warning)
        console.print(warning_table)

    if report.errors:
        error_table = Table(title="Pull Errors", show_header=True, header_style="bold red")
        error_table.add_column("error")
        for error in report.errors:
            error_table.add_row(error)
        console.print(error_table)


def register(app: typer.Typer) -> None:
    @app.command("pull")
    def pull(
        ctx: typer.Context,
        json_output_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Pull encrypted memories from managed storage into local storage."""

        require_mode("managed")(ctx)

        gctx = get_global_context(ctx)
        json_output = gctx.json_output or json_output_flag
        console = make_console()

        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)

        token = resolve_access_token(profile.name)
        env_token_active = bool(os.getenv("MATRIOSHA_MANAGED_TOKEN"))
        managed_profile_name = None if env_token_active else profile.name
        if not token:
            _emit_error(
                title="Managed token missing",
                category="AUTH",
                stable_code="AUTH-221",
                exit_code=EXIT_AUTH,
                fix="run `matriosha auth login` or set MATRIOSHA_MANAGED_TOKEN",
                debug="managed session token unavailable",
                json_output=json_output,
                plain=gctx.plain,
            )
            raise typer.Exit(code=EXIT_AUTH)

        endpoint = resolve_managed_endpoint(
            profile.managed_endpoint,
            os.getenv("MATRIOSHA_MANAGED_ENDPOINT"),
        )

        async def _run_pull() -> SyncReport:
            async with ManagedClient(
                token=token,
                base_url=endpoint,
                managed_mode=False,
                profile_name=managed_profile_name,
            ) as client:
                try:
                    await client.whoami()
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(f"managed token validation failed: {type(exc).__name__}: {exc}") from exc

                local = LocalStore(profile.name)
                data_key: bytes | None = None

                try:
                    resolved_passphrase = resolve_managed_passphrase(profile.name) or _resolve_passphrase(
                        provided=None,
                        json_output=json_output,
                    )
                    if isinstance(resolved_passphrase, tuple):
                        passphrase = resolved_passphrase[0]
                    else:
                        passphrase = resolved_passphrase
                    vault = Vault.unlock(profile.name, passphrase)
                    data_key = vault.data_key
                    local = LocalStore(profile.name, data_key=data_key)
                except typer.Exit:
                    raise

                engine = SyncEngine(
                    local=local,
                    remote=client,
                    embedder=get_default_embedder(),
                    data_key=data_key,
                    )
                return await engine.pull()

        try:
            if json_output or gctx.plain:
                report = asyncio.run(_run_pull())
            else:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[bold cyan]{task.description}"),
                    BarColumn(),
                    TimeElapsedColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task("vault pull", total=3)
                    progress.update(task, description="[bold cyan]validating managed session")
                    progress.advance(task)
                    progress.update(task, description="[bold cyan]pulling encrypted memories")
                    report = asyncio.run(_run_pull())
                    progress.advance(task, advance=2)
        except RuntimeError as exc:
            _emit_error(
                title="Managed pull failed",
                category="AUTH",
                stable_code="AUTH-222",
                exit_code=EXIT_AUTH,
                fix="refresh managed credentials and retry",
                debug=str(exc),
                json_output=json_output,
                plain=gctx.plain,
            )
            raise typer.Exit(code=EXIT_AUTH) from exc

        _emit_pull_report(report, json_output=json_output, plain=gctx.plain, console=console)
        if report.errors:
            raise typer.Exit(code=EXIT_INTEGRITY)
        raise typer.Exit(code=EXIT_OK)
