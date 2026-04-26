"""Vault command group with Phase 2.5 vault init implementation."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import platformdirs
import typer

from matriosha.cli.brand.theme import console as make_console
from matriosha.cli.utils.errors import EXIT_USAGE
from matriosha.core.config import Profile, get_active_profile, load_config, save_config

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


def _resolve_passphrase(
    *,
    provided: str | None,
    json_output: bool,
    with_source: bool = False,
) -> str | tuple[str, str]:
    if provided is not None:
        result = (provided, "typed option")
        return result if with_source else result[0]

    env_passphrase = os.getenv("MATRIOSHA_PASSPHRASE")
    if env_passphrase:
        result = (env_passphrase, "environment variable")
        return result if with_source else result[0]

    if json_output:
        raise typer.Exit(code=EXIT_USAGE)

    result = (
        typer.prompt("Vault passphrase", hide_input=True, confirmation_prompt=True),
        "interactive prompt",
    )
    return result if with_source else result[0]


def _render_card(title: str, rows: list[tuple[str, str]], *, status_chip: str, style: str) -> None:
    console = make_console()
    width = 88
    inner = width - 2
    header = f" {status_chip} {title} "
    header_pad = max(0, inner - len(header))
    console.print(f"[{style}]╭{'─' * ((header_pad // 2))}{header}{'─' * (header_pad - (header_pad // 2))}╮[/{style}]")
    label_width = max(10, *(len(key) for key, _ in rows))
    for key, value in rows:
        line = f" {key:<{label_width}}  {value} "
        console.print(f"[{style}]│{line:<{inner}}│[/{style}]")
    console.print(f"[{style}]╰{'─' * inner}╯[/{style}]")


def _emit_refusal(message: str, *, json_output: bool, code: int) -> None:
    is_managed_mode_refusal = "local-mode only" in message

    if is_managed_mode_refusal:
        title = "VAULT INIT IS LOCAL-ONLY"
        status_chip = "✖ MODE"
        next_step = "run `matriosha auth login`; managed key custody is automatic"
        stable_code = "VAL-VAULT-INIT-MANAGED"
        debug = "vault init refused because active mode is managed"
    else:
        title = "VAULT INIT REFUSED"
        status_chip = "⚠ EXISTS"
        next_step = "use --force only if you intentionally want to overwrite existing local vault files"
        stable_code = "VAL-VAULT-INIT-REFUSED"
        debug = "vault init refused"

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "status": "error",
                    "title": message,
                    "category": "VAL",
                    "code": stable_code,
                    "exit": code,
                    "fix": next_step,
                    "debug": debug,
                },
                sort_keys=True,
            )
        )
    else:
        _render_card(
            title,
            [("reason", message), ("next", next_step)],
            status_chip=status_chip,
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


