"""Shared helpers for mode commands."""

from __future__ import annotations

from datetime import datetime, timezone

from matriosha.core.config import Profile, get_active_profile, validate_profile_name


def resolve_target_profile(
    cfg: object,
    override: str | None,
    *,
    create_if_missing: bool,
) -> Profile:
    if override:
        override = validate_profile_name(override)

    if override and override not in cfg.profiles and create_if_missing:
        cfg.profiles[override] = Profile(
            name=override,
            mode="local",
            created_at=datetime.now(timezone.utc),
        )

    profile = get_active_profile(cfg, override)
    if override:
        cfg.active_profile = override
    return profile
