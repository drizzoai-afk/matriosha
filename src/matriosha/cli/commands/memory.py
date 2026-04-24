"""Memory command group with Phase 2.6 `remember` implementation."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import sys
import threading
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

app = typer.Typer(help="Encrypted memory operations.", no_args_is_help=True)

_MAX_MEMORY_BYTES = 50 * 1024 * 1024
_SEMANTIC_PREVIEW_CHARS = 4096
_SEMANTIC_SEARCH_TEXT_LIMIT = 24_000
_TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,31}$")
logger = logging.getLogger(__name__)


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
            raise InvalidInput(
                f"invalid tag '{tag}'. expected regex: ^[a-z0-9][a-z0-9_\\-]{{0,31}}$"
            )
        normalized.append(tag)
    return normalized


def _resolve_passphrase(*, profile_name: str, profile_mode: str) -> str:
    if profile_mode == "managed":
        managed = ensure_process_managed_passphrase(profile_name)
        if managed:
            return managed
        raise AuthError("managed key session missing; run `matriosha auth login`")

    env_passphrase = os.getenv("MATRIOSHA_PASSPHRASE")
    if env_passphrase:
        return env_passphrase
    return typer.prompt("Vault passphrase", hide_input=True)


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
    envelope_dict = asdict(env_obj)
    envelope_dict["merkle_leaf"] = envelope_dict.pop("merkle_leaves")
    return {
        "id": memory_id,
        "created": env_obj.created_at,
        "tags": env_obj.tags,
        "bytes": payload_size,
        "merkle_root": env_obj.merkle_root,
        "envelope": envelope_dict,
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
) -> dict[str, object]:
    filename = _detect_filename_from_tags(envelope_tags)
    semantic = decode_semantic_content(
        plaintext,
        {
            "mime_type": "text/plain",
            "filename": filename,
            "hints": {"memory_id": memory_id},
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
    backup = ManagedBackupStore()
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
        return decode_envelope(env, b64_payload, key), None, False
    except IntegrityError as exc:
        warning = f"Merkle corruption detected for {memory_id}: {exc}"
        if profile_mode == "managed" and "Merkle" in str(exc):
            try:
                recovered_payload = _try_managed_backup_restore(
                    profile_mode=profile_mode,
                    memory_id=memory_id,
                    store=store,
                )
                if recovered_payload is not None:
                    recovered = decode_envelope(env, recovered_payload, key)
                    return recovered, f"Merkle corruption detected; restored from managed backup for {memory_id}", True
            except ManagedBackupError:
                raise
            except Exception as restore_exc:  # noqa: BLE001
                raise IntegrityError(
                    f"Merkle corruption detected and backup restore failed: {type(restore_exc).__name__}: {restore_exc}"
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

    endpoint = managed_endpoint or os.getenv("MATRIOSHA_MANAGED_ENDPOINT")

    async def _auto_sync() -> None:
        try:
            async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
                engine = SyncEngine(local=LocalStore(profile_name), remote=client, embedder=get_default_embedder())
                await engine.sync()
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto-sync failed: %s: %s", type(exc).__name__, exc)

    def _thread_runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            task = loop.create_task(_auto_sync())
            loop.run_until_complete(task)
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    thread = threading.Thread(target=_thread_runner, daemon=True, name="matriosha-auto-sync")
    thread.start()


@app.command("remember")
def remember(
    ctx: typer.Context,
    text: str | None = typer.Argument(None, help="Text to store as encrypted memory."),
    file_path: Path | None = typer.Option(None, "--file", help="Read memory payload from file."),
    tags: list[str] = typer.Option([], "--tag", help="Attach one or more lowercase tags."),
    stdin_input: bool = typer.Option(False, "--stdin", help="Read memory payload from stdin."),
    json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Store encrypted memory into the local profile store."""

    output = resolve_output(ctx, json_flag=json_output_flag)
    gctx = output.ctx
    json_output = gctx.json_output
    console = make_console()

    try:
        payload = _resolve_payload_bytes(text=text, file_path=file_path, stdin_input=stdin_input)
        validated_tags = _validate_tags(tags)

        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)
        active_mode = profile.mode

        if stdin_input and (not json_output) and (not gctx.plain):
            console.print("[accent]● READING STDIN[/accent]")

        vault = Vault.unlock(profile.name, _resolve_passphrase(profile_name=profile.name, profile_mode=profile.mode))
        env, b64_payload = encode_envelope(
            payload,
            vault.data_key,
            mode=active_mode,
            tags=validated_tags,
            source="cli",
        )

        store = LocalStore(profile.name)
        embedder = get_default_embedder()
        embedding_input = payload[: 4 * 1024].decode("utf-8", errors="replace")
        embedding = embedder.embed(embedding_input)
        path = store.put(env, b64_payload, embedding=embedding)

        backup_key: str | None = None
        backup_warning: str | None = None
        if active_mode == "managed":
            try:
                backup_key = ManagedBackupStore().upload_backup(env.memory_id, b64_payload)
            except ManagedBackupError as backup_exc:
                backup_warning = str(backup_exc)

        _schedule_managed_auto_sync_if_enabled(
            profile.name,
            profile_mode=active_mode,
            auto_sync_enabled=cfg.managed.auto_sync,
            managed_endpoint=profile.managed_endpoint,
        )

        result = {
            "memory_id": env.memory_id,
            "bytes": len(payload),
            "blocks": len(env.merkle_leaves),
            "merkle_root": env.merkle_root,
            "tags": validated_tags,
            "path": str(path),
            "backup_key": backup_key,
            "backup_warning": backup_warning,
        }

        if json_output:
            output.json({"status": "ok", "operation": "memory.remember", "data": result, "error": None})
        elif gctx.plain:
            typer.echo(f"memory stored: {env.memory_id}")
            typer.echo(f"bytes: {len(payload)}")
            typer.echo(f"blocks: {len(env.merkle_leaves)}")
            typer.echo(f"merkle_root: {env.merkle_root}")
            typer.echo(f"tags: {', '.join(validated_tags) if validated_tags else '-'}")
        else:
            rendered_tags = " ".join(f"#{tag}" for tag in validated_tags) if validated_tags else "-"
            _render_panel(
                "MEMORY STORED",
                [
                    ("id", _short(env.memory_id, head=12, tail=6)),
                    ("bytes", f"{len(payload):,}"),
                    ("blocks", str(len(env.merkle_leaves))),
                    ("merkle", _short(env.merkle_root, head=12, tail=6)),
                    ("tags", rendered_tags),
                ],
                status_chip="✓ SUCCESS",
                style="success",
                console=console,
            )

        return

    except InvalidInput as exc:
        _emit_error(
            title="Invalid remember input",
            category="VAL",
            stable_code="VAL-001",
            exit_code=EXIT_USAGE,
            fix="provide exactly one source and valid tags; keep input <= 50 MiB",
            debug=f"detail={exc}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_USAGE)
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
            console=console,
        )
        raise typer.Exit(code=EXIT_AUTH)
    except IntegrityError:
        _emit_error(
            title="Memory encoding integrity failure",
            category="SYS",
            stable_code="SYS-010",
            exit_code=EXIT_INTEGRITY,
            fix="retry the command; if persistent run `matriosha vault verify`",
            debug="phase=encode_envelope integrity_check_failed",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_INTEGRITY)
    except (VaultIntegrityError, OSError, ValueError) as exc:
        _emit_error(
            title="Local storage operation failed",
            category="STORE",
            stable_code="STORE-001",
            exit_code=EXIT_UNKNOWN,
            fix="check file permissions and available disk, then retry",
            debug=f"os_error={type(exc).__name__}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_UNKNOWN)
    except Exception as exc:  # noqa: BLE001
        _emit_error(
            title="Unexpected remember failure",
            category="SYS",
            stable_code="SYS-999",
            exit_code=EXIT_UNKNOWN,
            fix="retry with --debug and run `matriosha doctor`",
            debug=f"exception={type(exc).__name__}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_UNKNOWN)


@app.command("recall")
def recall(
    ctx: typer.Context,
    memory_id: str = typer.Argument(..., help="Memory identifier to decrypt and print."),
    show_metadata: bool = typer.Option(False, "--show-metadata", help="Include envelope metadata JSON."),
    out: Path | None = typer.Option(None, "--out", help="Write plaintext bytes to file instead of stdout."),
    json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Recall one encrypted memory and verify integrity."""

    output = resolve_output(ctx, json_flag=json_output_flag)
    gctx = output.ctx
    json_output = gctx.json_output
    console = make_console()

    try:
        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)
        vault = Vault.unlock(profile.name, _resolve_passphrase(profile_name=profile.name, profile_mode=profile.mode))
        store = LocalStore(profile.name)

        try:
            env, b64_payload = store.get(memory_id)
        except FileNotFoundError:
            _emit_error(
                title="Memory not found",
                category="VAL",
                stable_code="VAL-404",
                exit_code=EXIT_USAGE,
                fix="run `matriosha memory list` and retry with a valid memory id",
                debug=f"memory_id={memory_id}",
                json_output=json_output,
                plain=gctx.plain,
                console=console,
            )
            raise typer.Exit(code=EXIT_USAGE) from None

        plaintext, integrity_warning, restored_from_backup = _decode_with_corruption_handling(
            env=env,
            b64_payload=b64_payload,
            key=vault.data_key,
            profile_mode=profile.mode,
            memory_id=env.memory_id,
            store=store,
        )

        semantic = (
            _semantic_from_plaintext(
                plaintext=plaintext,
                envelope_tags=env.tags,
                memory_id=env.memory_id,
            )
            if plaintext is not None
            else decode_semantic_content(
                b64_payload,
                {
                    "mime_type": "application/octet-stream",
                    "filename": f"{env.memory_id}.bin.b64",
                    "hints": {"memory_id": env.memory_id, "corrupted": True},
                },
            )
        )

        if integrity_warning:
            semantic_warnings = list(semantic.get("warnings") or [])
            semantic_warnings.append(integrity_warning)
            semantic["warnings"] = semantic_warnings

        if out is not None and plaintext is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(plaintext)

        metadata_json = json.dumps(asdict(env), separators=(",", ":"))

        if json_output:
            payload = {
                "status": "ok",
                "operation": "memory.recall",
                "data": {
                    "memory_id": env.memory_id,
                    "bytes": len(plaintext) if plaintext is not None else 0,
                    "out": str(out) if out and plaintext is not None else None,
                    "plaintext_b64": None
                    if out or plaintext is None
                    else base64.b64encode(plaintext).decode("ascii"),
                    "preview": str(semantic.get("preview") or "")[:_SEMANTIC_PREVIEW_CHARS],
                    "semantic": semantic,
                    "integrity_warning": integrity_warning,
                    "restored_from_backup": restored_from_backup,
                    "envelope": asdict(env) if show_metadata else None,
                },
                "error": None,
            }
            typer.echo(json.dumps(payload))
            raise typer.Exit(code=0)

        if out is not None and plaintext is not None:
            if gctx.plain:
                typer.echo(f"memory recalled: {env.memory_id}")
                typer.echo(f"out: {out}")
                if integrity_warning:
                    typer.echo(f"WARNING: {integrity_warning}")
                if show_metadata:
                    typer.echo(metadata_json)
            else:
                _render_panel(
                    "MEMORY RECALLED",
                    [
                        ("id", _short(env.memory_id, head=12, tail=6)),
                        ("bytes", f"{len(plaintext):,}"),
                        ("out", str(out)),
                    ],
                    status_chip="✓ SUCCESS",
                    style="success",
                    console=console,
                )
                if integrity_warning:
                    console.print(f"[warning]WARNING:[/warning] {integrity_warning}")
                if show_metadata:
                    console.print(metadata_json)
            raise typer.Exit(code=0)

        if plaintext is not None:
            if show_metadata:
                sys.stdout.buffer.write(plaintext)
                sys.stdout.buffer.write(b"\n")
                typer.echo(metadata_json)
            else:
                sys.stdout.buffer.write(plaintext)
        else:
            if gctx.plain:
                typer.echo(f"WARNING: {integrity_warning}")
            else:
                console.print(f"[warning]WARNING:[/warning] {integrity_warning}")
        raise typer.Exit(code=0)

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
            console=console,
        )
        raise typer.Exit(code=EXIT_AUTH)
    except IntegrityError:
        _emit_error(
            title="Memory integrity verification failed",
            category="SYS",
            stable_code="SYS-011",
            exit_code=EXIT_INTEGRITY,
            fix="run `matriosha vault verify --deep` to inspect corrupted entries",
            debug=f"memory_id={memory_id} phase=decode_envelope",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_INTEGRITY)
    except ManagedBackupError as exc:
        _emit_error(
            title="Managed backup restore failed",
            category="STORE",
            stable_code="STORE-008",
            exit_code=EXIT_UNKNOWN,
            fix="verify managed credentials/network and retry recall",
            debug=f"backup_error={type(exc).__name__}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_UNKNOWN)
    except InvalidInput as exc:
        _emit_error(
            title="Invalid recall input",
            category="VAL",
            stable_code="VAL-002",
            exit_code=EXIT_USAGE,
            fix="use a valid memory id and ISO-8601 timestamps where applicable",
            debug=f"detail={exc}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_USAGE)
    except (VaultIntegrityError, OSError, ValueError) as exc:
        _emit_error(
            title="Local storage operation failed",
            category="STORE",
            stable_code="STORE-002",
            exit_code=EXIT_UNKNOWN,
            fix="check file permissions and available disk, then retry",
            debug=f"os_error={type(exc).__name__}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_UNKNOWN)


@app.command("search")
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Semantic query to search memories."),
    k: int = typer.Option(10, "--k", min=1, help="Maximum number of nearest memories to retrieve."),
    threshold: float = typer.Option(0.0, "--threshold", help="Minimum cosine score to include."),
    tag: str | None = typer.Option(None, "--tag", help="Filter results by tag after ANN search."),
    json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Semantically search encrypted memories using local vector index."""

    output = resolve_output(ctx, json_flag=json_output_flag)
    gctx = output.ctx
    json_output = gctx.json_output
    console = make_console()

    try:
        if threshold < -1.0 or threshold > 1.0:
            raise InvalidInput("--threshold must be between -1.0 and 1.0")

        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)

        store = LocalStore(profile.name)
        index = LocalVectorIndex(profile.name)
        embedder = get_default_embedder()
        vault = Vault.unlock(profile.name, _resolve_passphrase(profile_name=profile.name, profile_mode=profile.mode))

        query_vec = embedder.embed(query)
        candidates = index.search(query_vec, k=k)

        rows: list[dict[str, object]] = []
        for memory_id, score in candidates:
            if score < threshold:
                continue

            try:
                env, b64_payload = store.get(memory_id)
            except (FileNotFoundError, ValueError):
                continue

            if tag is not None and tag not in env.tags:
                continue

            plaintext, integrity_warning, restored_from_backup = _decode_with_corruption_handling(
                env=env,
                b64_payload=b64_payload,
                key=vault.data_key,
                profile_mode=profile.mode,
                memory_id=memory_id,
                store=store,
            )

            if plaintext is not None:
                semantic = _semantic_from_plaintext(
                    plaintext=plaintext,
                    envelope_tags=env.tags,
                    memory_id=memory_id,
                    text_limit=_SEMANTIC_SEARCH_TEXT_LIMIT,
                )
                preview = str(semantic.get("preview") or "")[:80] or _preview_plaintext(plaintext, max_chars=80)
            else:
                semantic = decode_semantic_content(
                    b64_payload,
                    {
                        "mime_type": "application/octet-stream",
                        "filename": f"{memory_id}.bin.b64",
                        "hints": {"memory_id": memory_id, "corrupted": True},
                    },
                )
                preview = str(semantic.get("preview") or "")[:80]

            if integrity_warning:
                semantic_warnings = list(semantic.get("warnings") or [])
                semantic_warnings.append(integrity_warning)
                semantic["warnings"] = semantic_warnings

            rows.append(
                {
                    "rank": len(rows) + 1,
                    "memory_id": memory_id,
                    "score": score,
                    "tags": env.tags,
                    "created_at": env.created_at,
                    "preview": preview,
                    "semantic": semantic,
                    "integrity_warning": integrity_warning,
                    "restored_from_backup": restored_from_backup,
                }
            )

        if json_output:
            payload = {
                "status": "ok",
                "operation": "memory.search",
                "data": {
                    "query": query,
                    "k": k,
                    "threshold": threshold,
                    "tag": tag,
                    "results": [
                        {
                            "memory_id": row["memory_id"],
                            "score": row["score"],
                            "tags": row["tags"],
                            "created_at": row["created_at"],
                            "preview": row["preview"],
                            "semantic": row["semantic"],
                            "integrity_warning": row["integrity_warning"],
                            "restored_from_backup": row["restored_from_backup"],
                        }
                        for row in rows
                    ],
                },
                "error": None,
            }
            output.json(payload)
            raise typer.Exit(code=0)

        if gctx.plain:
            for row in rows:
                tags_str = ",".join(row["tags"]) if row["tags"] else "-"
                typer.echo(
                    f"{row['rank']}\t{row['memory_id']}\t{float(row['score']):.4f}\t{row['created_at']}\t"
                    f"{tags_str}\t{row['preview']}"
                )
            if not rows:
                typer.echo("no matching memories found")
            raise typer.Exit(code=0)

        table = Table(title="Memory Search", show_header=True, header_style="bold accent")
        table.add_column("rank", justify="right")
        table.add_column("id")
        table.add_column("score", justify="right")
        table.add_column("created")
        table.add_column("tags")
        table.add_column("preview")

        for row in rows:
            table.add_row(
                str(row["rank"]),
                str(row["memory_id"]),
                f"{float(row['score']):.4f}",
                str(row["created_at"]),
                " ".join(f"#{t}" for t in row["tags"]) if row["tags"] else "-",
                str(row["preview"]),
            )

        console.print(table)
        raise typer.Exit(code=0)

    except InvalidInput as exc:
        _emit_error(
            title="Invalid search input",
            category="VAL",
            stable_code="VAL-005",
            exit_code=EXIT_USAGE,
            fix="provide a query, valid threshold range, and valid tag filters",
            debug=f"detail={exc}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_USAGE)
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
            console=console,
        )
        raise typer.Exit(code=EXIT_AUTH)
    except IntegrityError:
        _emit_error(
            title="Memory integrity verification failed",
            category="SYS",
            stable_code="SYS-011",
            exit_code=EXIT_INTEGRITY,
            fix="run `matriosha vault verify --deep` to inspect corrupted entries",
            debug="phase=memory.search preview_decode_failed",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_INTEGRITY)
    except ManagedBackupError as exc:
        _emit_error(
            title="Managed backup restore failed",
            category="STORE",
            stable_code="STORE-009",
            exit_code=EXIT_UNKNOWN,
            fix="verify managed credentials/network and retry search",
            debug=f"backup_error={type(exc).__name__}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_UNKNOWN)
    except (VaultIntegrityError, OSError, ValueError) as exc:
        _emit_error(
            title="Local storage operation failed",
            category="STORE",
            stable_code="STORE-005",
            exit_code=EXIT_UNKNOWN,
            fix="check local memory files and vector index, then retry",
            debug=f"os_error={type(exc).__name__}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_UNKNOWN)


@app.command("list")
def list_memories(
    ctx: typer.Context,
    tag: str | None = typer.Option(None, "--tag", help="Filter by one tag value."),
    limit: int = typer.Option(50, "--limit", min=1, help="Maximum rows to return (default 50)."),
    since: str | None = typer.Option(None, "--since", help="Filter to created_at >= ISO-8601 timestamp."),
    json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """List memory envelopes from local store."""

    output = resolve_output(ctx, json_flag=json_output_flag)
    gctx = output.ctx
    json_output = gctx.json_output
    console = make_console()

    try:
        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)
        store = LocalStore(profile.name)

        since_dt = _parse_iso8601(since) if since else None
        envelopes = store.list(tag=tag, limit=1_000_000)

        rows: list[dict[str, object]] = []
        for env in envelopes:
            if since_dt is not None and _parse_iso8601(env.created_at) < since_dt:
                continue
            _, payload = store.get(env.memory_id)
            rows.append(_memory_summary_dict(env.memory_id, env, len(payload)))
            if len(rows) >= limit:
                break

        if json_output:
            payload = {
                "status": "ok",
                "operation": "memory.list",
                "data": {
                    "tag": tag,
                    "limit": limit,
                    "since": since,
                    "items": [row["envelope"] for row in rows],
                },
                "error": None,
            }
            output.json(payload)
            raise typer.Exit(code=0)

        if gctx.plain:
            for row in rows:
                typer.echo(
                    f"{_short(str(row['id']), head=12, tail=6)}\t{row['created']}\t"
                    f"{','.join(row['tags']) if row['tags'] else '-'}\t{row['bytes']}\t"
                    f"{_short(str(row['merkle_root']), head=12, tail=6)}"
                )
            if not rows:
                typer.echo("no memories found")
            raise typer.Exit(code=0)

        table = Table(title="Memory List", show_header=True, header_style="bold accent")
        table.add_column("id")
        table.add_column("created")
        table.add_column("tags")
        table.add_column("bytes", justify="right")
        table.add_column("merkle_root")

        for row in rows:
            tags_str = " ".join(f"#{t}" for t in row["tags"]) if row["tags"] else "-"
            table.add_row(
                _short(str(row["id"]), head=12, tail=6),
                str(row["created"]),
                tags_str,
                f"{int(row['bytes']):,}",
                _short(str(row["merkle_root"]), head=12, tail=6),
            )

        console.print(table)
        raise typer.Exit(code=0)

    except InvalidInput as exc:
        _emit_error(
            title="Invalid list filters",
            category="VAL",
            stable_code="VAL-003",
            exit_code=EXIT_USAGE,
            fix="use --since in ISO-8601 format and valid tag filters",
            debug=f"detail={exc}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_USAGE)
    except (VaultIntegrityError, OSError, ValueError) as exc:
        _emit_error(
            title="Local storage operation failed",
            category="STORE",
            stable_code="STORE-003",
            exit_code=EXIT_UNKNOWN,
            fix="check local memory files and retry",
            debug=f"os_error={type(exc).__name__}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_UNKNOWN)


@app.command("delete")
def delete(
    ctx: typer.Context,
    memory_id: str = typer.Argument(..., help="Memory identifier to delete."),
    yes: bool = typer.Option(False, "--yes", help="Delete without confirmation prompt."),
    strict: bool = typer.Option(False, "--strict", help="Exit 2 when memory id does not exist."),
    json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Delete one memory envelope+payload from local store."""

    output = resolve_output(ctx, json_flag=json_output_flag)
    gctx = output.ctx
    json_output = gctx.json_output
    console = make_console()

    try:
        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)
        store = LocalStore(profile.name)

        if not yes and not json_output:
            confirmed = Confirm.ask(f"Delete memory '{memory_id}'?", default=False)
            if not confirmed:
                raise typer.Exit(code=0)

        removed = store.delete(memory_id)
        deleted_count = 1 if removed else 0
        if removed:
            _schedule_managed_auto_sync_if_enabled(
                profile.name,
                profile_mode=profile.mode,
                auto_sync_enabled=cfg.managed.auto_sync,
                managed_endpoint=profile.managed_endpoint,
            )

        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "status": "ok",
                        "operation": "memory.delete",
                        "data": {
                            "memory_id": memory_id,
                            "deleted": deleted_count,
                        },
                        "error": None,
                    }
                )
            )
        elif gctx.plain:
            typer.echo(f"deleted: {deleted_count}")
        else:
            _render_panel(
                "MEMORY DELETE",
                [
                    ("id", _short(memory_id, head=12, tail=6)),
                    ("deleted", str(deleted_count)),
                ],
                status_chip="✓ SUCCESS" if removed else "⚠ NOOP",
                style="success" if removed else "yellow",
                console=console,
            )

        if strict and not removed:
            raise typer.Exit(code=EXIT_USAGE)
        raise typer.Exit(code=0)

    except InvalidInput as exc:
        _emit_error(
            title="Invalid delete input",
            category="VAL",
            stable_code="VAL-004",
            exit_code=EXIT_USAGE,
            fix="provide a valid memory id",
            debug=f"detail={exc}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_USAGE)
    except (VaultIntegrityError, OSError, ValueError) as exc:
        _emit_error(
            title="Local storage operation failed",
            category="STORE",
            stable_code="STORE-004",
            exit_code=EXIT_UNKNOWN,
            fix="check local memory files and retry",
            debug=f"os_error={type(exc).__name__}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_UNKNOWN)


@app.command("compress")
def compress(
    ctx: typer.Context,
    threshold: float = typer.Option(0.85, "--threshold", help="Cluster threshold for cosine similarity."),
    tag: str | None = typer.Option(None, "--tag", help="Only consider memories containing this tag."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview clusters without writing parent memories."),
    json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Cluster similar memories and write reversible compressed parent memories."""

    output = resolve_output(ctx, json_flag=json_output_flag)
    gctx = output.ctx
    json_output = gctx.json_output
    console = make_console()

    try:
        if threshold < -1.0 or threshold > 1.0:
            raise InvalidInput("--threshold must be between -1.0 and 1.0")

        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)
        store = LocalStore(profile.name)
        index = LocalVectorIndex(profile.name)
        embedder = get_default_embedder()
        vault = Vault.unlock(profile.name, _resolve_passphrase(profile_name=profile.name, profile_mode=profile.mode))

        all_envs = store.list(tag=tag, limit=1_000_000)
        env_by_id = {env.memory_id: env for env in all_envs}
        vector_by_id: dict[str, np.ndarray] = {}

        for idx, memory_id in enumerate(index._ids):  # noqa: SLF001 - internal store for local clustering
            if memory_id not in env_by_id:
                continue
            vector_by_id[memory_id] = np.asarray(index._vectors[idx], dtype=np.float32)  # noqa: SLF001

        candidate_ids = [env.memory_id for env in all_envs if env.memory_id in vector_by_id]
        remaining = list(candidate_ids)

        clusters: list[list[str]] = []
        while remaining:
            seed = remaining[0]
            seed_vec = vector_by_id[seed]

            cluster = [seed]
            for candidate in remaining[1:]:
                sim = _cosine_similarity(seed_vec, vector_by_id[candidate])
                if sim >= threshold:
                    cluster.append(candidate)

            clusters.append(cluster)
            clustered = set(cluster)
            remaining = [memory_id for memory_id in remaining if memory_id not in clustered]

        parent_records: list[dict[str, object]] = []

        for cluster in clusters:
            if len(cluster) < 2:
                continue

            plaintext_parts: list[bytes] = []
            cluster_tags: set[str] = set()

            for memory_id in cluster:
                env, b64_payload = store.get(memory_id)
                plaintext_parts.append(decode_envelope(env, b64_payload, vault.data_key))
                cluster_tags.update(env.tags)

            merged_plaintext = b"\n---\n".join(plaintext_parts)
            merged_tags = sorted(cluster_tags.union({"compressed", "parent"}))

            parent_env, parent_payload = encode_envelope(
                merged_plaintext,
                vault.data_key,
                mode=profile.mode,
                tags=merged_tags,
                source="cli",
            )
            parent_env.children = list(cluster)

            if not dry_run:
                cluster_vectors = [vector_by_id[memory_id] for memory_id in cluster]
                centroid = np.mean(np.vstack(cluster_vectors), axis=0).astype(np.float32)
                norm = float(np.linalg.norm(centroid))
                if norm > 0.0:
                    centroid = (centroid / norm).astype(np.float32)
                store.put(parent_env, parent_payload, embedding=centroid, embedding_kind="parent", is_active=True)

            parent_records.append(
                {
                    "parent_id": parent_env.memory_id,
                    "children": list(cluster),
                    "size": len(cluster),
                    "tags": merged_tags,
                }
            )

        result = {
            "dry_run": dry_run,
            "threshold": threshold,
            "tag": tag,
            "candidate_count": len(candidate_ids),
            "cluster_count": len(parent_records),
            "created_parents": parent_records,
            "singleton_count": sum(1 for cluster in clusters if len(cluster) == 1),
        }

        if json_output:
            typer.echo(json.dumps(result))
            raise typer.Exit(code=0)

        if gctx.plain:
            typer.echo(
                f"clusters={result['cluster_count']} singletons={result['singleton_count']} dry_run={str(dry_run).lower()}"
            )
            for cluster_idx, parent in enumerate(parent_records, start=1):
                typer.echo(
                    f"cluster_{cluster_idx}\tparent={parent['parent_id']}\tsize={parent['size']}\t"
                    f"children={','.join(parent['children'])}"
                )
            if not parent_records:
                typer.echo("no clusters found")
            raise typer.Exit(code=0)

        title = "Memory Compress (dry-run)" if dry_run else "Memory Compress"
        root = Tree(f"[bold accent]{title}[/bold accent]")
        root.add(f"threshold={threshold:.2f} candidates={len(candidate_ids)}")

        if parent_records:
            for cluster_idx, parent in enumerate(parent_records, start=1):
                cluster_node = root.add(
                    f"cluster {cluster_idx}: parent={parent['parent_id']} size={parent['size']}"
                )
                children_node = cluster_node.add("children")
                for child_id in parent["children"]:
                    children_node.add(child_id)
        else:
            root.add("no merge clusters found")

        root.add(f"singletons untouched: {result['singleton_count']}")
        console.print(root)
        raise typer.Exit(code=0)

    except InvalidInput as exc:
        _emit_error(
            title="Invalid compress input",
            category="VAL",
            stable_code="VAL-006",
            exit_code=EXIT_USAGE,
            fix="provide --threshold in range [-1.0, 1.0] and valid tag filters",
            debug=f"detail={exc}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_USAGE)
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
            console=console,
        )
        raise typer.Exit(code=EXIT_AUTH)
    except IntegrityError:
        _emit_error(
            title="Memory integrity verification failed",
            category="SYS",
            stable_code="SYS-011",
            exit_code=EXIT_INTEGRITY,
            fix="run `matriosha vault verify --deep` to inspect corrupted entries",
            debug="phase=memory.compress preview_decode_failed",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_INTEGRITY)
    except (VaultIntegrityError, OSError, ValueError) as exc:
        _emit_error(
            title="Local storage operation failed",
            category="STORE",
            stable_code="STORE-006",
            exit_code=EXIT_UNKNOWN,
            fix="check local memory files and vector index, then retry",
            debug=f"os_error={type(exc).__name__}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_UNKNOWN)


@app.command("decompress")
def decompress(
    ctx: typer.Context,
    parent_id: str = typer.Argument(..., help="Compressed parent memory id to expand."),
    keep_parent: bool = typer.Option(False, "--keep-parent", help="Keep parent memory after successful restore."),
    min_similarity: float = typer.Option(0.9, "--min-similarity", help="Minimum child-parent cosine similarity."),
    json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Validate and restore children from a compressed parent memory."""

    output = resolve_output(ctx, json_flag=json_output_flag)
    gctx = output.ctx
    json_output = gctx.json_output
    console = make_console()

    try:
        if min_similarity < -1.0 or min_similarity > 1.0:
            raise InvalidInput("--min-similarity must be between -1.0 and 1.0")

        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)
        store = LocalStore(profile.name)
        index = LocalVectorIndex(profile.name)
        embedder = get_default_embedder()
        vault = Vault.unlock(profile.name, _resolve_passphrase(profile_name=profile.name, profile_mode=profile.mode))

        try:
            parent_env, parent_payload = store.get(parent_id)
        except FileNotFoundError as exc:
            raise InvalidInput(f"parent memory not found: {parent_id}") from exc

        if not parent_env.children:
            if json_output:
                typer.echo(json.dumps({"status": "error", "message": "not a compressed parent", "exit": EXIT_USAGE}))
            else:
                typer.echo("not a compressed parent")
            raise typer.Exit(code=EXIT_USAGE)

        parent_vec = index.get_vector(parent_id)
        if parent_vec is None:
            parent_plaintext = decode_envelope(parent_env, parent_payload, vault.data_key)
            parent_input = parent_plaintext[: 4 * 1024].decode("utf-8", errors="replace")
            parent_vec = embedder.embed(parent_input)
            index.add(parent_id, parent_vec, entry_type="parent", is_active=True)
            index.save()

        restored_vectors: list[tuple[str, np.ndarray]] = []
        failing_children: list[dict[str, object]] = []

        for child_id in parent_env.children:
            try:
                child_env, child_payload = store.get(child_id)
                child_plaintext = decode_envelope(child_env, child_payload, vault.data_key)
            except FileNotFoundError:
                failing_children.append({"memory_id": child_id, "reason": "missing"})
                continue

            child_input = child_plaintext[: 4 * 1024].decode("utf-8", errors="replace")
            child_vec = embedder.embed(child_input)
            similarity = _cosine_similarity(child_vec, parent_vec)

            if similarity < min_similarity:
                failing_children.append({"memory_id": child_id, "similarity": similarity})
                continue

            restored_vectors.append((child_id, child_vec))

        if failing_children:
            if json_output:
                typer.echo(
                    json.dumps(
                        {
                            "status": "error",
                            "message": "integrity check failed",
                            "exit": EXIT_INTEGRITY,
                            "failing_children": failing_children,
                        }
                    )
                )
            else:
                typer.echo("integrity check failed")
                for item in failing_children:
                    if "similarity" in item:
                        typer.echo(f"- {item['memory_id']} similarity={float(item['similarity']):.6f}")
                    else:
                        typer.echo(f"- {item['memory_id']} reason={item['reason']}")
            raise typer.Exit(code=EXIT_INTEGRITY)

        for child_id, child_vec in restored_vectors:
            index.add(child_id, child_vec, entry_type="memory", is_active=True)
        index.save()

        parent_deleted = False
        if not keep_parent:
            parent_deleted = store.delete(parent_id)

        restored_ids = [memory_id for memory_id, _ in restored_vectors]
        payload = {"restored": restored_ids, "parent_deleted": parent_deleted}

        if json_output:
            typer.echo(json.dumps(payload))
            raise typer.Exit(code=0)

        if gctx.plain:
            typer.echo(f"restored: {','.join(restored_ids)}")
            typer.echo(f"parent_deleted: {str(parent_deleted).lower()}")
            raise typer.Exit(code=0)

        _render_panel(
            "MEMORY DECOMPRESS",
            [
                ("parent", _short(parent_id, head=12, tail=6)),
                ("restored", str(len(restored_ids))),
                ("parent_deleted", str(parent_deleted).lower()),
            ],
            status_chip="✓ SUCCESS",
            style="success",
            console=console,
        )
        raise typer.Exit(code=0)

    except InvalidInput as exc:
        _emit_error(
            title="Invalid decompress input",
            category="VAL",
            stable_code="VAL-007",
            exit_code=EXIT_USAGE,
            fix="provide a valid parent id and --min-similarity in range [-1.0, 1.0]",
            debug=f"detail={exc}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_USAGE)
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
            console=console,
        )
        raise typer.Exit(code=EXIT_AUTH)
    except IntegrityError:
        _emit_error(
            title="Memory integrity verification failed",
            category="SYS",
            stable_code="SYS-011",
            exit_code=EXIT_INTEGRITY,
            fix="run `matriosha vault verify --deep` to inspect corrupted entries",
            debug=f"memory_id={parent_id} phase=memory.decompress",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_INTEGRITY)
    except (VaultIntegrityError, OSError, ValueError) as exc:
        _emit_error(
            title="Local storage operation failed",
            category="STORE",
            stable_code="STORE-007",
            exit_code=EXIT_UNKNOWN,
            fix="check local memory files and vector index, then retry",
            debug=f"os_error={type(exc).__name__}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_UNKNOWN)
