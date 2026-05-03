"""`matriosha memory index` command."""

from __future__ import annotations

from typing import cast

import typer

from .common import (
    EXIT_AUTH,
    EXIT_INTEGRITY,
    EXIT_UNKNOWN,
    LocalStore,
    Vault,
    VaultIntegrityError,
    _SEMANTIC_SEARCH_TEXT_LIMIT,
    _decode_with_corruption_handling,
    _emit_error,
    _is_missing_vault_error,
    _resolve_passphrase,
    _semantic_from_plaintext,
    get_active_profile,
    get_default_embedder,
    load_config,
    make_console,
    resolve_output,
)
from matriosha.core.local_vectors import existing_vector_ids, get_local_vector_index, vector_count


def _text_for_embedding(plaintext: bytes, env, memory_id: str) -> str:
    semantic = _semantic_from_plaintext(
        plaintext=plaintext,
        envelope_tags=env.tags,
        memory_id=memory_id,
        text_limit=_SEMANTIC_SEARCH_TEXT_LIMIT,
        filename=getattr(env, "filename", None),
        mime_type=getattr(env, "mime_type", None),
        content_kind=getattr(env, "content_kind", None),
    )
    text = str(semantic.get("text") or semantic.get("preview") or "").strip()
    if text:
        return text
    return plaintext.decode("utf-8", errors="replace").strip()


def build_missing_local_vectors(
    *,
    profile_name: str,
    profile_mode: str,
    data_key: bytes,
    limit: int | None = None,
) -> dict[str, int]:
    """Build missing local vectors after append-only memory writes."""

    store = LocalStore(profile_name, data_key=data_key)
    index = get_local_vector_index(profile_name, data_key=data_key)
    embedder = get_default_embedder()
    existing_ids = existing_vector_ids(index)
    indexed = 0
    skipped = 0
    failed = 0

    for memory_id in sorted(store.index_metadata().keys()):
        if memory_id in existing_ids:
            skipped += 1
            continue
        if limit is not None and indexed >= limit:
            break
        try:
            env, b64_payload = store.get(memory_id)
            plaintext, _, _ = _decode_with_corruption_handling(
                env=env,
                b64_payload=b64_payload,
                key=data_key,
                profile_mode=profile_mode,
                memory_id=memory_id,
                store=store,
            )
            if plaintext is None:
                failed += 1
                continue
            text = _text_for_embedding(plaintext, env, memory_id)
            if not text:
                failed += 1
                continue
            index.add(memory_id, embedder.embed(text), entry_type="memory", is_active=True)
            existing_ids.add(memory_id)
            indexed += 1
        except Exception:  # noqa: BLE001
            failed += 1

    if indexed:
        index.save()
    return {
        "indexed": indexed,
        "skipped": skipped,
        "failed": failed,
        "total_vectors": vector_count(index),
    }


def register(app: typer.Typer) -> None:
    @app.command("index")
    def index(
        ctx: typer.Context,
        limit: int | None = typer.Option(None, "--limit", min=1, help="Maximum missing memories to index."),
        json_output_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Build missing local semantic vectors for append-only memories."""

        output = resolve_output(ctx, json_flag=json_output_flag)
        gctx = output.ctx
        json_output = gctx.json_output
        console = make_console()

        try:
            cfg = load_config()
            profile = get_active_profile(cfg, gctx.profile)
            vault = Vault.unlock(
                profile.name,
                _resolve_passphrase(profile_name=profile.name, profile_mode=profile.mode, json_output=json_output),
            )
            stats = build_missing_local_vectors(
                profile_name=profile.name,
                profile_mode=cast(str, profile.mode),
                data_key=vault.data_key,
                limit=limit,
            )
            if json_output:
                output.json({"status": "ok", "operation": "memory.index", "data": stats, "error": None})
                return
            if gctx.plain:
                typer.echo(
                    f"indexed={stats['indexed']} skipped={stats['skipped']} "
                    f"failed={stats['failed']} total_vectors={stats['total_vectors']}"
                )
                return
            console.print(
                "[green]Local vector index updated[/green] "
                f"indexed={stats['indexed']} skipped={stats['skipped']} "
                f"failed={stats['failed']} total_vectors={stats['total_vectors']}"
            )
            return
        except (VaultIntegrityError, OSError, ValueError) as exc:
            if _is_missing_vault_error(exc):
                _emit_error(
                    title="Vault not initialized",
                    category="AUTH",
                    stable_code="AUTH-001",
                    exit_code=EXIT_AUTH,
                    fix="Run: matriosha vault init",
                    debug="provider=local_vault missing_vault",
                    json_output=json_output,
                    plain=gctx.plain,
                    console=console,
                )
                raise typer.Exit(code=EXIT_AUTH)
            _emit_error(
                title="Local vector indexing failed",
                category="STORE",
                stable_code="STORE-014",
                exit_code=EXIT_UNKNOWN,
                fix="check local memory files and retry `matriosha memory index`",
                debug=f"detail={type(exc).__name__}: {exc}",
                json_output=json_output,
                plain=gctx.plain,
                console=console,
            )
            raise typer.Exit(code=EXIT_UNKNOWN)
        except Exception as exc:  # noqa: BLE001
            _emit_error(
                title="Local vector indexing failed",
                category="SYS",
                stable_code="SYS-015",
                exit_code=EXIT_INTEGRITY,
                fix="run `matriosha vault verify --deep`, then retry indexing",
                debug=f"detail={type(exc).__name__}: {exc}",
                json_output=json_output,
                plain=gctx.plain,
                console=console,
            )
            raise typer.Exit(code=EXIT_INTEGRITY)
