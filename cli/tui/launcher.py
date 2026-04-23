"""Interactive Daytona-inspired launcher for Matriosha CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import typer

from cli.brand.banner import print_banner
from cli.brand.theme import console
from core.config import get_active_profile, load_config

try:  # pragma: no cover - optional dependency is validated via runtime path
    import questionary
    from questionary import Choice, Separator
except ImportError:  # pragma: no cover
    questionary = None
    Choice = None
    Separator = None

FOOTER = "↑↓ navigate • Enter select • q quit • ? help"


@dataclass(frozen=True)
class LaunchAction:
    label: str
    value: str


ALL_COMMANDS: dict[str, list[tuple[str, list[str]]]] = {
    "mode": [
        ("mode show", ["mode", "show"]),
        ("mode set <local|managed>", ["mode", "set", "--help"]),
    ],
    "auth": [
        ("auth login", ["auth", "login"]),
        ("auth logout", ["auth", "logout"]),
        ("auth whoami", ["auth", "whoami"]),
        ("auth switch", ["auth", "switch"]),
    ],
    "billing": [
        ("billing status", ["billing", "status"]),
        ("billing subscribe", ["billing", "subscribe"]),
        ("billing upgrade", ["billing", "upgrade"]),
        ("billing cancel", ["billing", "cancel"]),
    ],
    "quota": [
        ("quota status", ["quota", "status"]),
    ],
    "vault": [
        ("vault init", ["vault", "init"]),
        ("vault verify", ["vault", "verify"]),
        ("vault rotate", ["vault", "rotate"]),
        ("vault export", ["vault", "export"]),
        ("vault sync", ["vault", "sync"]),
    ],
    "memory": [
        ("memory remember", ["memory", "remember"]),
        ("memory recall", ["memory", "recall"]),
        ("memory search", ["memory", "search"]),
        ("memory list", ["memory", "list"]),
        ("memory delete", ["memory", "delete"]),
        ("memory compress", ["memory", "compress"]),
        ("memory decompress", ["memory", "decompress"]),
    ],
    "token": [
        ("token generate", ["token", "generate"]),
        ("token list", ["token", "list"]),
        ("token revoke", ["token", "revoke"]),
        ("token inspect", ["token", "inspect"]),
    ],
    "agent": [
        ("agent connect", ["agent", "connect"]),
        ("agent list", ["agent", "list"]),
        ("agent remove", ["agent", "remove"]),
    ],
    "status": [
        ("status", ["status"]),
    ],
    "doctor": [
        ("doctor", ["doctor"]),
    ],
    "completion": [
        ("completion", ["completion"]),
    ],
}

MAIN_MENU: list[LaunchAction] = [
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
    LaunchAction("Settings · Profile/Config", "profile_config"),
    LaunchAction("Utility · All Commands", "all_commands"),
    LaunchAction("Utility · ? Help", "help"),
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


def launch_interactive_launcher(command_runner: Callable[[list[str]], int]) -> int:
    """Render and execute the interactive launcher loop."""

    if questionary is None:
        typer.echo("questionary is required for the interactive launcher. Install with: pip install 'matriosha[tui]'")
        return 1

    while True:
        _render_header()
        selected = questionary.select(
            "Select a command group",
            choices=_build_main_choices(),
            qmark="",
            instruction="",
            use_shortcuts=True,
        ).ask()

        if selected is None or selected == "quit":
            return 0

        if selected == "help":
            _render_help()
            continue

        if selected == "all_commands":
            command = _select_all_commands()
            if command:
                return command_runner(command)
            continue

        command = _dispatch_from_main_selection(selected)
        if command:
            return command_runner(command)


def _build_main_choices() -> list[object]:
    if Separator is None or Choice is None:
        return [item.value for item in MAIN_MENU]

    sectioned_values: list[tuple[str, list[str]]] = [
        ("Local", ["memory", "vault", "status", "doctor"]),
        ("Managed", ["auth", "billing", "vault_sync", "quota"]),
        ("Agents", ["token", "agent"]),
        ("Settings", ["mode", "completion", "profile_config"]),
        ("Utility", ["all_commands", "help", "quit"]),
    ]

    by_value = {item.value: item for item in MAIN_MENU}
    choices: list[object] = []
    for section, values in sectioned_values:
        choices.append(Separator(f"=== {section} ==="))
        for value in values:
            item = by_value[value]
            if value == "help":
                choices.append(Choice(item.label, value=item.value, shortcut_key="?"))
            elif value == "quit":
                choices.append(Choice(item.label, value=item.value, shortcut_key="q"))
            else:
                choices.append(Choice(item.label, value=item.value))

    return choices


def _dispatch_from_main_selection(selected: str) -> list[str] | None:
    command_map: dict[str, list[str]] = {
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
        "profile_config": ["mode", "config", "--help"],
    }
    return command_map.get(selected)


def _render_header() -> None:
    cfg = load_config()
    active_profile = get_active_profile(cfg, None)
    status_line = f"active profile: {active_profile.name} | mode: {active_profile.mode}"
    if active_profile.mode == "managed":
        status_line += " | subscription: [MANAGED]"

    c = console()
    print_banner(c)
    c.print(status_line, style="muted")
    c.print(FOOTER, style="accent")


def _render_help() -> None:
    typer.echo("")
    typer.echo("Launcher help")
    typer.echo("- Use arrow keys to move through categories.")
    typer.echo("- Press Enter to open a command group or execute a selected command.")
    typer.echo("- Select 'All Commands' for the full command catalog from SPECIFICATION.md §3.")
    typer.echo("- Press q or choose Quit to exit.")
    typer.echo("")


def _select_all_commands() -> list[str] | None:
    if questionary is None:
        return None

    typer.echo("")
    typer.echo("All Commands (SPECIFICATION.md §3)")
    for group, commands in ALL_COMMANDS.items():
        typer.echo(f"[{group}]")
        for display, _ in commands:
            typer.echo(f"  - {display}")

    choices: list[object] = []
    if Separator is None or Choice is None:  # pragma: no cover - guarded by import
        return None

    for group, commands in ALL_COMMANDS.items():
        choices.append(Separator(f"=== {group} ==="))
        for display, args in commands:
            choices.append(Choice(display, value=args))

    choices.append(Separator("=== utility ==="))
    choices.append(Choice("Back", value=None, shortcut_key="q"))

    return questionary.select(
        "Select a command to run",
        choices=choices,
        qmark="",
        instruction="",
        use_shortcuts=True,
    ).ask()
