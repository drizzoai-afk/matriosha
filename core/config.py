"""Persistent profile configuration for Matriosha CLI."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import platformdirs
from pydantic import BaseModel, Field

try:
    import tomllib
except ImportError:  # pragma: no cover - Python <3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


class Profile(BaseModel):
    name: str
    mode: Literal["local", "managed"] = "local"
    managed_endpoint: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MatrioshaConfig(BaseModel):
    profiles: dict[str, Profile] = Field(default_factory=dict)
    active_profile: str = "default"


def _config_dir() -> Path:
    return Path(platformdirs.user_config_dir("matriosha"))


def _config_path() -> Path:
    return _config_dir() / "config.toml"


def _default_config() -> MatrioshaConfig:
    default_profile = Profile(name="default", mode="local")
    return MatrioshaConfig(profiles={"default": default_profile}, active_profile="default")


def _serialize_config(cfg: MatrioshaConfig) -> str:
    lines: list[str] = [f'active_profile = "{cfg.active_profile}"', ""]
    for profile_name, profile in cfg.profiles.items():
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

    return cfg


def save_config(cfg: MatrioshaConfig):
    """Persist config to disk with owner-only permissions (0600)."""

    cfg_path = _config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(_serialize_config(cfg), encoding="utf-8")

    if os.name != "nt":
        os.chmod(cfg_path, 0o600)


def get_active_profile(cfg: MatrioshaConfig, profile_name_override: str | None) -> Profile:
    profile_name = profile_name_override or cfg.active_profile
    profile = cfg.profiles.get(profile_name)
    if profile is None:
        raise ValueError(f"Profile '{profile_name}' not found")
    return profile
