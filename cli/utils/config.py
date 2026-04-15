"""
Matriosha CLI Utils — Config File Loader

Loads configuration from ~/.matriosha/config.toml
Provides defaults for vault path, mode, and credentials.
"""

import os
import tomllib
from pathlib import Path
from typing import Dict, Any

DEFAULT_CONFIG_PATH = Path.home() / ".matriosha" / "config.toml"

DEFAULT_CONFIG: Dict[str, Any] = {
    "vault": {
        "path": str(Path.home() / ".matriosha" / "vault"),
        "mode": "local",  # local | managed | hybrid
    },
    "auth": {
        "type": "keyring",  # keyring | api_key
        "api_key": None,
    },
    "supabase": {
        "url": None,
        "anon_key": None,
    },
    "cli": {
        "output_format": "human",  # human | json
        "verbose": False,
    },
}


def load_config(config_path: Path = DEFAULT_CONFIG_PATH) -> Dict[str, Any]:
    """
    Load configuration from TOML file with defaults.

    Args:
        config_path: Path to config.toml file.

    Returns:
        Merged configuration dictionary (defaults + file overrides).
    """
    config = DEFAULT_CONFIG.copy()

    if config_path.exists():
        try:
            with open(config_path, "rb") as f:
                file_config = tomllib.load(f)
            # Deep merge (simple top-level override)
            for section, values in file_config.items():
                if section in config and isinstance(config[section], dict):
                    config[section].update(values)
                else:
                    config[section] = values
        except Exception as e:
            print(f"Warning: Could not load config from {config_path}: {e}")

    # Override with environment variables if set
    if os.getenv("MATRIOSHA_VAULT_PATH"):
        config["vault"]["path"] = os.getenv("MATRIOSHA_VAULT_PATH")
    if os.getenv("MATRIOSHA_MODE"):
        config["vault"]["mode"] = os.getenv("MATRIOSHA_MODE")
    if os.getenv("MATRIOSHA_API_KEY"):
        config["auth"]["api_key"] = os.getenv("MATRIOSHA_API_KEY")

    return config


def save_config(config: Dict[str, Any], config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """
    Save configuration to TOML file.

    Args:
        config: Configuration dictionary to save.
        config_path: Path to config.toml file.
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)

    import tomli_w

    with open(config_path, "w") as f:
        tomli_w.dump(config, f)


def get_vault_path(config: Dict[str, Any]) -> Path:
    """Get vault path from config, ensuring it exists."""
    path = Path(config["vault"]["path"])
    path.mkdir(parents=True, exist_ok=True)
    return path
