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

from cli.brand.banner import print_banner
from cli.brand.theme import console as make_console
from cli.utils.context import get_global_context
from cli.utils.errors import EXIT_AUTH, EXIT_INTEGRITY, EXIT_MODE, EXIT_OK, EXIT_USAGE
from cli.utils.mode_guard import require_mode
from core.binary_protocol import decode_envelope, envelope_to_json, merkle_root
from core.config import Profile, get_active_profile, load_config, save_config
from core.crypto import IntegrityError, derive_key, encrypt, generate_salt
from core.managed.client import ManagedClient
from core.managed.key_custody import double_wrap, upload_wrapped_key
from core.managed.sync import SyncEngine, SyncReport
from core.secrets import get_secret
from core.storage_local import LocalStore
from core.vault import (
    AuthError,
    DATA_KEY_LEN,
    MAGIC,
    Vault,
    VaultAlreadyInitializedError,
    VaultIntegrityError,
)
from core.vectors import get_default_embedder

app = typer.Typer(help="Vault key lifecycle and integrity commands.", no_args_is_help=True)
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
            branded_console = make_console()
            print_banner(branded_console)
            branded_console.print()
            _render_card(
                "VAULT INITIALIZED",
                [
                    ("profile", profile.name),
                    ("key file", str(vault.key_file)),
                    ("salt file", str(vault.salt_file)),
                    ("next", "matriosha memory remember \"hello\" --tag test"),
                ],
                status_chip="✓ INITIALIZED",
                style="success",
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
                style="danger",
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
                style="danger",
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
    console = make_console()

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
            summary_table = Table(title="Vault Verify Summary", show_header=True, header_style="bold accent")
            summary_table.add_column("metric")
            summary_table.add_column("value", justify="right")
            summary_table.add_row("total", str(total))
            summary_table.add_row("ok", str(ok))
            summary_table.add_row("failed", str(len(failed)))
            console.print(summary_table)

            if failed:
                failed_table = Table(title="Verification Failures", show_header=True, header_style="bold danger")
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


def _resolve_unlock_passphrase(*, override: str | None = None) -> str:
    if override is not None:
        return override
    env_passphrase = os.getenv("MATRIOSHA_PASSPHRASE")
    if env_passphrase:
        return env_passphrase
    return typer.prompt("Current vault passphrase", hide_input=True)


def _resolve_new_passphrase(*, override: str | None = None) -> str:
    if override is not None:
        return override
    env_passphrase = os.getenv("MATRIOSHA_NEW_PASSPHRASE")
    if env_passphrase:
        return env_passphrase
    return typer.prompt("New vault passphrase", hide_input=True, confirmation_prompt=True)


def _build_wrapped_key_material(data_key: bytes, passphrase: str) -> tuple[bytes, bytes, bytes]:
    salt = generate_salt(16)
    kek = derive_key(passphrase, salt)
    nonce, ciphertext = encrypt(data_key, kek)
    wrapped_blob = MAGIC + nonce + ciphertext
    return salt, kek, wrapped_blob


def _safe_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    if os.name != "nt":
        os.chmod(path, 0o600)


def _rotation_marker_path(root: Path) -> Path:
    return root / "rotate.marker.json"


def _collect_memory_ids(memories_dir: Path) -> list[str]:
    ids: list[str] = []
    for env_file in sorted(memories_dir.glob("*.env.json")):
        memory_id = env_file.name.removesuffix(".env.json")
        payload_file = memories_dir / f"{memory_id}.bin.b64"
        if payload_file.exists():
            ids.append(memory_id)
    return ids


def _reencrypt_memories_with_marker(
    *,
    profile_name: str,
    old_key: bytes,
    new_key: bytes,
    crash_after: int | None,
) -> tuple[int, bool]:
    store = LocalStore(profile_name)
    root = store.root
    memories_dir = root / "memories"
    tmp_dir = root / "memories.rotate.tmp"
    marker_path = _rotation_marker_path(root)

    resumed = marker_path.exists()
    if resumed:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    else:
        memory_ids = _collect_memory_ids(memories_dir)
        marker = {
            "version": 1,
            "status": "in_progress",
            "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "memory_ids": memory_ids,
            "completed": [],
            "active_dir": str(memories_dir),
            "tmp_dir": str(tmp_dir),
        }
        _safe_write_json(marker_path, marker)

    tmp_dir.mkdir(parents=True, exist_ok=True)

    memory_ids = [str(mid) for mid in marker.get("memory_ids", [])]
    completed = {str(mid) for mid in marker.get("completed", [])}
    processed_this_run = 0

    for memory_id in memory_ids:
        if memory_id in completed:
            continue

        env, b64_payload = store.get(memory_id)
        plaintext = decode_envelope(env, b64_payload, old_key)
        nonce, ciphertext = encrypt(plaintext, new_key)
        reencrypted_b64 = base64.b64encode(nonce + ciphertext)

        env_src = memories_dir / f"{memory_id}.env.json"
        env_dst = tmp_dir / env_src.name
        payload_dst = tmp_dir / f"{memory_id}.bin.b64"

        shutil.copy2(env_src, env_dst)
        payload_dst.write_bytes(reencrypted_b64)
        if os.name != "nt":
            os.chmod(payload_dst, 0o600)

        completed.add(memory_id)
        marker["completed"] = sorted(completed)
        marker["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _safe_write_json(marker_path, marker)

        processed_this_run += 1
        if crash_after is not None and processed_this_run >= crash_after:
            raise RuntimeError("simulated rotate crash")

    backup_dir = root / "memories.rotate.backup"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)

    os.replace(memories_dir, backup_dir)
    os.replace(tmp_dir, memories_dir)
    shutil.rmtree(backup_dir)

    marker_payload = json.loads(marker_path.read_text(encoding="utf-8"))
    marker_payload["status"] = "completed"
    marker_payload["completed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _safe_write_json(marker_path, marker_payload)
    marker_path.unlink(missing_ok=True)

    return len(memory_ids), resumed


@app.command("rotate")
def rotate(
    ctx: typer.Context,
    new_passphrase: str | None = typer.Option(None, "--new-passphrase", help="New vault passphrase."),
    current_passphrase: str | None = typer.Option(None, "--current-passphrase", help="Current vault passphrase."),
    rotate_data_key: bool = typer.Option(
        False,
        "--rotate-data-key",
        help="Generate a new data key and re-encrypt every local memory payload.",
    ),
    confirm_bulk: bool = typer.Option(
        False,
        "--confirm-bulk",
        help="Required acknowledgement for --rotate-data-key destructive bulk re-encryption.",
    ),
    json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Rotate KEK wrapping, with optional full data-key rotation."""

    gctx = get_global_context(ctx)
    json_output = gctx.json_output or json_output_flag

    cfg = load_config()
    profile = get_active_profile(cfg, gctx.profile)

    old_passphrase = _resolve_unlock_passphrase(override=current_passphrase)
    new_passphrase_resolved = _resolve_new_passphrase(override=new_passphrase)

    if old_passphrase == new_passphrase_resolved and not rotate_data_key:
        message = "new passphrase must differ from current passphrase"
        if json_output:
            typer.echo(json.dumps({"status": "error", "error": message}))
        else:
            typer.echo(message)
        raise typer.Exit(code=EXIT_USAGE)

    if rotate_data_key and not confirm_bulk:
        message = "--rotate-data-key requires --confirm-bulk"
        if json_output:
            typer.echo(json.dumps({"status": "error", "error": message}))
        else:
            typer.echo(message)
        raise typer.Exit(code=EXIT_USAGE)

    try:
        vault = Vault.unlock(profile.name, old_passphrase)
    except AuthError:
        if json_output:
            typer.echo(json.dumps({"status": "error", "error": "vault unlock failed"}))
        else:
            typer.echo("vault unlock failed")
        raise typer.Exit(code=EXIT_AUTH)

    resulting_data_key = vault.data_key
    reencrypted_memories = 0
    resumed = False

    try:
        if rotate_data_key:
            resulting_data_key = os.urandom(DATA_KEY_LEN)
            crash_after_raw = os.getenv("MATRIOSHA_ROTATE_CRASH_AFTER")
            crash_after = int(crash_after_raw) if crash_after_raw else None
            reencrypted_memories, resumed = _reencrypt_memories_with_marker(
                profile_name=profile.name,
                old_key=vault.data_key,
                new_key=resulting_data_key,
                crash_after=crash_after,
            )

        # Memories are encrypted by `data_key`; in KEK-only rotation we must only rewrite
        # vault wrapping material and leave encrypted memory payloads untouched.
        salt, kek, wrapped = _build_wrapped_key_material(resulting_data_key, new_passphrase_resolved)
        Vault._write_secure(vault.salt_file, salt)
        Vault._write_secure(vault.key_file, wrapped)

        managed_uploaded = False
        if profile.mode == "managed":
            server_pubkey = get_secret("MATRIOSHA_VAULT_SERVER_PUBKEY")
            if not server_pubkey:
                raise RuntimeError("MATRIOSHA_VAULT_SERVER_PUBKEY is required for managed key custody upload")

            sealed = double_wrap(resulting_data_key, kek, server_pubkey)

            async def _upload() -> None:
                token = os.getenv("MATRIOSHA_MANAGED_TOKEN")
                if not token:
                    raise RuntimeError("MATRIOSHA_MANAGED_TOKEN is required for managed key custody upload")
                endpoint = profile.managed_endpoint or os.getenv("MATRIOSHA_MANAGED_ENDPOINT")
                async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
                    await upload_wrapped_key(client, salt, sealed)
                    if rotate_data_key:
                        engine = SyncEngine(local=LocalStore(profile.name), remote=client, embedder=get_default_embedder())
                        await engine.sync()

            asyncio.run(_upload())
            managed_uploaded = True

        result = {
            "status": "ok",
            "profile": profile.name,
            "mode": profile.mode,
            "rotate_data_key": rotate_data_key,
            "reencrypted_memories": reencrypted_memories,
            "resumed": resumed,
            "managed_wrapped_key_uploaded": managed_uploaded,
        }

        if json_output:
            typer.echo(json.dumps(result))
        elif gctx.plain:
            typer.echo(f"profile: {profile.name}")
            typer.echo(f"mode: {profile.mode}")
            typer.echo(f"rotate_data_key: {str(rotate_data_key).lower()}")
            typer.echo(f"reencrypted_memories: {reencrypted_memories}")
            typer.echo(f"managed_wrapped_key_uploaded: {str(managed_uploaded).lower()}")
        else:
            _render_card(
                "VAULT ROTATED",
                [
                    ("profile", profile.name),
                    ("mode", profile.mode),
                    ("rotate key", str(rotate_data_key).lower()),
                    ("memories", str(reencrypted_memories)),
                    ("managed", str(managed_uploaded).lower()),
                ],
                status_chip="✓ ROTATED",
                style="success",
            )

        raise typer.Exit(code=EXIT_OK)

    except RuntimeError as exc:
        if isinstance(exc, typer.Exit):
            raise
        if json_output:
            typer.echo(json.dumps({"status": "error", "error": str(exc)}))
        else:
            typer.echo(str(exc))
        raise typer.Exit(code=EXIT_USAGE)


def _emit_sync_report(report: SyncReport, *, json_output: bool, plain: bool, console: Console) -> None:
    payload = report.to_dict()
    payload["status"] = "ok" if not report.errors else "error"

    if json_output:
        typer.echo(json.dumps(payload))
        return

    if plain:
        typer.echo(f"pushed: {report.pushed}")
        typer.echo(f"pulled: {report.pulled}")
        typer.echo(f"warnings: {len(report.warnings)}")
        typer.echo(f"errors: {len(report.errors)}")
        for warning in report.warnings:
            typer.echo(f"warning: {warning}")
        for error in report.errors:
            typer.echo(f"error: {error}")
        return

    table = Table(title="Vault Sync Report", show_header=True, header_style="bold accent")
    table.add_column("metric")
    table.add_column("value", justify="right")
    table.add_row("pushed", str(report.pushed))
    table.add_row("pulled", str(report.pulled))
    table.add_row("warnings", str(len(report.warnings)))
    table.add_row("errors", str(len(report.errors)))
    console.print(table)

    if report.warnings:
        warning_table = Table(title="Sync Warnings", show_header=True, header_style="bold warning")
        warning_table.add_column("warning")
        for warning in report.warnings:
            warning_table.add_row(warning)
        console.print(warning_table)

    if report.errors:
        error_table = Table(title="Sync Errors", show_header=True, header_style="bold danger")
        error_table.add_column("error")
        for error in report.errors:
            error_table.add_row(error)
        console.print(error_table)


def _default_export_path(profile_name: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path.cwd() / f"matriosha-{profile_name}-{stamp}.tar.gz"


def _build_export_archive(profile_name: str, mode: str, output_path: Path) -> dict[str, object]:
    store = LocalStore(profile_name)
    envelopes = sorted(store.list(limit=1_000_000), key=lambda item: item.memory_id)

    envelope_index: list[dict[str, object]] = []
    memory_roots: list[str] = []
    memory_entries: list[dict[str, str]] = []

    for env in envelopes:
        env_file = store.root / "memories" / f"{env.memory_id}.env.json"
        payload_file = store.root / "memories" / f"{env.memory_id}.bin.b64"
        if not env_file.exists() or not payload_file.exists():
            continue

        envelope_index.append(json.loads(envelope_to_json(env)))
        memory_roots.append(env.merkle_root)
        memory_entries.append(
            {
                "memory_id": env.memory_id,
                "envelope": f"memories/{env_file.name}",
                "payload": f"memories/{payload_file.name}",
            }
        )

    manifest = {
        "profile": profile_name,
        "mode": mode,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "memory_count": len(memory_entries),
        "memory_merkle_roots": memory_roots,
        "merkle_root": merkle_root(memory_roots),
        "encoding": "base64",
        "hash_algo": "sha256",
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(output_path, "w:gz") as archive:
        for entry in memory_entries:
            archive.add(store.root / entry["envelope"], arcname=entry["envelope"])
            archive.add(store.root / entry["payload"], arcname=entry["payload"])

        index_bytes = json.dumps(envelope_index, separators=(",", ":"), sort_keys=True).encode("utf-8")
        manifest_bytes = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")
        memories_bytes = json.dumps(memory_entries, separators=(",", ":"), sort_keys=True).encode("utf-8")

        for arcname, blob in (
            ("envelope_index.json", index_bytes),
            ("manifest.json", manifest_bytes),
            ("memories_index.json", memories_bytes),
        ):
            info = tarfile.TarInfo(name=arcname)
            info.size = len(blob)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(blob))

    return {
        "path": str(output_path),
        "memory_count": len(memory_entries),
        "merkle_root": manifest["merkle_root"],
    }


@app.command("export")
def export(
    ctx: typer.Context,
    out: Path | None = typer.Option(None, "--out", help="Output .tar.gz path for export archive."),
    json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Export local encrypted memories to tar.gz with archive manifest integrity."""

    gctx = get_global_context(ctx)
    json_output = gctx.json_output or json_output_flag

    cfg = load_config()
    profile = get_active_profile(cfg, gctx.profile)
    target = out or _default_export_path(profile.name)

    result = _build_export_archive(profile.name, profile.mode, target)

    if json_output:
        typer.echo(json.dumps(result))
    elif gctx.plain:
        typer.echo(f"export: {result['path']}")
        typer.echo(f"memories: {result['memory_count']}")
        typer.echo(f"merkle_root: {result['merkle_root']}")
    else:
        _render_card(
            "VAULT EXPORT",
            [
                ("path", str(result["path"])),
                ("memories", str(result["memory_count"])),
                ("merkle", str(result["merkle_root"])),
            ],
            status_chip="✓ EXPORTED",
            style="success",
        )

    raise typer.Exit(code=EXIT_OK)


@app.command("sync")
def sync(
    ctx: typer.Context,
    watch: int | None = typer.Option(
        None,
        "--watch",
        min=1,
        flag_value=60,
        help="Continuously sync every INTERVAL seconds (defaults to 60 when used without a value).",
    ),
    json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Synchronize local encrypted memories with managed storage."""

    require_mode("managed")(ctx)

    gctx = get_global_context(ctx)
    json_output = gctx.json_output or json_output_flag
    console = make_console()

    cfg = load_config()
    profile = get_active_profile(cfg, gctx.profile)

    token = os.getenv("MATRIOSHA_MANAGED_TOKEN")
    if not token:
        _emit_error(
            title="Managed token missing",
            category="AUTH",
            stable_code="AUTH-211",
            exit_code=EXIT_AUTH,
            fix="set MATRIOSHA_MANAGED_TOKEN or run `matriosha auth login`",
            debug="missing MATRIOSHA_MANAGED_TOKEN",
            json_output=json_output,
            plain=gctx.plain,
        )
        raise typer.Exit(code=EXIT_AUTH)

    endpoint = profile.managed_endpoint or os.getenv("MATRIOSHA_MANAGED_ENDPOINT")

    async def _run_sync() -> SyncReport:
        async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
            try:
                await client.whoami()
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"managed token validation failed: {type(exc).__name__}: {exc}") from exc

            engine = SyncEngine(local=LocalStore(profile.name), remote=client, embedder=get_default_embedder())
            return await engine.sync()

    def _run_single_iteration() -> SyncReport:
        if json_output or gctx.plain:
            return asyncio.run(_run_sync())

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("vault sync", total=3)
            progress.update(task, description="[bold cyan]validating managed session")
            progress.advance(task)
            progress.update(task, description="[bold cyan]syncing memories")
            report = asyncio.run(_run_sync())
            progress.advance(task, advance=2)
            return report

    watch_interval = watch
    if watch_interval is None:
        try:
            report = _run_single_iteration()
        except RuntimeError as exc:
            _emit_error(
                title="Managed sync failed",
                category="AUTH",
                stable_code="AUTH-212",
                exit_code=EXIT_AUTH,
                fix="refresh managed credentials and retry",
                debug=str(exc),
                json_output=json_output,
                plain=gctx.plain,
            )
            raise typer.Exit(code=EXIT_AUTH)

        _emit_sync_report(report, json_output=json_output, plain=gctx.plain, console=console)
        if report.errors:
            raise typer.Exit(code=EXIT_INTEGRITY)
        raise typer.Exit(code=EXIT_OK)

    stop_requested = False

    def _sigint_handler(signum, frame) -> None:  # noqa: ANN001,ARG001
        nonlocal stop_requested
        stop_requested = True
        logger.info("vault sync watch received SIGINT; stopping after current iteration")

    previous_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _sigint_handler)

    iteration = 0
    try:
        while True:
            iteration += 1
            logger.info("vault sync watch iteration=%s started", iteration)

            try:
                report = _run_single_iteration()
                _emit_sync_report(report, json_output=json_output, plain=gctx.plain, console=console)
                logger.info(
                    "vault sync watch iteration=%s complete pushed=%s pulled=%s errors=%s",
                    iteration,
                    report.pushed,
                    report.pulled,
                    len(report.errors),
                )
            except RuntimeError as exc:
                debug = str(exc)
                logger.warning("vault sync watch iteration=%s failed: %s", iteration, debug)
                if json_output:
                    typer.echo(json.dumps({"status": "error", "iteration": iteration, "error": debug}))
                elif gctx.plain:
                    typer.echo(f"iteration {iteration} error: {debug}")
                else:
                    typer.echo(f"[watch] iteration {iteration} error: {debug}")
            except Exception as exc:  # noqa: BLE001
                debug = f"{type(exc).__name__}: {exc}"
                logger.warning("vault sync watch iteration=%s unexpected failure: %s", iteration, debug)
                if json_output:
                    typer.echo(json.dumps({"status": "error", "iteration": iteration, "error": debug}))
                elif gctx.plain:
                    typer.echo(f"iteration {iteration} error: {debug}")
                else:
                    typer.echo(f"[watch] iteration {iteration} error: {debug}")

            if stop_requested:
                break

            slept = 0
            while slept < watch_interval and not stop_requested:
                time.sleep(1)
                slept += 1

        raise typer.Exit(code=EXIT_OK)
    finally:
        signal.signal(signal.SIGINT, previous_handler)
