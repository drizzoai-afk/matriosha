"""
Matriosha CLI — Init Command

Initializes a new Matriosha vault with encryption key generation.
Creates directory structure and stores key in OS keyring.
"""

import typer
from pathlib import Path
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.security import generate_salt, derive_key, store_key_vault
from cli.utils.config import save_config, DEFAULT_CONFIG


def init_cmd(
    path: Optional[str] = typer.Option(
        None, "--path", "-p", help="Path to vault directory (default: ~/.matriosha/vault)"
    ),
    password: Optional[str] = typer.Option(
        None, "--password", help="Vault password (prompted if not provided)"
    ),
):
    """
    Initialize a new Matriosha vault.

    Generates a unique salt and derives an encryption key from the user's password.
    The key is stored securely in the OS keyring (never on disk).

    Examples:
        matriosha init
        matriosha init --path ./my-vault
        matriosha init --password "secure-password"
    """
    import getpass

    # Determine vault path
    if path:
        vault_path = Path(path).resolve()
    else:
        vault_path = Path.home() / ".matriosha" / "vault"

    # Create vault directory
    vault_path.mkdir(parents=True, exist_ok=True)
    typer.echo(f"✓ Vault directory created: {vault_path}")

    # Get password
    if not password:
        password = getpass.getpass("Enter vault password: ")
        password_confirm = getpass.getpass("Confirm password: ")
        if password != password_confirm:
            typer.echo("✗ Passwords do not match.", err=True)
            raise typer.Exit(code=1)

    if len(password) < 8:
        typer.echo("✗ Password must be at least 8 characters.", err=True)
        raise typer.Exit(code=1)

    # Generate salt and derive key
    salt = generate_salt()
    key = derive_key(password, salt)

    # Store salt in vault (plaintext, needed for key derivation)
    salt_file = vault_path / "salt.bin"
    salt_file.write_bytes(salt)
    typer.echo("✓ Salt generated and stored.")

    # Store key in OS keyring
    vault_id = vault_path.stem
    store_key_vault(vault_id, key)
    typer.echo("✓ Encryption key stored in OS keyring.")

    # Save config file
    config = DEFAULT_CONFIG.copy()
    config["vault"]["path"] = str(vault_path)
    config_path = Path.home() / ".matriosha" / "config.toml"
    save_config(config, config_path)
    typer.echo(f"✓ Config saved: {config_path}")

    typer.echo(f"\n🎉 Vault initialized successfully at {vault_path}")
    typer.echo("\nNext steps:")
    typer.echo("  matriosha remember \"Your first memory\"")
    typer.echo("  matriosha recall \"search query\"")
