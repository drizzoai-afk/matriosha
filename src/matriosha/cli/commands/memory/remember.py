"""`matriosha memory remember` command."""

from __future__ import annotations

import mimetypes
import os
from typing import Any

import typer

from .common import (
    AuthError,
    EXIT_AUTH,
    EXIT_INTEGRITY,
    EXIT_UNKNOWN,
    EXIT_USAGE,
    IntegrityError,
    InvalidInput,
    LocalStore,
    Path,
    _MAX_MEMORY_BYTES,
    Vault,
    VaultIntegrityError,
    _audit_memory_event,
    _emit_error,
    _is_missing_vault_error,
    _render_panel,
    _require_managed_session_for_memory,
    _resolve_passphrase,
    _resolve_payload_bytes,
    _schedule_managed_auto_sync_if_enabled,
    _short,
    _validate_tags,
    encode_envelope,
    get_active_profile,
    load_config,
    make_console,
    resolve_output,
)
_INBOX_PROCESSED_DIRNAME = ".processed"
_INBOX_SKIP_SUFFIXES = (".tmp", ".part", ".partial", ".swp", ".crdownload")


def _inbox_candidate_paths(inbox_dir: Path) -> list[Path]:
    if not inbox_dir.exists() or not inbox_dir.is_dir():
        return []

    candidates: list[Path] = []
    for path in sorted(inbox_dir.iterdir(), key=lambda item: item.name):
        if path.name.startswith("."):
            continue
        if path.name.endswith(_INBOX_SKIP_SUFFIXES):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        candidates.append(path)
    return candidates


def _move_to_processed(path: Path, processed_dir: Path) -> None:
    processed_dir.mkdir(parents=True, exist_ok=True)
    target = processed_dir / path.name
    if target.exists():
        stem = path.stem
        suffix = path.suffix
        counter = 1
        while True:
            candidate = processed_dir / f"{stem}-{counter}{suffix}"
            if not candidate.exists():
                target = candidate
                break
            counter += 1
    path.replace(target)


def _read_inbox_file(path: Path) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    fd = os.open(path, flags)
    try:
        with os.fdopen(fd, "rb") as f:
            payload = f.read()
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        raise

    if len(payload) > _MAX_MEMORY_BYTES:
        raise InvalidInput("input exceeds max size of 50 MiB")
    return payload


def _store_inbox_file(
    *,
    path: Path,
    vault,
    store: LocalStore,
    profile_name: str,
    profile_mode: str,
) -> str:
    payload = _read_inbox_file(path)
    filename = path.name
    guessed_mime = mimetypes.guess_type(filename)[0]
    mime_type = guessed_mime or "application/octet-stream"
    content_kind = "text" if mime_type.startswith("text/") else "binary"

    env, b64_payload = encode_envelope(
        payload,
        vault.data_key,
        mode=profile_mode,
        tags=["inbox"],
        source="cli",
        filename=filename,
        mime_type=mime_type,
        content_kind=content_kind,
    )
    store.put(env, b64_payload, embedding=None)
    _audit_memory_event(
        profile_name=profile_name,
        profile_mode=profile_mode,
        action="memory.inbox",
        target_id=env.memory_id,
        outcome="success",
        metadata={
            "bytes": len(payload),
            "blocks": len(env.merkle_leaves),
            "tags": ["inbox"],
            "content_kind": content_kind,
            "mime_type": mime_type,
            "filename_present": True,
            "filename": filename,
        },
    )
    return env.memory_id


def _drain_inbox(
    *,
    store: LocalStore,
    vault,
    profile_name: str,
    profile_mode: str,
) -> list[str]:
    inbox_dir = store.root / "inbox"
    processed_dir = inbox_dir / _INBOX_PROCESSED_DIRNAME
    memory_ids: list[str] = []

    for path in _inbox_candidate_paths(inbox_dir):
        try:
            memory_id = _store_inbox_file(
                path=path,
                vault=vault,
                store=store,
                profile_name=profile_name,
                profile_mode=profile_mode,
            )
            _move_to_processed(path, processed_dir)
            memory_ids.append(memory_id)
        except InvalidInput:
            continue
        except OSError:
            continue

    return memory_ids



