"""Vault command group with Phase 2.5 vault init implementation."""

from __future__ import annotations

import base64
import binascii
import json
import os
import time
from pathlib import Path

import platformdirs
import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from cli.utils.context import get_global_context
from cli.utils.errors import EXIT_AUTH, EXIT_INTEGRITY, EXIT_OK, EXIT_USAGE
from core.binary_protocol import decode_envelope, merkle_root
from core.config import Profile, get_active_profile, load_config, save_config
from core.crypto import IntegrityError
from core.storage_local import LocalStore
from core.vault import AuthError, Vault, VaultAlreadyInitializedError, VaultIntegrityError

app = typer.Typer(help="Vault key lifecycle and integrity commands.", no_args_is_help=True)

_BANNER = """            1010101010101
         1010┌─────────┐0101
       1010  │101010101│ 0101
      1010 ┌─┴─────────┴─┐ 0101
     1010  │ 01010101010 │ 0101
     1010  │ ┌─────────┐ │ 0101
     1010  │ │101010101│ │ 0101
     1010  │ └─────────┘ │ 0101
      1010 └─────────────┘ 0101
       1010    1010101    0101
          10101010101010101
              MATRIOSHA"""


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
    console = Console()
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
            style="yellow",
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
        style="red",
    )


@app.command("init")
def init(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="Overwrite existing local vault files."),
    passphrase: str | None = typer.Option(None, "--passphrase", help="Vault passphrase."),
    json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Initialize local-mode vault key material for the selected profile."""

    gctx = get_global_context(ctx)
    effective_json = gctx.json_output or json_output_flag
    profile = _resolve_target_profile(gctx.profile)

    if profile.mode == "managed":
        _emit_refusal("vault init is local-mode only", json_output=effective_json, code=EXIT_USAGE)

    limiter = _RateLimiter()
    limiter.apply_backoff_if_needed()

    resolved_passphrase = _resolve_passphrase(provided=passphrase, json_output=effective_json)

    try:
        key_file, salt_file = Vault._paths(profile.name)
        if key_file.exists() and not force:
            limiter.record_failure()
            _emit_refusal(
                f"vault already exists for profile '{profile.name}'",
                json_output=effective_json,
                code=EXIT_USAGE,
            )

        if force and (key_file.exists() or salt_file.exists()):
            Vault.validate_material(profile.name)

        vault = Vault.init(profile.name, resolved_passphrase, force=force)
        limiter.clear()

        if effective_json:
            typer.echo(
                json.dumps(
                    {
                        "status": "ok",
                        "profile": profile.name,
                        "salt_file": str(vault.salt_file),
                        "key_file": str(vault.key_file),
                    }
                )
            )
            raise typer.Exit(code=EXIT_OK)

        if not gctx.plain:
            typer.echo(_BANNER)
            typer.echo()
            _render_card(
                "VAULT INITIALIZED",
                [
                    ("profile", profile.name),
                    ("key file", str(vault.key_file)),
                    ("salt file", str(vault.salt_file)),
                    ("next", "matriosha memory remember \"hello\" --tag test"),
                ],
                status_chip="✓ INITIALIZED",
                style="green",
            )
        else:
            typer.echo(f"vault initialized for profile '{profile.name}'")
            typer.echo(f"key file: {vault.key_file}")
            typer.echo(f"salt file: {vault.salt_file}")

        raise typer.Exit(code=EXIT_OK)

    except VaultIntegrityError as exc:
        limiter.record_failure()
        if effective_json:
            typer.echo(json.dumps({"status": "error", "error": str(exc)}))
        else:
            _render_card(
                "VAULT INTEGRITY ERROR",
                [("reason", str(exc)), ("exit", str(EXIT_INTEGRITY))],
                status_chip="✖ INTEGRITY",
                style="red",
            )
        raise typer.Exit(code=EXIT_INTEGRITY)
    except AuthError as exc:
        limiter.record_failure()
        if effective_json:
            typer.echo(json.dumps({"status": "error", "error": str(exc)}))
        else:
            _render_card(
                "VAULT AUTH ERROR",
                [("reason", str(exc)), ("exit", str(EXIT_AUTH))],
                status_chip="✖ AUTH",
                style="red",
            )
        raise typer.Exit(code=EXIT_AUTH)
    except VaultAlreadyInitializedError as exc:
        limiter.record_failure()
        _emit_refusal(str(exc), json_output=effective_json, code=EXIT_USAGE)


@app.command("verify")
def verify(
    ctx: typer.Context,
    deep: bool = typer.Option(False, "--deep", help="Decrypt each memory and verify Merkle integrity end-to-end."),
    json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Verify all memories in local vault storage."""

    gctx = get_global_context(ctx)
    json_output = gctx.json_output or json_output_flag
    console = Console()

    try:
        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)
        store = LocalStore(profile.name)
        envelopes = store.list(limit=1_000_000)

        vault = None
        if deep:
            vault = Vault.unlock(profile.name, _resolve_passphrase(provided=None, json_output=False))

        total = len(envelopes)
        ok = 0
        failed: list[dict[str, str]] = []

        progress = None
        task_id = None
        if not json_output and not gctx.plain:
            progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                console=console,
            )
            progress.start()
            task_id = progress.add_task("vault verify", total=total if total > 0 else 1)

        for env in envelopes:
            reason = ""
            try:
                env_obj, payload_b64 = store.get(env.memory_id)

                if deep:
                    assert vault is not None
                    decode_envelope(env_obj, payload_b64, vault.data_key)
                else:
                    try:
                        encrypted_blob = base64.b64decode(payload_b64, validate=True)
                    except binascii.Error as exc:
                        raise IntegrityError("payload is not valid base64") from exc

                    if len(encrypted_blob) < 12:
                        raise IntegrityError("payload too short")

                    if merkle_root(env_obj.merkle_leaves) != env_obj.merkle_root:
                        raise IntegrityError("merkle root mismatch")

                    for leaf in env_obj.merkle_leaves:
                        if len(leaf) != 64:
                            raise IntegrityError("invalid merkle leaf length")
                        int(leaf, 16)

                ok += 1
            except (IntegrityError, ValueError) as exc:
                reason = str(exc)
            except Exception as exc:  # noqa: BLE001
                reason = f"{type(exc).__name__}: {exc}"

            if reason:
                failed.append({"id": env.memory_id, "reason": reason})

            if progress is not None and task_id is not None:
                progress.update(task_id, advance=1)

        if progress is not None:
            progress.stop()

        summary = {"total": total, "ok": ok, "failed": failed}
        has_failures = len(failed) > 0

        if json_output:
            typer.echo(json.dumps(summary))
            raise typer.Exit(code=EXIT_INTEGRITY if has_failures else EXIT_OK)

        if gctx.plain:
            typer.echo(f"total: {total}")
            typer.echo(f"ok: {ok}")
            typer.echo(f"failed: {len(failed)}")
            for item in failed:
                typer.echo(f"- {item['id']}: {item['reason']}")
        else:
            summary_table = Table(title="Vault Verify Summary", show_header=True, header_style="bold cyan")
            summary_table.add_column("metric")
            summary_table.add_column("value", justify="right")
            summary_table.add_row("total", str(total))
            summary_table.add_row("ok", str(ok))
            summary_table.add_row("failed", str(len(failed)))
            console.print(summary_table)

            if failed:
                failed_table = Table(title="Verification Failures", show_header=True, header_style="bold red")
                failed_table.add_column("id")
                failed_table.add_column("reason")
                for item in failed:
                    failed_table.add_row(item["id"], item["reason"])
                console.print(failed_table)

        raise typer.Exit(code=EXIT_INTEGRITY if has_failures else EXIT_OK)

    except AuthError:
        _emit_error(
            title="Vault unlock failed",
            category="AUTH",
            stable_code="AUTH-002",
            exit_code=EXIT_AUTH,
            fix="set MATRIOSHA_PASSPHRASE correctly or retry with the right passphrase",
            debug="provider=local_vault profile_auth_failed",
            json_output=json_output,
            plain=gctx.plain,
        )
        raise typer.Exit(code=EXIT_AUTH)
    except (OSError, VaultIntegrityError, ValueError) as exc:
        _emit_error(
            title="Vault verify storage failure",
            category="STORE",
            stable_code="STORE-010",
            exit_code=EXIT_USAGE,
            fix="check local vault files and run `matriosha doctor`",
            debug=f"os_error={type(exc).__name__}",
            json_output=json_output,
            plain=gctx.plain,
        )
        raise typer.Exit(code=EXIT_USAGE)


@app.command("rotate")
def rotate() -> None:
    raise NotImplementedError("not implemented in phase 2.5")


@app.command("export")
def export() -> None:
    raise NotImplementedError("not implemented in phase 2.5")


@app.command("sync")
def sync() -> None:
    raise NotImplementedError("not implemented in phase 2.5")
