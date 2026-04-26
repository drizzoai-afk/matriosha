"""Auth status alias command."""

from __future__ import annotations

import typer

from .whoami import _run_whoami


def register(app: typer.Typer) -> None:
    @app.command("status")
    def status(
        ctx: typer.Context,
        json_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Alias for whoami, for script-friendly auth status checks."""

        _run_whoami(ctx, json_flag=json_flag, operation="auth.status")
