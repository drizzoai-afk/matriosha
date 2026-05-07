"""Memory command package with isolated subcommand modules."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading  # noqa: F401 - compatibility export for memory package monkeypatching
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import typer
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table
from rich.tree import Tree

from matriosha.cli.brand.theme import console as make_console
from matriosha.cli.utils.errors import EXIT_AUTH, EXIT_INTEGRITY, EXIT_UNKNOWN, EXIT_USAGE
from matriosha.cli.utils.output import resolve_output
from matriosha.core.audit import AuditEvent, AuditJournal
from matriosha.core.binary_protocol import decode_envelope, encode_envelope
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.crypto import IntegrityError
from matriosha.core.interpreter import decode_semantic_content
from matriosha.core.managed.auth import ensure_process_managed_passphrase, resolve_access_token
from matriosha.core.managed.backup import ManagedBackupError, ManagedBackupStore
from matriosha.core.managed.client import ManagedClient
from matriosha.core.managed.sync import SyncEngine
from matriosha.core.storage_local import LocalStore
from matriosha.core.vault import AuthError, Vault, VaultIntegrityError
from matriosha.core.vectors import LocalVectorIndex, get_default_embedder


_MAX_MEMORY_BYTES = 50 * 1024 * 1024
_SEMANTIC_PREVIEW_CHARS = 4096
_SEMANTIC_SEARCH_TEXT_LIMIT = 24_000
_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,31}$")
logger = logging.getLogger(__name__)


def _audit_memory_event(
    *,
    profile_name: str,
    profile_mode: str,
    action: str,
    target_id: str | None,
    outcome: str,
    reason_code: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Best-effort local audit journal write; audit failures must not break commands."""

    try:
        AuditJournal(profile_name).append(
            AuditEvent.create(
                profile=profile_name,
                mode=profile_mode,
                action=action,
                target_type="memory",
                target_id=target_id,
                outcome=outcome,
                reason_code=reason_code,
                metadata=metadata or {},
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "audit write failed action=%s profile=%s error=%s",
            action,
            profile_name,
            type(exc).__name__,
        )


def _is_missing_vault_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "vault material missing" in message or "vault not initialized" in message


def _memory_package_patchable(name: str, fallback):
    package = sys.modules.get("matriosha.cli.commands.memory")
    return getattr(package, name, fallback) if package is not None else fallback


class InvalidInput(ValueError):
    """Raised when command input does not satisfy the command contract."""


def _short(value: str, *, head: int = 8, tail: int = 4) -> str:
    if len(value) <= head + tail + 1:
        return value
    return f"{value[:head]}…{value[-tail:]}"


def _render_panel(
    title: str,
    rows: list[tuple[str, str]],
    *,
    status_chip: str,
    style: str,
    console: Console,
) -> None:
    width = 88
    inner = width - 2
    header = f" {status_chip} {title} "
    header_pad = max(0, inner - len(header))
    console.print(
        f"[{style}]╭{'─' * (header_pad // 2)}{header}{'─' * (header_pad - header_pad // 2)}╮[/{style}]"
    )
    for key, value in rows:
        line = f" {key:<10} {value} "
        console.print(f"[{style}]│{line:<{inner}}│[/{style}]")
    console.print(f"[{style}]╰{'─' * inner}╯[/{style}]")


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
    console: Console,
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
    elif plain:
        typer.echo(f"{title}")
        typer.echo(f"category: {category}  code: {stable_code}  exit: {exit_code}")
        typer.echo(f"fix: {fix}")
        typer.echo(f"debug: {debug}")
    else:
        _render_panel(
            title,
            [
                ("category", f"{category}  code: {stable_code}  exit: {exit_code}"),
                ("fix", fix),
                ("debug", debug),
            ],
            status_chip="✖ ERROR",
            style="danger",
            console=console,
        )


def _require_managed_session_for_memory(
    profile, *, json_output: bool, plain: bool, console: Console
) -> str | None:
    """Return managed token for managed profiles, or stop before local fallback."""

    if profile.mode != "managed":
        return None

    token = resolve_access_token(profile.name)
    if token:
        return token

    _emit_error(
        title="Managed login required",
        category="AUTH",
        stable_code="AUTH-010",
        exit_code=EXIT_AUTH,
        fix=f"run `matriosha --profile {profile.name} auth login`",
        debug=f"profile={profile.name} mode=managed reason=missing_session_token",
        json_output=json_output,
        plain=plain,
        console=console,
    )
    raise typer.Exit(code=EXIT_AUTH)


def _resolve_payload_bytes(*, text: str | None, file_path: Path | None, stdin_input: bool) -> bytes:
    selected = int(text is not None) + int(file_path is not None) + int(stdin_input)
    if selected != 1:
        raise InvalidInput("provide exactly one input source: TEXT or --file or --stdin")

    if text is not None:
        payload = text.encode("utf-8")
    elif file_path is not None:
        if not file_path.exists() or not file_path.is_file():
            raise InvalidInput(f"file not found: {file_path}")
        payload = file_path.read_bytes()
    else:
        payload = sys.stdin.buffer.read()

    if len(payload) > _MAX_MEMORY_BYTES:
        raise InvalidInput("input exceeds max size of 50 MiB")

    return payload


def _validate_tags(tags: list[str]) -> list[str]:
    normalized = []
    for tag in tags:
        if not _TAG_PATTERN.fullmatch(tag):
            example = tag.lower()[:32] if tag else "example-tag"
            raise InvalidInput(
                f"Tag '{tag}' is invalid. Tags must be lowercase, max 32 chars, "
                "and may contain a-z, 0-9, hyphen, or underscore. "
                "Expected regex: ^[a-z0-9][a-z0-9_\\-]{0,31}$. "
                f"Example: {example}"
            )
        normalized.append(tag)
    return normalized


def _resolve_passphrase(*, profile_name: str, profile_mode: str, json_output: bool = False) -> str:
    if profile_mode == "managed":
        managed = ensure_process_managed_passphrase(profile_name)
        if managed:
            return managed
        raise AuthError("managed key session missing; run `matriosha auth login`")

    env_passphrase = os.getenv("MATRIOSHA_PASSPHRASE")
    if env_passphrase:
        return env_passphrase
    return typer.prompt("Vault passphrase", hide_input=True, err=json_output)


def _parse_iso8601(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise InvalidInput("invalid --since value; expected ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _memory_summary_dict(memory_id: str, env_obj, payload_size: int) -> dict[str, object]:
    return {
        "id": memory_id,
        "memory_id": memory_id,
        "created": env_obj.created_at,
        "tags": env_obj.tags,
        "bytes": getattr(env_obj, "plaintext_bytes", None) or payload_size,
        "stored_bytes": payload_size,
        "blocks": len(getattr(env_obj, "merkle_leaves", []) or []),
        "encoding": getattr(env_obj, "encoding", "base64"),
        "hash_algo": getattr(env_obj, "hash_algo", "sha256"),
        "merkle_root": env_obj.merkle_root,
        "mode": env_obj.mode,
        "source": env_obj.source,
        "filename": getattr(env_obj, "filename", None),
        "mime_type": getattr(env_obj, "mime_type", None),
        "content_kind": getattr(env_obj, "content_kind", None),
        "children": getattr(env_obj, "children", None),
    }


def _preview_plaintext(plaintext: bytes, *, max_chars: int = 80) -> str:
    text = plaintext.decode("utf-8", errors="replace").replace("\n", " ").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _detect_filename_from_tags(tags: list[str]) -> str | None:
    for tag in tags:
        if "." in tag and not tag.startswith(".") and len(tag) <= 128:
            return tag
    return None


def _semantic_from_plaintext(
    *,
    plaintext: bytes,
    envelope_tags: list[str],
    memory_id: str,
    text_limit: int | None = None,
    filename: str | None = None,
    mime_type: str | None = None,
    content_kind: str | None = None,
) -> dict[str, object]:
    detected_filename = filename or _detect_filename_from_tags(envelope_tags)
    detected_mime = mime_type or (
        "text/plain" if content_kind != "binary" else "application/octet-stream"
    )
    semantic = decode_semantic_content(
        plaintext,
        {
            "mime_type": detected_mime,
            "filename": detected_filename,
            "hints": {"memory_id": memory_id, "content_kind": content_kind},
        },
    )
    if text_limit is not None and len(str(semantic.get("text") or "")) > text_limit:
        semantic["text"] = str(semantic.get("text") or "")[:text_limit]
        warnings = list(semantic.get("warnings") or [])
        warnings.append(f"semantic text truncated to {text_limit} chars for search output")
        semantic["warnings"] = warnings
        semantic["preview"] = str(semantic.get("preview") or "")[:_SEMANTIC_PREVIEW_CHARS]
    return semantic


def _try_managed_backup_restore(
    *,
    profile_mode: str,
    memory_id: str,
    store: LocalStore,
) -> bytes | None:
    if profile_mode != "managed":
        return None
    backup_store_cls = _memory_package_patchable("ManagedBackupStore", ManagedBackupStore)
    backup = backup_store_cls()
    backup_payload = backup.download_backup(memory_id)
    store.replace_payload(memory_id, backup_payload)
    return backup_payload


def _decode_with_corruption_handling(
    *,
    env,
    b64_payload: bytes,
    key: bytes,
    profile_mode: str,
    memory_id: str,
    store: LocalStore,
) -> tuple[bytes | None, str | None, bool]:
    try:
        patched_decode_envelope = _memory_package_patchable("decode_envelope", decode_envelope)
        return patched_decode_envelope(env, b64_payload, key), None, False
    except IntegrityError as exc:
        exc_message = str(exc) or type(exc).__name__
        merkle_detected = "Merkle" in exc_message
        warning = (
            f"Merkle corruption detected for {memory_id}"
            if merkle_detected
            else "Encrypted memory failed integrity checks"
        )
        if profile_mode == "managed" and merkle_detected:
            try:
                recovered_payload = _try_managed_backup_restore(
                    profile_mode=profile_mode,
                    memory_id=memory_id,
                    store=store,
                )
                if recovered_payload is not None:
                    patched_decode_envelope = _memory_package_patchable(
                        "decode_envelope", decode_envelope
                    )
                    recovered = patched_decode_envelope(env, recovered_payload, key)
                    return (
                        recovered,
                        f"Merkle corruption detected; restored from managed backup for {memory_id}",
                        True,
                    )
            except ManagedBackupError:
                raise
            except Exception as restore_exc:  # noqa: BLE001
                raise IntegrityError(
                    f"Merkle corruption detected and backup restore failed: {type(restore_exc).__name__}"
                ) from restore_exc

        return None, warning, False


def _cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    a = np.asarray(vec_a, dtype=np.float32)
    b = np.asarray(vec_b, dtype=np.float32)
    if a.shape != b.shape:
        raise ValueError("vectors must have same shape")
    return float(a @ b)


def _schedule_managed_auto_sync_if_enabled(
    profile_name: str,
    *,
    profile_mode: str,
    auto_sync_enabled: bool,
    managed_endpoint: str | None,
) -> None:
    if profile_mode != "managed" or not auto_sync_enabled:
        return

    token = resolve_access_token(profile_name)
    if not token:
        logger.warning("auto-sync skipped: missing managed session token")
        return

    executable = shutil.which("matriosha")
    if not executable:
        logger.warning("auto-sync skipped: matriosha executable not found")
        return

    env = os.environ.copy()
    if managed_endpoint:
        env["MATRIOSHA_MANAGED_ENDPOINT"] = managed_endpoint

    cmd = [
        executable,
        "--profile",
        profile_name,
        "--json",
        "vault",
        "sync",
    ]

    try:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto-sync failed to start: %s: %s", type(exc).__name__, exc)


# Export private helper names to command modules that use `from .common import *`.
# This keeps the mechanical split behavior-compatible with the former single-file module.
__all__ = [
    "AuthError",
    "Confirm",
    "EXIT_AUTH",
    "EXIT_INTEGRITY",
    "EXIT_UNKNOWN",
    "EXIT_USAGE",
    "IntegrityError",
    "InvalidInput",
    "LocalStore",
    "LocalVectorIndex",
    "ManagedBackupError",
    "ManagedBackupStore",
    "ManagedClient",
    "Path",
    "SyncEngine",
    "Table",
    "Tree",
    "Vault",
    "VaultIntegrityError",
    "asdict",
    "asyncio",
    "base64",
    "decode_envelope",
    "encode_envelope",
    "get_active_profile",
    "get_default_embedder",
    "json",
    "load_config",
    "make_console",
    "np",
    "resolve_output",
    "sys",
    "typer",
]
