"""Local semantic index database helper commands."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Annotated

import typer
from rich import box
from rich.table import Table

from matriosha.cli.brand.theme import console as make_console
from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_INTEGRITY, EXIT_OK
from matriosha.core.local_db import (
    DEFAULT_LOCAL_DATABASE_URL,
    DEFAULT_LOCAL_DB_CONTAINER,
    DEFAULT_LOCAL_DB_IMAGE,
    DEFAULT_LOCAL_DB_PORT,
    DEFAULT_LOCAL_DB_VOLUME,
    LOCAL_DB_AUTO_START_ENV,
    LocalDatabaseError,
    docker_available,
    ensure_default_local_pgvector,
)
from matriosha.core.local_pgvector import LOCAL_DATABASE_URL_ENV, LOCAL_VECTOR_BACKEND_ENV


def container_status() -> str:
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", DEFAULT_LOCAL_DB_CONTAINER],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return "unknown"
    if result.returncode != 0:
        return "missing"
    return result.stdout.strip() or "unknown"


def status_payload() -> dict[str, object]:
    configured_url = os.getenv(LOCAL_DATABASE_URL_ENV)
    docker_ok = docker_available()
    return {
        "backend_env": os.getenv(LOCAL_VECTOR_BACKEND_ENV, "pgvector"),
        "database_url_env_set": bool(configured_url),
        "database_url": configured_url or DEFAULT_LOCAL_DATABASE_URL,
        "auto_start_env": os.getenv(LOCAL_DB_AUTO_START_ENV, "1"),
        "docker_available": docker_ok,
        "container": DEFAULT_LOCAL_DB_CONTAINER,
        "container_status": container_status() if docker_ok else "docker-unavailable",
        "image": DEFAULT_LOCAL_DB_IMAGE,
        "volume": DEFAULT_LOCAL_DB_VOLUME,
        "port": DEFAULT_LOCAL_DB_PORT,
    }


def index_status_cmd(ctx: typer.Context) -> None:
    """Show local semantic index database status."""

    gctx = get_global_context(ctx)
    payload = status_payload()

    if gctx.json_output:
        typer.echo(json.dumps(payload, sort_keys=True))
        raise typer.Exit(code=EXIT_OK)

    if gctx.plain:
        for key, value in payload.items():
            typer.echo(f"{key}: {value}")
        raise typer.Exit(code=EXIT_OK)

    console = make_console()
    console.print("[accent]MATRIOSHA MEMORY INDEX[/accent] [muted]PostgreSQL/pgvector[/muted]")

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="accent")
    table.add_column("Setting", style="primary", no_wrap=True)
    table.add_column("Value", style="muted")

    for key, value in payload.items():
        table.add_row(str(key), str(value))

    console.print(table)
    raise typer.Exit(code=EXIT_OK)


def index_start_cmd(
    ctx: typer.Context,
    timeout: Annotated[
        float, typer.Option("--timeout", help="Seconds to wait for Postgres readiness.")
    ] = 30.0,
) -> None:
    """Create/start the local semantic index database."""

    gctx = get_global_context(ctx)
    try:
        url = ensure_default_local_pgvector(timeout_seconds=timeout)
    except LocalDatabaseError as exc:
        if gctx.json_output:
            typer.echo(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        else:
            typer.echo(f"memory index database setup failed: {exc}", err=True)
        raise typer.Exit(code=EXIT_INTEGRITY) from exc

    payload = {
        "ok": True,
        "database_url": url,
        "container": DEFAULT_LOCAL_DB_CONTAINER,
        "image": DEFAULT_LOCAL_DB_IMAGE,
    }

    if gctx.json_output:
        typer.echo(json.dumps(payload, sort_keys=True))
        raise typer.Exit(code=EXIT_OK)

    typer.echo(f"memory index database is ready: {url}")
    typer.echo("To use an explicit environment variable, run:")
    typer.echo(f"export {LOCAL_DATABASE_URL_ENV}='{url}'")
    raise typer.Exit(code=EXIT_OK)


def index_env_cmd() -> None:
    """Print shell exports for the local semantic index database."""

    typer.echo(f"export {LOCAL_VECTOR_BACKEND_ENV}=pgvector")
    typer.echo(f"export {LOCAL_DATABASE_URL_ENV}='{DEFAULT_LOCAL_DATABASE_URL}'")
    typer.echo(f"export {LOCAL_DB_AUTO_START_ENV}=1")


def register(app: typer.Typer) -> None:
    """Register memory index database helper commands."""

    app.command(
        "index-status",
        help="Show local semantic index database status.",
    )(index_status_cmd)
    app.command(
        "index-start",
        help="Create/start the local semantic index database.",
    )(index_start_cmd)
    app.command(
        "index-env",
        help="Print shell exports for the local semantic index database.",
    )(index_env_cmd)
