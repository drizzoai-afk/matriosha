"""Shared filesystem path resolution for Matriosha."""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs


def data_dir() -> Path:
    """Return the Matriosha data root.

    Resolution order:
    1. MATRIOSHA_DATA_DIR
    2. MATRIOSHA_HOME/data
    3. platform default data directory
    """

    override = os.environ.get("MATRIOSHA_DATA_DIR")
    if override:
        return Path(override).expanduser()

    home = os.environ.get("MATRIOSHA_HOME")
    if home:
        return Path(home).expanduser() / "data"

    return Path(platformdirs.user_data_dir("matriosha"))


def config_dir() -> Path:
    """Return the Matriosha config root.

    Resolution order:
    1. MATRIOSHA_CONFIG_DIR
    2. MATRIOSHA_HOME/config
    3. platform default config directory
    """

    override = os.environ.get("MATRIOSHA_CONFIG_DIR")
    if override:
        return Path(override).expanduser()

    home = os.environ.get("MATRIOSHA_HOME")
    if home:
        return Path(home).expanduser() / "config"

    return Path(platformdirs.user_config_dir("matriosha"))