def register(app: typer.Typer) -> None:
    @app.command("remember")
    def remember(
        ctx: typer.Context,
        text: str | None = typer.Argument(None, help="Text to store as encrypted memory."),
        file_path: Path | None = typer.Option(None, "--file", help="Read memory payload from file."),
        tags: list[str] = typer.Option([], "--tag", help="Attach one or more lowercase tags."),
        stdin_input: bool = typer.Option(False, "--stdin", help="Read memory payload from stdin."),
        json_output_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Save a new encrypted memory."""

        output = resolve_output(ctx, json_flag=json_output_flag)
        gctx = output.ctx
        json_output = gctx.json_output
        console = make_console()

        try:
            validated_tags = _validate_tags(tags)

            cfg = load_config()
            profile = get_active_profile(cfg, gctx.profile)
            active_mode = profile.mode
            _require_managed_session_for_memory(profile, json_output=json_output, plain=gctx.plain, console=console)

            if stdin_input and (not json_output) and (not gctx.plain):
                console.print("[accent]● READING STDIN[/accent]")

            vault = Vault.unlock(profile.name, _resolve_passphrase(profile_name=profile.name, profile_mode=profile.mode, json_output=json_output))
            store = LocalStore(profile.name, data_key=vault.data_key)
            inbox_memory_ids = _drain_inbox(
                store=store,
                vault=vault,
                profile_name=profile.name,
                profile_mode=active_mode,
            )

            has_explicit_input = text is not None or file_path is not None or stdin_input
            if not has_explicit_input:
                if not inbox_memory_ids:
                    raise InvalidInput("provide exactly one source")
                _schedule_managed_auto_sync_if_enabled(
                    profile.name,
                    profile_mode=active_mode,
                    auto_sync_enabled=cfg.managed.auto_sync,
                    managed_endpoint=profile.managed_endpoint,
                )
                result: dict[str, Any] = {
                    "memory_id": None,
                    "bytes": 0,
                    "blocks": 0,
                    "merkle_root": None,
                    "tags": [],
                    "path": None,
                    "backup_key": None,
                    "backup_warning": None,
                    "inbox_ingested": len(inbox_memory_ids),
                    "inbox_memory_ids": inbox_memory_ids,
                }
                if json_output:
                    output.json({"status": "ok", "operation": "memory.remember", "data": result, "error": None})
                elif gctx.plain:
                    typer.echo(f"inbox ingested: {len(inbox_memory_ids)}")
                else:
                    _render_panel(
                        "INBOX INGESTED",
                        [("files", str(len(inbox_memory_ids)))],
                        status_chip="✓ SUCCESS",
                        style="success",
                        console=console,
                    )
                return

            payload = _resolve_payload_bytes(text=text, file_path=file_path, stdin_input=stdin_input)

            filename = file_path.name if file_path is not None else None
            guessed_mime = mimetypes.guess_type(filename or "")[0] if filename else None
            if file_path is not None:
                mime_type = guessed_mime or "application/octet-stream"
                content_kind = "text" if mime_type.startswith("text/") else "binary"
            else:
                mime_type = "text/plain"
                content_kind = "text"

            env, b64_payload = encode_envelope(
                payload,
                vault.data_key,
                mode=active_mode,
                tags=validated_tags,
                source="cli",
                filename=filename,
                mime_type=mime_type,
                content_kind=content_kind,
            )

            memory_path = store.put(env, b64_payload, embedding=None)
            _audit_memory_event(
                profile_name=profile.name,
                profile_mode=active_mode,
                action="memory.remember",
                target_id=env.memory_id,
                outcome="success",
                metadata={
                    "bytes": len(payload),
                    "blocks": len(env.merkle_leaves),
                    "tags": validated_tags,
                    "content_kind": content_kind,
                    "mime_type": mime_type,
                    "filename_present": filename is not None,
                },
            )
            _schedule_managed_auto_sync_if_enabled(
                profile.name,
                profile_mode=active_mode,
                auto_sync_enabled=cfg.managed.auto_sync,
                managed_endpoint=profile.managed_endpoint,
            )

            backup_key: str | None = None
            backup_warning: str | None = None

            result = {
                "memory_id": env.memory_id,
                "bytes": len(payload),
                "blocks": len(env.merkle_leaves),
                "merkle_root": env.merkle_root,
                "tags": validated_tags,
                "path": str(memory_path),
                "backup_key": backup_key,
                "backup_warning": backup_warning,
                "inbox_ingested": len(inbox_memory_ids),
                "inbox_memory_ids": inbox_memory_ids,
            }

            if json_output:
                output.json({"status": "ok", "operation": "memory.remember", "data": result, "error": None})
            elif gctx.plain:
                typer.echo(f"memory stored: {env.memory_id}")
                typer.echo(f"bytes: {len(payload)}")
                typer.echo(f"blocks: {len(env.merkle_leaves)}")
                typer.echo(f"merkle_root: {env.merkle_root}")
                typer.echo(f"tags: {', '.join(validated_tags) if validated_tags else '-'}")
                if inbox_memory_ids:
                    typer.echo(f"inbox ingested: {len(inbox_memory_ids)}")
            else:
                rendered_tags = " ".join(f"#{tag}" for tag in validated_tags) if validated_tags else "-"
                rows = [
                    ("id", _short(env.memory_id, head=12, tail=6)),
                    ("bytes", f"{len(payload):,}"),
                    ("blocks", str(len(env.merkle_leaves))),
                    ("merkle", _short(env.merkle_root, head=12, tail=6)),
                    ("tags", rendered_tags),
                ]
                if inbox_memory_ids:
                    rows.append(("inbox", str(len(inbox_memory_ids))))
                _render_panel(
                    "MEMORY STORED",
                    rows,
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
                fix="Use the correct vault passphrase and try again.",
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
            if _is_missing_vault_error(exc):
                _emit_error(
                    title="Vault not initialized",
                    category="AUTH",
                    stable_code="AUTH-003",
                    exit_code=EXIT_AUTH,
                    fix="Run: matriosha vault init",
                    debug=f"profile={profile.name} reason=missing_vault_material",
                    json_output=json_output,
                    plain=gctx.plain,
                    console=console,
                )
                raise typer.Exit(code=EXIT_AUTH) from None
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
        except typer.Exit:
            raise
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
