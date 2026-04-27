"""Matriosha CLI main application entrypoint."""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Optional

import typer
from typer.main import get_command

from matriosha.cli.commands import (
    agent,
    audit,
    auth,
    billing,
    compress,
    delete,
    doctor,
    init,
    memory,
    mode,
    profile,
    quota,
    status,
    token,
    vault,
)
from matriosha.cli.tui.launcher import launch_interactive_launcher, should_launch_tui
from matriosha.cli.utils.context import build_global_context


def _version_callback(value: bool) -> None:
    if not value:
        return
    try:
        package_version = version("matriosha")
    except PackageNotFoundError:
        package_version = "2.0.0"
    typer.echo(f"matriosha {package_version}")
    raise typer.Exit(code=0)


app = typer.Typer(
    name="matriosha",
    help="Store, protect, and sync encrypted memory for humans and agents.",
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
    json_output: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    plain: bool = typer.Option(False, "--plain", help="Use simple text without colors or boxes."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show more detail while running."),
    debug: bool = typer.Option(False, "--debug", help="Show technical troubleshooting details."),
    version_flag: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the Matriosha version and exit.",
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Use a separate saved workspace/profile."),
    mode_value: str = typer.Option(
        "local", "--mode", help="Run this command in local or managed mode."
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
app.add_typer(profile.app, name="profile")
app.add_typer(auth.app, name="auth")
app.add_typer(audit.app, name="audit")
app.add_typer(billing.app, name="billing")
app.add_typer(quota.app, name="quota")
app.add_typer(vault.app, name="vault")
app.add_typer(memory.app, name="memory")
app.add_typer(token.app, name="token")
app.add_typer(agent.app, name="agent")
app.add_typer(status.app, name="status")
app.add_typer(doctor.app, name="doctor")
compress.register(app)
delete.register(app)
app.command("init", help="Check and install optional tools for available file formats.")(init.init_cmd)


if __name__ == "__main__":
    app()
