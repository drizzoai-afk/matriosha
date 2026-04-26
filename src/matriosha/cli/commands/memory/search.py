"""`matriosha memory search` command."""

from __future__ import annotations

import typer

from .common import *


def _search_format_bytes(n: int) -> str:
    value = float(n)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "bytes":
                return f"{int(value):,} bytes"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{n:,} bytes"


def register(app: typer.Typer) -> None:
    @app.command("search")
    def search(
        ctx: typer.Context,
        query: str = typer.Argument(..., help="Semantic query to search memories."),
        k: int = typer.Option(10, "--k", min=1, help="Maximum number of nearest memories to retrieve."),
        threshold: float = typer.Option(0.0, "--threshold", help="Minimum cosine score to include."),
        tag: str | None = typer.Option(None, "--tag", help="Filter results by tag after ANN search."),
        json_output_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Search saved memories by meaning."""

        output = resolve_output(ctx, json_flag=json_output_flag)
        gctx = output.ctx
        json_output = gctx.json_output
        console = make_console()

        try:
            if threshold < -1.0 or threshold > 1.0:
                raise InvalidInput("--threshold must be between -1.0 and 1.0")

            cfg = load_config()
            profile = get_active_profile(cfg, gctx.profile)
            _require_managed_session_for_memory(profile, json_output=json_output, plain=gctx.plain, console=console)
            vault = Vault.unlock(profile.name, _resolve_passphrase(profile_name=profile.name, profile_mode=profile.mode, json_output=output.json))

            store = LocalStore(profile.name)
            existing_envelopes = store.list(limit=1)
            if not existing_envelopes:
                if json_output:
                    output.json(
                        {
                            "status": "ok",
                            "operation": "memory.search",
                            "data": {
                                "query": query,
                                "k": k,
                                "threshold": threshold,
                                "tag": tag,
                                "results": [],
                            },
                            "error": None,
                        }
                    )
                    raise typer.Exit(code=0)

                if gctx.plain:
                    typer.echo("no matching memories found")
                    raise typer.Exit(code=0)

                console.print(f'Found [bold]0[/bold] memories for "[cyan]{query}[/cyan]"')
                console.print(
                    f"Nothing to search yet. Save one with: [bold]matriosha --profile {profile.name} memory remember \"your note\"[/bold]"
                )
                raise typer.Exit(code=0)

            index = LocalVectorIndex(profile.name)
            embedder = get_default_embedder()

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
                        filename=getattr(env, "filename", None),
                        mime_type=getattr(env, "mime_type", None),
                        content_kind=getattr(env, "content_kind", None),
                    )
                    filename = getattr(env, "filename", None)
                    mime_type = getattr(env, "mime_type", None)
                    content_kind = getattr(env, "content_kind", None)
                    plaintext_bytes = getattr(env, "plaintext_bytes", None) or len(plaintext)

                    if content_kind == "binary" or filename:
                        preview_parts = []
                        if filename:
                            preview_parts.append(f"File: {filename}")
                        if mime_type:
                            preview_parts.append(f"Type: {mime_type}")
                        preview_parts.append(f"Size: {_search_format_bytes(int(plaintext_bytes))}")
                        preview = "\n".join(preview_parts)
                        semantic = {
                            "kind": content_kind or "file",
                            "filename": filename,
                            "mime_type": mime_type,
                            "preview": preview,
                            "metadata": {
                                "input_bytes": int(plaintext_bytes),
                                "blocks": len(getattr(env, "merkle_leaves", []) or []),
                            },
                            "warnings": list(semantic.get("warnings") or []),
                        }
                    else:
                        preview = str(semantic.get("preview") or "")[:80] or _preview_plaintext(plaintext, max_chars=80)
                else:
                    plaintext_bytes = getattr(env, "plaintext_bytes", None) or 0
                    preview = "Unavailable: encrypted memory failed integrity checks"
                    semantic = {
                        "kind": "corrupted",
                        "filename": getattr(env, "filename", None),
                        "mime_type": getattr(env, "mime_type", None),
                        "preview": preview,
                        "metadata": {
                            "input_bytes": int(plaintext_bytes),
                            "blocks": len(getattr(env, "merkle_leaves", []) or []),
                        },
                        "warnings": [],
                    }

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

            result_word = "memory" if len(rows) == 1 else "memories"
            console.print(f'Found [bold]{len(rows)}[/bold] {result_word} for "[cyan]{query}[/cyan]"')

            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("#", justify="right", width=3)
            table.add_column("Memory", max_width=20, overflow="ellipsis")
            table.add_column("Match", justify="right", width=7)
            table.add_column("When", max_width=19, overflow="ellipsis")
            table.add_column("Tags", max_width=22, overflow="ellipsis")
            table.add_column("Preview", ratio=1, overflow="fold")

            for row in rows:
                table.add_row(
                    str(row["rank"]),
                    _short(str(row["memory_id"]), head=8, tail=6),
                    f"{max(0.0, min(1.0, float(row['score']))) * 100:.0f}%",
                    str(row["created_at"]).replace("T", " ").replace("Z", " UTC").split(".")[0],
                    " ".join(f"#{t}" for t in row["tags"]) if row["tags"] else "-",
                    str(row["preview"]),
                )

            console.print(table)
            if rows:
                first_id = str(rows[0]["memory_id"])
                console.print(f"Recall top result: [bold]matriosha --profile {profile.name} memory recall {first_id}[/bold]")
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
                stable_code="STORE-005",
                exit_code=EXIT_UNKNOWN,
                fix="check local memory files and vector index, then retry",
                debug=f"os_error={type(exc).__name__}",
                json_output=json_output,
                plain=gctx.plain,
                console=console,
            )
            raise typer.Exit(code=EXIT_UNKNOWN)
