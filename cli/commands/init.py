"""
Matriosha CLI — Init Command

Initializes a new Matriosha vault with encryption key generation.
Creates directory structure and stores key in OS keyring.
"""

import typer
from typing import Optional
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rich.panel import Panel  # noqa: E402
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn  # noqa: E402
from rich.table import Table  # noqa: E402

from cli.brand.banner import print_banner  # noqa: E402
from cli.brand.theme import console as make_console  # noqa: E402
from core.security import generate_salt, derive_key, store_key_vault  # noqa: E402
from cli.utils.config import save_config, DEFAULT_CONFIG  # noqa: E402

def _get_console():
    return make_console()


def init_cmd(
    path: Optional[str] = typer.Option(
        None, "--path", "-p", help="Path to vault directory (default: ~/.matriosha/vault)"
    ),
    password: Optional[str] = typer.Option(
        None, "--password", help="Vault password (prompted if not provided)"
    ),
    local: bool = typer.Option(
        True, "--local/--cloud", help="Initialize as local-only vault"
    ),
):
    """
    [primary]Initialize[/primary] a new Matriosha vault.

    Generates a unique salt and derives an encryption key from your password.
    The key is stored securely in the OS keyring (never on disk).

    [accent]Examples:[/accent]
        matriosha init
        matriosha init --path ./my-vault
        matriosha init --password "secure-password"
    """
    import getpass

    # Header banner
    print_banner(_get_console())
    _get_console().print("\n[primary]╔══════════════════════════════════════╗[/primary]")
    _get_console().print("[primary]║   Matriosha Vault Initialization     ║[/primary]")
    _get_console().print("[primary]╚══════════════════════════════════════╝[/primary]\n")

    # Determine vault path
    if path:
        vault_path = Path(path).resolve()
    else:
        vault_path = Path.home() / ".matriosha" / "vault"

    # Create vault directory with progress
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        transient=True,
    ) as progress:
        task = progress.add_task("Creating vault directory...", total=None)
        vault_path.mkdir(parents=True, exist_ok=True)
        progress.update(task, completed=100)

    _get_console().print("✓ Vault directory created", style="success")
    _get_console().print(f"  Path: [accent]{vault_path}[/accent]\n")

    # Get password
    if not password:
        password = getpass.getpass("Enter vault password: ")
        password_confirm = getpass.getpass("Confirm password: ")
        if password != password_confirm:
            _get_console().print("✗ Passwords do not match.", style="danger")
            # Zero out passwords from memory
            password = ""
            password_confirm = ""
            raise typer.Exit(code=1)

    if len(password) < 8:
        _get_console().print("✗ Password must be at least 8 characters.", style="danger")
        password = ""
        raise typer.Exit(code=1)

    # Generate salt and derive key with progress
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task = progress.add_task("Generating cryptographic keys...", total=None)
        salt = generate_salt()
        key = derive_key(password, salt)
        progress.update(task, completed=100)

    _get_console().print("✓ Cryptographic keys generated", style="success")

    # Store salt in vault (plaintext, needed for key derivation)
    salt_file = vault_path / "salt.bin"
    salt_file.write_bytes(salt)
    _get_console().print("✓ Salt generated and stored", style="success")

    # Store key in OS keyring
    vault_id = vault_path.stem
    store_key_vault(vault_id, key)
    _get_console().print("✓ Encryption key stored in OS keyring", style="success")

    # Save config file
    config = DEFAULT_CONFIG.copy()
    config["vault"]["path"] = str(vault_path)
    config["vault"]["mode"] = "local" if local else "cloud"
    config_path = Path.home() / ".matriosha" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    save_config(config, config_path)
    _get_console().print(f"✓ Config saved: [accent]{config_path}[/accent]", style="success")

    # Success panel
    success_table = Table.grid(padding=1)
    success_table.add_column(style="success", justify="right")
    success_table.add_column(style="white")

    success_table.add_row("Vault Location:", str(vault_path))
    success_table.add_row("Config File:", str(config_path))
    success_table.add_row("Key Storage:", "OS Keyring (secure)")

    _get_console().print("\n")
    _get_console().print(Panel(
        success_table,
        title="[success]🎉 Vault Initialized Successfully[/success]",
        border_style="success",
    ))

    # Next steps
    _get_console().print("\n[primary]Next Steps:[/primary]")
    _get_console().print("  [accent]matriosha remember[/accent] \"Your first memory\"")
    _get_console().print("  [accent]matriosha recall[/accent] \"search query\"\n")
