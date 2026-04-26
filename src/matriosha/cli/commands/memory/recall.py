"""`matriosha memory recall` command."""

from __future__ import annotations

import typer

from .common import *


def register(app: typer.Typer) -> None:
    @app.command("recall")
    def recall(
        ctx: typer.Context,
        memory_id: str = typer.Argument(..., help="Memory identifier to read."),
        show_metadata: bool = typer.Option(False, "--show-metadata", help="Include envelope metadata JSON."),
        out: Path | None = typer.Option(None, "--out", help="Write the memory to a file instead of printing it. Use this for files or large memories."),
        json_output_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Read a saved memory and verify its integrity."""

        output = resolve_output(ctx, json_flag=json_output_flag)
        gctx = output.ctx
        json_output = gctx.json_output
        console = make_console()

        try:
            cfg = load_config()
            profile = get_active_profile(cfg, gctx.profile)
            _require_managed_session_for_memory(profile, json_output=json_output, plain=gctx.plain, console=console)
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

            if plaintext is not None:
                semantic = _semantic_from_plaintext(
                    plaintext=plaintext,
                    envelope_tags=env.tags,
                    memory_id=env.memory_id,
                    filename=getattr(env, "filename", None),
                    mime_type=getattr(env, "mime_type", None),
                    content_kind=getattr(env, "content_kind", None),
                )
            else:
                semantic = {
                    "kind": "corrupted",
                    "filename": getattr(env, "filename", None),
                    "mime_type": getattr(env, "mime_type", None),
                    "preview": "Unavailable: encrypted memory failed integrity checks",
                    "metadata": {
                        "input_bytes": int(getattr(env, "plaintext_bytes", None) or 0),
                        "blocks": len(getattr(env, "merkle_leaves", []) or []),
                    },
                    "warnings": [],
                }

            if integrity_warning:
                semantic_warnings = list(semantic.get("warnings") or [])
                semantic_warnings.append(integrity_warning)
                semantic["warnings"] = semantic_warnings

            if out is not None and plaintext is not None:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(plaintext)

            metadata_json = json.dumps(asdict(env), separators=(",", ":"))

            if json_output:
                plaintext_size = len(plaintext) if plaintext is not None else 0
                content_kind = getattr(env, "content_kind", None)
                filename = getattr(env, "filename", None)
                mime_type = getattr(env, "mime_type", None)
                unsafe_for_json = (
                    plaintext is None
                    or out is not None
                    or plaintext_size > 65536
                    or b"\x00" in plaintext
                    or content_kind == "binary"
                )

                if unsafe_for_json:
                    preview_parts = []
                    if filename:
                        preview_parts.append(f"File: {filename}")
                    if mime_type:
                        preview_parts.append(f"Type: {mime_type}")
                    preview_parts.append(f"Size: {plaintext_size:,} bytes")
                    safe_preview = "\n".join(preview_parts)

                    semantic = {
                        "kind": content_kind or ("file" if filename else "binary"),
                        "filename": filename,
                        "mime_type": mime_type,
                        "preview": safe_preview,
                        "metadata": {
                            "input_bytes": plaintext_size,
                            "blocks": len(getattr(env, "merkle_leaves", []) or []),
                        },
                        "warnings": list(semantic.get("warnings") or []),
                    }

                payload = {
                    "status": "ok",
                    "operation": "memory.recall",
                    "data": {
                        "memory_id": env.memory_id,
                        "bytes": plaintext_size,
                        "out": str(out) if out and plaintext is not None else None,
                        "printed": not unsafe_for_json,
                        "reason": "Large or binary content" if unsafe_for_json and plaintext is not None and out is None else None,
                        "suggested_out": (filename or "memory-output.bin") if unsafe_for_json and plaintext is not None and out is None else None,
                        "plaintext_b64": None
                        if unsafe_for_json
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
                    typer.echo(f"memory: {env.memory_id}")
                    typer.echo(f"size: {len(plaintext):,} bytes")
                    typer.echo(f"saved_to: {out}")
                    if integrity_warning:
                        typer.echo(f"WARNING: {integrity_warning}")
                    if show_metadata:
                        typer.echo(metadata_json)
                else:
                    _render_panel(
                        "MEMORY SAVED TO FILE",
                        [
                            ("Memory", _short(env.memory_id, head=12, tail=6)),
                            ("Size", f"{len(plaintext):,} bytes"),
                            ("Saved to", str(out)),
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

            suggested_out = getattr(env, "filename", None) or "memory-output.bin"

            if plaintext is not None:
                unsafe_for_terminal = len(plaintext) > 65536 or b"\x00" in plaintext
                if unsafe_for_terminal:
                    if gctx.plain:
                        typer.echo(f"memory: {env.memory_id}")
                        typer.echo(f"size: {len(plaintext):,} bytes")
                        typer.echo("not_printed: memory is large or binary")
                        typer.echo(f"save_with: matriosha --profile {profile.name} memory recall {env.memory_id} --out {suggested_out}")
                    else:
                        _render_panel(
                            "MEMORY NOT PRINTED",
                            [
                                ("Memory", _short(env.memory_id, head=12, tail=6)),
                                ("Size", f"{len(plaintext):,} bytes"),
                                ("Reason", "Large or binary content"),
                            ],
                            status_chip="ⓘ USE --OUT",
                            style="warning",
                            console=console,
                        )
                        console.print("Save it to a file instead:")
                        typer.echo(f"  matriosha --profile {profile.name} memory recall {env.memory_id} --out {suggested_out}")
                    if integrity_warning:
                        if gctx.plain:
                            typer.echo(f"WARNING: {integrity_warning}")
                        else:
                            console.print(f"[warning]WARNING:[/warning] {integrity_warning}")
                    if show_metadata:
                        typer.echo(metadata_json)
                    raise typer.Exit(code=0)

                if show_metadata:
                    sys.stdout.buffer.write(plaintext)
                    if not plaintext.endswith(b"\n"):
                        sys.stdout.buffer.write(b"\n")
                    typer.echo(metadata_json)
                else:
                    sys.stdout.buffer.write(plaintext)
                    if not plaintext.endswith(b"\n"):
                        sys.stdout.buffer.write(b"\n")
            else:
                if gctx.plain:
                    typer.echo(f"WARNING: {integrity_warning}")
                else:
                    console.print(f"[warning]WARNING:[/warning] {integrity_warning}")
            raise typer.Exit(code=0)

        except AuthError as exc:
            if _is_missing_vault_error(exc):
                _emit_error(
                    title="Vault not initialized",
                    category="AUTH",
                    stable_code="AUTH-001",
                    exit_code=EXIT_AUTH,
                    fix="Run: matriosha vault init",
                    debug=f"profile={profile.name} provider=local_vault missing_vault",
                    json_output=json_output,
                    plain=gctx.plain,
                    console=console,
                )
                raise typer.Exit(code=EXIT_AUTH) from None
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
            if _is_missing_vault_error(exc):
                _emit_error(
                    title="Vault not initialized",
                    category="AUTH",
                    stable_code="AUTH-001",
                    exit_code=EXIT_AUTH,
                    fix="Run: matriosha vault init",
                    debug=f"profile={profile.name} provider=local_vault missing_vault",
                    json_output=json_output,
                    plain=gctx.plain,
                    console=console,
                )
                raise typer.Exit(code=EXIT_AUTH)

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
