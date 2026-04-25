"""Shared shell completion helpers."""

from __future__ import annotations

import os
from pathlib import Path

import typer
import typer.completion

SUPPORTED_SHELLS = {"bash", "zsh", "fish"}
COMPLETE_VAR = "_MATRIOSHA_COMPLETE"
MARKER_BEGIN = "# >>> matriosha completion >>>"
MARKER_END = "# <<< matriosha completion <<<"
COMMAND_NAMES = (
    "mode",
    "auth",
    "billing",
    "quota",
    "vault",
    "memory",
    "token",
    "agent",
    "status",
    "doctor",
    "completion",
)


def completion_script(shell: str) -> str:
    script = typer.completion.get_completion_script(
        prog_name="matriosha",
        complete_var=COMPLETE_VAR,
        shell=shell,
    )
    commands_line = "# commands: " + " ".join(COMMAND_NAMES)
    return f"{commands_line}\n{script}"


def detect_shell_from_env() -> str:
    shell_path = (os.environ.get("SHELL") or "").strip()
    shell_name = Path(shell_path).name.lower()

    if shell_name in SUPPORTED_SHELLS:
        return shell_name

    raise typer.BadParameter(
        "Could not detect shell from $SHELL. Use --shell bash|zsh|fish.",
        param_hint="--shell",
    )


def resolve_shell(shell: str | None) -> str:
    if shell is None or shell == "auto":
        return detect_shell_from_env()

    candidate = shell.lower()
    if candidate not in SUPPORTED_SHELLS:
        raise typer.BadParameter("Supported values: bash, zsh, fish", param_hint="--shell")

    return candidate


def shell_rc_path(shell: str) -> Path:
    home = Path.home()
    if shell == "bash":
        return home / ".bashrc"
    if shell == "zsh":
        return home / ".zshrc"
    return home / ".config" / "fish" / "config.fish"


def install_script(shell: str) -> tuple[Path, bool]:
    target = shell_rc_path(shell)
    target.parent.mkdir(parents=True, exist_ok=True)

    content = target.read_text(encoding="utf-8") if target.exists() else ""
    if MARKER_BEGIN in content and MARKER_END in content:
        return target, False

    block = (
        f"{MARKER_BEGIN}\n"
        f"# shell={shell}\n"
        f"{completion_script(shell).rstrip()}\n"
        f"{MARKER_END}\n"
    )

    if content and not content.endswith("\n"):
        content += "\n"
    if content:
        content += "\n"

    target.write_text(content + block, encoding="utf-8")
    return target, True
