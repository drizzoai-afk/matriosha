"""Shell completion helpers for Matriosha CLI."""

from __future__ import annotations

import os
from pathlib import Path

import typer
import typer.completion

from cli.utils.errors import EXIT_USAGE

app = typer.Typer(help="Shell completion integration helpers.", no_args_is_help=True)

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


def _completion_script(shell: str) -> str:
    script = typer.completion.get_completion_script(
        prog_name="matriosha",
        complete_var=COMPLETE_VAR,
        shell=shell,
    )
    commands_line = "# commands: " + " ".join(COMMAND_NAMES)
    return f"{commands_line}\n{script}"


def _detect_shell_from_env() -> str:
    shell_path = (os.environ.get("SHELL") or "").strip()
    shell_name = Path(shell_path).name.lower()

    if shell_name in SUPPORTED_SHELLS:
        return shell_name

    raise typer.BadParameter(
        "Could not detect shell from $SHELL. Use --shell bash|zsh|fish.",
        param_hint="--shell",
    )


def _resolve_shell(shell: str | None) -> str:
    if shell is None or shell == "auto":
        return _detect_shell_from_env()

    candidate = shell.lower()
    if candidate not in SUPPORTED_SHELLS:
        raise typer.BadParameter("Supported values: bash, zsh, fish", param_hint="--shell")

    return candidate


def _shell_rc_path(shell: str) -> Path:
    home = Path.home()
    if shell == "bash":
        return home / ".bashrc"
    if shell == "zsh":
        return home / ".zshrc"
    return home / ".config" / "fish" / "config.fish"


def _install_script(shell: str) -> tuple[Path, bool]:
    target = _shell_rc_path(shell)
    target.parent.mkdir(parents=True, exist_ok=True)

    content = target.read_text(encoding="utf-8") if target.exists() else ""
    if MARKER_BEGIN in content and MARKER_END in content:
        return target, False

    block = (
        f"{MARKER_BEGIN}\n"
        f"# shell={shell}\n"
        f"{_completion_script(shell).rstrip()}\n"
        f"{MARKER_END}\n"
    )

    if content and not content.endswith("\n"):
        content += "\n"
    if content:
        content += "\n"

    target.write_text(content + block, encoding="utf-8")
    return target, True


@app.command("bash")
def completion_bash() -> None:
    """Print Bash completion script."""

    typer.echo(_completion_script("bash"))


@app.command("zsh")
def completion_zsh() -> None:
    """Print Zsh completion script."""

    typer.echo(_completion_script("zsh"))


@app.command("fish")
def completion_fish() -> None:
    """Print Fish completion script."""

    typer.echo(_completion_script("fish"))


@app.command("install")
def install_completion(
    shell: str | None = typer.Option(
        None,
        "--shell",
        help="Target shell (bash|zsh|fish). Auto-detected from $SHELL when omitted or set to 'auto'.",
    ),
) -> None:
    """Install shell completion block in shell config file."""

    try:
        resolved_shell = _resolve_shell(shell)
    except typer.BadParameter as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=EXIT_USAGE) from exc

    target, installed = _install_script(resolved_shell)
    if installed:
        typer.echo(f"Installed {resolved_shell} completion in {target}")
    else:
        typer.echo(f"Completion already installed in {target}")
