"""
Matriosha CLI Utils — Config File Loader

Loads configuration from ~/.matriosha/config.toml
Provides defaults for vault path, mode, and credentials.
"""

import os
from pathlib import Path
from typing import Dict, Any

try:
    import tomllib
except ImportError:
    import importlib

    tomllib = importlib.import_module("tomli")  # Python <3.11 fallback

from matriosha.core.secrets import get_secret

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

    # Override with environment variables or GCP Secret Manager
    if os.getenv("MATRIOSHA_VAULT_PATH"):
        config["vault"]["path"] = os.getenv("MATRIOSHA_VAULT_PATH")
    if os.getenv("MATRIOSHA_MODE"):
        config["vault"]["mode"] = os.getenv("MATRIOSHA_MODE")
    if os.getenv("MATRIOSHA_API_KEY"):
        config["auth"]["api_key"] = os.getenv("MATRIOSHA_API_KEY")

    # Auto-inject Supabase secrets if not set in config
    if not config["supabase"]["url"]:
        config["supabase"]["url"] = get_secret("SUPABASE_URL")
    if not config["supabase"]["anon_key"]:
        config["supabase"]["anon_key"] = get_secret("SUPABASE_ANON_KEY")

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

    # Filter out None values before saving to TOML
    def filter_none(d):
        if isinstance(d, dict):
            return {k: filter_none(v) for k, v in d.items() if v is not None}
        return d

    with open(config_path, "wb") as f:
        tomli_w.dump(filter_none(config), f)


def get_vault_path(config: Dict[str, Any]) -> Path:
    """Get vault path from config, ensuring it exists."""
    path = Path(config["vault"]["path"])
    path.mkdir(parents=True, exist_ok=True)
    return path
