"""Matriosha CLI main application entrypoint."""

from __future__ import annotations

import sys
from typing import Optional

import typer
from typer.main import get_command

from matriosha.cli.commands import (
    agent,
    auth,
    billing,
    completion,
    doctor,
    init,
    memory,
    mode,
    quota,
    status,
    token,
    vault,
)
from matriosha.cli.tui.launcher import launch_interactive_launcher, should_launch_tui
from matriosha.cli.utils.context import build_global_context

app = typer.Typer(
    name="matriosha",
    help="Matriosha CLI command launcher.",
    no_args_is_help=False,
)


def _run_typer_command(command_args: list[str]) -> int:
    command = get_command(app)
    try:
        command.main(args=command_args, prog_name="matriosha", standalone_mode=False)
        return 0
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 1


@app.callback(invoke_without_command=True)
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

    if ctx.invoked_subcommand is not None:
        return

    if should_launch_tui(
        sys.argv,
        sys.stdout.isatty(),
        json_output=json_output,
        plain=plain,
    ):
        raise typer.Exit(code=launch_interactive_launcher(_run_typer_command))

    typer.echo(ctx.get_help())
    raise typer.Exit(code=0)


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
app.command("init", help="Intelligent dependency bootstrap for first-run setup.")(init.init_cmd)


if __name__ == "__main__":
    app()
