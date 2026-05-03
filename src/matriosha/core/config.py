"""Persistent profile configuration for Matriosha CLI."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import platformdirs  # noqa: F401
from matriosha.core.paths import config_dir
from pydantic import BaseModel, Field

try:
    import tomllib
except ImportError:  # pragma: no cover - Python <3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

_PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
DEFAULT_MANAGED_ENDPOINT = "https://matriosha-api-982521900123.europe-west3.run.app"


def validate_profile_name(profile_name: str) -> str:
    """Validate profile names before config lookup or mutation."""

    if not _PROFILE_NAME_RE.fullmatch(profile_name):
        raise ValueError("Profile name must be 1-64 characters and contain only letters, numbers, '_' or '-'")
    return profile_name


class Profile(BaseModel):
    name: str
    mode: Literal["local", "managed"] = "local"
    managed_endpoint: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ManagedSettings(BaseModel):
    auto_sync: bool = True


class MatrioshaConfig(BaseModel):
    profiles: dict[str, Profile] = Field(default_factory=dict)
    active_profile: str = "default"
    managed: ManagedSettings = Field(default_factory=ManagedSettings)


def _config_dir() -> Path:
    return config_dir()


def _config_path() -> Path:
    return _config_dir() / "config.toml"


def _default_config() -> MatrioshaConfig:
    default_profile = Profile(name="default", mode="local")
    return MatrioshaConfig(profiles={"default": default_profile}, active_profile="default")


def _serialize_config(cfg: MatrioshaConfig) -> str:
    lines: list[str] = [f'active_profile = "{cfg.active_profile}"', ""]
    lines.append("[managed]")
    lines.append(f"auto_sync = {str(cfg.managed.auto_sync).lower()}")
    lines.append("")

    for profile_name, profile in cfg.profiles.items():
        validate_profile_name(profile_name)
        validate_profile_name(profile.name)
        lines.append(f'[profiles."{profile_name}"]')
        lines.append(f'name = "{profile.name}"')
        lines.append(f'mode = "{profile.mode}"')
        if profile.managed_endpoint is not None:
            lines.append(f'managed_endpoint = "{profile.managed_endpoint}"')
        lines.append(f'created_at = "{profile.created_at.isoformat()}"')
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def load_config() -> MatrioshaConfig:
    """Load persistent config from disk, creating defaults on first run."""

    cfg_path = _config_path()
    if not cfg_path.exists():
        cfg = _default_config()
        save_config(cfg)
        return cfg

    try:
        raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        cfg = MatrioshaConfig.model_validate(raw)
    except Exception:
        logger.warning("Config file unreadable; re-creating default configuration.")
        cfg = _default_config()
        save_config(cfg)
        return cfg

    if "default" not in cfg.profiles:
        cfg.profiles["default"] = Profile(name="default", mode="local")

    if cfg.active_profile not in cfg.profiles:
        cfg.active_profile = "default"

    if cfg.managed is None:
        cfg.managed = ManagedSettings()

    return cfg


def save_config(cfg: MatrioshaConfig):
    """Persist config to disk with owner-only permissions (0600)."""

    cfg_path = _config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(_serialize_config(cfg), encoding="utf-8")

    if os.name != "nt":
        os.chmod(cfg_path, 0o600)


def get_active_profile(cfg: MatrioshaConfig, profile_name_override: str | None) -> Profile:
    profile_name = validate_profile_name(profile_name_override or cfg.active_profile)
    profile = cfg.profiles.get(profile_name)
    if profile is None:
        raise ValueError(f"Profile '{profile_name}' not found")
    return profile
