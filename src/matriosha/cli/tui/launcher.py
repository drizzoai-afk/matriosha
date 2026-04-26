"""Textual-powered interactive launcher for Matriosha CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import typer

from matriosha.cli.command_manifest import launcher_commands
from matriosha.core.config import get_active_profile, load_config


@dataclass(frozen=True)
class LaunchAction:
    label: str
    value: str


ALL_COMMANDS: dict[str, list[tuple[str, list[str]]]] = launcher_commands()

MAIN_MENU: list[LaunchAction] = [
    LaunchAction("Setup · Init", "init_setup"),
    LaunchAction("Local · Memory", "memory"),
    LaunchAction("Local · Vault", "vault"),
    LaunchAction("Local · Status", "status"),
    LaunchAction("Local · Doctor", "doctor"),
    LaunchAction("Managed · Auth", "auth"),
    LaunchAction("Managed · Billing", "billing"),
    LaunchAction("Managed · Vault Sync", "vault_sync"),
    LaunchAction("Managed · Quota", "quota"),
    LaunchAction("Agents · Tokens", "token"),
    LaunchAction("Agents · Agents", "agent"),
    LaunchAction("Settings · Mode", "mode"),
    LaunchAction("Settings · Completion", "completion"),
    LaunchAction("Settings · Profile", "profile"),
    LaunchAction("Settings · Mode Config", "mode_config"),
    LaunchAction("Utility · All Commands", "all_commands"),
    LaunchAction("Utility · Quit", "quit"),
]


def should_launch_tui(argv: Sequence[str], stdout_is_tty: bool, *, json_output: bool, plain: bool) -> bool:
    """Return True when launcher should own the no-arg interactive experience."""

    if not stdout_is_tty:
        return False

    if json_output or plain:
        return False

    if len(argv) != 1:
        return False

    return Path(argv[0]).name == "matriosha"


def launch_interactive_launcher(
    command_runner: Callable[[list[str]], int],
    *,
    app_factory: Callable[[], object] | None = None,
) -> int:
    """Render and execute the Textual launcher loop."""

    if app_factory is None:
        try:
            from matriosha.cli.tui.textual_app import MatrioshaTextualLauncher
        except ImportError:
            typer.echo(
                "textual is required for the interactive launcher. "
                "Install with: pip install 'matriosha[tui]'"
            )
            return 1

        cfg = load_config()
        active_profile = get_active_profile(cfg, None)
        app: object = MatrioshaTextualLauncher(
            command_map=_command_map(),
            all_commands=ALL_COMMANDS,
            menu_items=MAIN_MENU,
            profile_name=active_profile.name,
            runtime_mode=active_profile.mode,
        )
    else:
        app = app_factory()

    run = getattr(app, "run", None)
    if callable(run):
        run()

    selected = getattr(app, "selected_command", None)
    if selected:
        return command_runner(selected)

    return 0


def _command_map() -> dict[str, list[str]]:
    return {
        "init_setup": ["init", "--help"],
        "memory": ["memory", "--help"],
        "vault": ["vault", "--help"],
        "status": ["status"],
        "doctor": ["doctor"],
        "auth": ["auth", "--help"],
        "billing": ["billing", "--help"],
        "vault_sync": ["vault", "sync", "--help"],
        "quota": ["quota", "status"],
        "token": ["token", "--help"],
        "agent": ["agent", "--help"],
        "mode": ["mode", "--help"],
        "completion": ["completion"],
        "profile": ["profile", "--help"],
        "mode_config": ["mode", "config", "--help"],
    }
