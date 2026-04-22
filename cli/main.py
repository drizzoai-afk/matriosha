"""Matriosha CLI main application entrypoint."""

from __future__ import annotations

from typing import Optional

import typer

from cli.commands import (
    agent,
    auth,
    billing,
    completion,
    doctor,
    memory,
    mode,
    quota,
    status,
    token,
    vault,
)
from cli.utils.context import build_global_context

app = typer.Typer(
    name="matriosha",
    help="Matriosha CLI command launcher.",
    no_args_is_help=True,
)


@app.callback()
def main_callback(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    plain: bool = typer.Option(False, "--plain", help="Disable rich formatting."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output."),
    debug: bool = typer.Option(False, "--debug", help="Enable debug output."),
    profile: Optional[str] = typer.Option(None, "--profile", help="Use a named profile."),
    mode_value: str = typer.Option(
        "local", "--mode", help="Override runtime mode for this command invocation."
    ),
) -> None:
    """Set shared global context for all command groups."""

    ctx.obj = build_global_context(
        json_output=json_output,
        plain=plain,
        verbose=verbose,
        debug=debug,
        profile=profile,
        mode=mode_value,
    )


app.add_typer(mode.app, name="mode")
app.add_typer(auth.app, name="auth")
app.add_typer(billing.app, name="billing")
app.add_typer(quota.app, name="quota")
app.add_typer(vault.app, name="vault")
app.add_typer(memory.app, name="memory")
app.add_typer(token.app, name="token")
app.add_typer(agent.app, name="agent")
app.add_typer(status.app, name="status")
app.add_typer(doctor.app, name="doctor")
app.add_typer(completion.app, name="completion")


if __name__ == "__main__":
    app()
