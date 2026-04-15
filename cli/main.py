"""
Matriosha CLI — Main Entry Point

Typer-based CLI with Rich UI for seamless memory management.
Commands: init, remember, recall, sync, verify, export, import
"""

import typer
from typing import Optional
from rich.console import Console
from rich.theme import Theme

# Custom theme for Matriosha branding
matriosha_theme = Theme({
    "info": "cyan",
    "success": "green bold",
    "warning": "yellow",
    "error": "red bold",
    "header": "bold magenta",
    "accent": "bright_cyan",
})

console = Console(theme=matriosha_theme)

app = typer.Typer(
    name="matriosha",
    help="[header]Secure Agentic Memory Layer[/header] — [accent]Binary standard for AI memory[/accent]",
    add_completion=True,
    rich_markup_mode="rich",
)

# Register commands
from cli.commands import init, remember, recall, sync, verify, export_import

app.command(name="init")(init.init_cmd)
app.command(name="remember")(remember.remember_cmd)
app.command(name="recall")(recall.recall_cmd)
app.command(name="sync")(sync.sync_cmd)
app.command(name="verify")(verify.verify_cmd)
app.command(name="export")(export_import.export_cmd)
app.command(name="import")(export_import.import_cmd)


@app.callback()
def callback(
    version: bool = typer.Option(
        False, "--version", "-v", help="Show version and exit."
    ),
):
    """[header]Matriosha[/header] — [accent]Secure Agentic Memory Layer[/accent]"""
    if version:
        from cli import __version__
        console.print(f"[header]Matriosha[/header] v{__version__}", style="success")
        raise typer.Exit()


if __name__ == "__main__":
    app()
