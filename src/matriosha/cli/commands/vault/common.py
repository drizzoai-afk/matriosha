"""Vault command group with Phase 2.5 vault init implementation."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import io
import json
import logging
import os
import shutil
import signal
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

import platformdirs
import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from matriosha.cli.brand.banner import print_banner
from matriosha.cli.brand.theme import console as make_console
from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_AUTH, EXIT_INTEGRITY, EXIT_MODE, EXIT_OK, EXIT_USAGE
from matriosha.cli.utils.mode_guard import require_mode
from matriosha.core.binary_protocol import decode_envelope, envelope_to_json, merkle_root
from matriosha.core.config import Profile, get_active_profile, load_config, save_config
from matriosha.core.crypto import IntegrityError, derive_key, encrypt, generate_salt
from matriosha.core.managed.auth import ensure_process_managed_passphrase, resolve_access_token
from matriosha.core.managed.client import ManagedClient
from matriosha.core.managed.key_custody import double_wrap, upload_wrapped_key
from matriosha.core.managed.sync import SyncEngine, SyncReport
from matriosha.core.secrets import get_secret
from matriosha.core.storage_local import LocalStore
from matriosha.core.vault import (
    AuthError,
    DATA_KEY_LEN,
    MAGIC,
    Vault,
    VaultAlreadyInitializedError,
    VaultIntegrityError,
)
from matriosha.core.vectors import get_default_embedder

logger = logging.getLogger(__name__)

class _RateLimiter:
    """Simple failed-attempt limiter for vault init in config-dir state file."""

    WINDOW_SECONDS = 60

    def __init__(self) -> None:
        self.path = Path(platformdirs.user_config_dir("matriosha")) / "vault_init_attempts.json"

    def apply_backoff_if_needed(self) -> None:
        recent = self._recent_failures()
        if recent < 5:
            return
        delay = min(32, 2 ** (recent - 5))
        time.sleep(delay)

    def record_failure(self) -> None:
        now = time.time()
        data = self._load()
        failures = [t for t in data.get("failed_init_timestamps", []) if now - t <= self.WINDOW_SECONDS]
        failures.append(now)
        self._save({"failed_init_timestamps": failures})

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink(missing_ok=True)

    def _recent_failures(self) -> int:
        now = time.time()
        data = self._load()
        failures = [t for t in data.get("failed_init_timestamps", []) if now - t <= self.WINDOW_SECONDS]
        self._save({"failed_init_timestamps": failures})
        return len(failures)

    def _load(self) -> dict[str, list[float]]:
        if not self.path.exists():
            return {"failed_init_timestamps": []}
        try:
            payload = self.path.read_text(encoding="utf-8")
            data = json.loads(payload)
            failures = data.get("failed_init_timestamps", [])
            if not isinstance(failures, list):
                return {"failed_init_timestamps": []}
            normalized = [float(v) for v in failures]
            return {"failed_init_timestamps": normalized}
        except Exception:
            return {"failed_init_timestamps": []}

    def _save(self, data: dict[str, list[float]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        if os.name != "nt":
            os.chmod(self.path, 0o600)


def _resolve_target_profile(profile_override: str | None) -> Profile:
    cfg = load_config()
    if profile_override and profile_override not in cfg.profiles:
        cfg.profiles[profile_override] = Profile(name=profile_override, mode="local")
        cfg.active_profile = profile_override
        save_config(cfg)
    return get_active_profile(cfg, profile_override)


def _resolve_passphrase(*, provided: str | None, json_output: bool) -> str:
    env_passphrase = os.getenv("MATRIOSHA_PASSPHRASE")
    if env_passphrase:
        return env_passphrase
    if provided is not None:
        return provided
    if json_output:
        raise typer.Exit(code=EXIT_USAGE)
    return typer.prompt("Vault passphrase", hide_input=True, confirmation_prompt=True)


def _render_card(title: str, rows: list[tuple[str, str]], *, status_chip: str, style: str) -> None:
    console = make_console()
    width = 88
    inner = width - 2
    header = f" {status_chip} {title} "
    header_pad = max(0, inner - len(header))
    console.print(f"[{style}]╭{'─' * ((header_pad // 2))}{header}{'─' * (header_pad - (header_pad // 2))}╮[/{style}]")
    for key, value in rows:
        line = f" {key:<10} {value} "
        console.print(f"[{style}]│{line:<{inner}}│[/{style}]")
    console.print(f"[{style}]╰{'─' * inner}╯[/{style}]")


def _emit_refusal(message: str, *, json_output: bool, code: int) -> None:
    if json_output:
        typer.echo(json.dumps({"status": "error", "error": message}))
    else:
        _render_card(
            "VAULT INIT REFUSED",
            [("reason", message), ("next", "use --force to overwrite existing vault files")],
            status_chip="⚠ EXISTS",
            style="warning",
        )
    raise typer.Exit(code=code)


def _emit_error(
    *,
    title: str,
    category: str,
    stable_code: str,
    exit_code: int,
    fix: str,
    debug: str,
    json_output: bool,
    plain: bool,
) -> None:
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "status": "error",
                    "title": title,
                    "category": category,
                    "code": stable_code,
                    "exit": exit_code,
                    "fix": fix,
                    "debug": debug,
                }
            )
        )
        return

    if plain:
        typer.echo(title)
        typer.echo(f"category: {category}  code: {stable_code}  exit: {exit_code}")
        typer.echo(f"fix: {fix}")
        typer.echo(f"debug: {debug}")
        return

    _render_card(
        title,
        [
            ("category", f"{category}  code: {stable_code}  exit: {exit_code}"),
            ("fix", fix),
            ("debug", debug),
        ],
        status_chip="✖ ERROR",
        style="danger",
    )


