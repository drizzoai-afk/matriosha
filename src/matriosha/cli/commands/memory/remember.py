"""`matriosha memory remember` command."""

from __future__ import annotations

import mimetypes
import sys

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
    ManagedBackupError,
    ManagedBackupStore,
    Path,
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
    get_default_embedder,
    load_config,
    make_console,
    resolve_output,
)


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
            payload = _resolve_payload_bytes(text=text, file_path=file_path, stdin_input=stdin_input)
            validated_tags = _validate_tags(tags)

            filename = file_path.name if file_path is not None else None
            guessed_mime = mimetypes.guess_type(filename or "")[0] if filename else None
            if file_path is not None:
                mime_type = guessed_mime or "application/octet-stream"
                content_kind = "text" if mime_type.startswith("text/") else "binary"
            else:
                mime_type = "text/plain"
                content_kind = "text"

            cfg = load_config()
            profile = get_active_profile(cfg, gctx.profile)
            active_mode = profile.mode
            _require_managed_session_for_memory(profile, json_output=json_output, plain=gctx.plain, console=console)

            if stdin_input and (not json_output) and (not gctx.plain):
                console.print("[accent]● READING STDIN[/accent]")

            vault = Vault.unlock(profile.name, _resolve_passphrase(profile_name=profile.name, profile_mode=profile.mode, json_output=json_output))
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

            store = LocalStore(profile.name)
            embedder = get_default_embedder()
            if content_kind == "text":
                embedding_input = payload[: 4 * 1024].decode("utf-8", errors="replace")
            else:
                embedding_input = f"Binary file memory: {filename or 'unnamed file'} ({mime_type}, {len(payload)} bytes)"
            embedding = embedder.embed(embedding_input)
            path = store.put(env, b64_payload, embedding=embedding)
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

            backup_key: str | None = None
            backup_warning: str | None = None
            if active_mode == "managed":
                try:
                    memory_package = sys.modules[__package__]
                    backup_store_cls = getattr(memory_package, "ManagedBackupStore", ManagedBackupStore)
                    backup_key = backup_store_cls().upload_backup(env.memory_id, b64_payload)
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
