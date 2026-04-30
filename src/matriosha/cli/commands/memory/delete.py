"""`matriosha memory delete` command."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import typer

from .common import (
    AuthError,
    EXIT_AUTH,
    EXIT_UNKNOWN,
    EXIT_USAGE,
    InvalidInput,
    LocalStore,
    LocalVectorIndex,
    Vault,
    VaultIntegrityError,
    _audit_memory_event,
    _emit_error,
    _is_missing_vault_error,
    _render_panel,
    _require_managed_session_for_memory,
    _resolve_passphrase,
    _schedule_managed_auto_sync_if_enabled,
    _short,
    get_active_profile,
    get_default_embedder,
    json,
    load_config,
    make_console,
    resolve_output,
)


def delete(
    ctx: typer.Context,
    memory_id: str | None = typer.Argument(None, help="Memory identifier to delete."),
    older_than: int | None = typer.Option(None, "--older-than", min=1, help="Bulk delete memories older than this many days."),
    query: str | None = typer.Option(None, "--query", help="Bulk delete memories semantically matching this query."),
    threshold: float = typer.Option(0.35, "--threshold", help="Minimum cosine score for --query bulk delete."),
    limit: int = typer.Option(100, "--limit", min=1, help="Maximum memories to consider for bulk delete."),
    yes: bool = typer.Option(False, "--yes", help="Delete without confirmation prompt."),
    strict: bool = typer.Option(False, "--strict", help="Exit 2 when memory id does not exist."),
    json_output_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
) -> None:
    """Delete one memory or delete memories by age or search."""

    output = resolve_output(ctx, json_flag=json_output_flag)
    gctx = output.ctx
    json_output = gctx.json_output
    console = make_console()

    try:
        if threshold < -1.0 or threshold > 1.0:
            raise InvalidInput("--threshold must be between -1.0 and 1.0")

        selectors = [memory_id is not None, older_than is not None, query is not None]
        if sum(selectors) != 1:
            raise InvalidInput("provide exactly one delete selector: MEMORY_ID, --older-than, or --query")

        cfg = load_config()
        profile = get_active_profile(cfg, gctx.profile)
        _require_managed_session_for_memory(profile, json_output=json_output, plain=gctx.plain, console=console)
        vault = Vault.unlock(profile.name, _resolve_passphrase(profile_name=profile.name, profile_mode=profile.mode, json_output=json_output))
        store = LocalStore(profile.name, data_key=vault.data_key)

        target_ids: list[str] = []
        selector: dict[str, object]

        if memory_id is not None:
            target_ids = [memory_id]
            selector = {"type": "memory_id", "memory_id": memory_id}
        elif older_than is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=older_than)
            selector = {
                "type": "older_than",
                "days": older_than,
                "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
            }
            for env in store.list(limit=limit):
                created_at = _parse_memory_created_at(env.created_at)
                if created_at < cutoff:
                    target_ids.append(env.memory_id)
        else:
            assert query is not None
            selector = {"type": "query", "query": query, "threshold": threshold, "limit": limit}
            index = LocalVectorIndex(profile.name, data_key=vault.data_key)
            embedder = get_default_embedder()
            query_vec = embedder.embed(query)
            for candidate_id, score in index.search(query_vec, k=limit, entry_types={"memory", "parent"}):
                if score >= threshold:
                    target_ids.append(candidate_id)

        is_bulk = memory_id is None

        if is_bulk and target_ids and not yes:
            if json_output:
                raise InvalidInput("bulk delete requires --yes")
            console.print()
            console.print(f"[bold yellow]Delete {len(target_ids)} memories?[/bold yellow]")
            console.print("[yellow]This cannot be undone.[/yellow]")
            answer = typer.prompt("Type y to delete, or press Enter to cancel", default="", show_default=False)
            if answer.strip().lower() not in {"y", "yes"}:
                console.print("Canceled. No memories were deleted.")
                raise typer.Exit(code=0)
        elif memory_id is not None and not yes and not json_output:
            preview_env = None
            try:
                preview_record = store.get(memory_id)
                preview_env = preview_record[0] if isinstance(preview_record, tuple) else preview_record
            except Exception:
                preview_env = None

            console.print()
            console.print("[bold yellow]Delete this memory?[/bold yellow]")
            if preview_env is not None:
                console.print(f"ID: {_short(preview_env.memory_id, head=12, tail=6)}")
                console.print(f"When: {preview_env.created_at}")
                tags = getattr(preview_env, "tags", []) or []
                if tags:
                    console.print("Tags: " + " ".join(f"#{tag}" for tag in tags))
                size = getattr(preview_env, "plaintext_bytes", None)
                console.print(f"Size: {size:,} bytes" if isinstance(size, int) else "Size: unknown")
            else:
                console.print(f"ID: {_short(memory_id, head=12, tail=6)}")
            console.print("[yellow]This cannot be undone.[/yellow]")
            answer = typer.prompt("Type y to delete, or press Enter to cancel", default="", show_default=False)
            if answer.strip().lower() not in {"y", "yes"}:
                console.print("Canceled. No memories were deleted.")
                raise typer.Exit(code=0)

        deleted_ids: list[str] = []
        for target_id in target_ids:
            removed = store.delete(target_id)
            if removed:
                deleted_ids.append(target_id)

        deleted_count = len(deleted_ids)
        if deleted_count:
            _audit_memory_event(
                profile_name=profile.name,
                profile_mode=profile.mode,
                action="memory.delete",
                target_id=memory_id if memory_id is not None and deleted_count == 1 else None,
                outcome="success",
                metadata={
                    "selector": selector,
                    "deleted_count": deleted_count,
                    "bulk": is_bulk,
                },
            )
            _schedule_managed_auto_sync_if_enabled(
                profile.name,
                profile_mode=profile.mode,
                auto_sync_enabled=cfg.managed.auto_sync,
                managed_endpoint=profile.managed_endpoint,
                managed_vector_mode=cfg.managed.vector_mode,
            )

        result_data = {
            "selector": selector,
            "memory_id": memory_id,
            "deleted": deleted_count,
            "memory_ids": deleted_ids,
        }

        if json_output:
            if strict and memory_id is not None and deleted_count == 0:
                typer.echo(
                    json.dumps(
                        {
                            "status": "error",
                            "operation": "memory.delete",
                            "data": result_data,
                            "error": {
                                "category": "VAL",
                                "code": "VAL-404",
                                "message": "Memory not found",
                                "fix": "run `matriosha memory list` and retry with a valid memory id",
                            },
                        }
                    )
                )
            else:
                typer.echo(
                    json.dumps(
                        {
                            "status": "ok",
                            "operation": "memory.delete",
                            "data": result_data,
                            "error": None,
                        }
                    )
                )
        elif gctx.plain:
            typer.echo(f"deleted: {deleted_count}")
            for deleted_id in deleted_ids:
                typer.echo(deleted_id)
        else:
            if memory_id is not None:
                rows = [
                    ("id", _short(memory_id, head=12, tail=6)),
                    ("deleted", "1 memory" if deleted_count == 1 else "0 memories"),
                ]
                title = "MEMORY DELETED" if deleted_count else "DELETE MEMORY"
            else:
                rows = [
                    ("matched", str(len(target_ids))),
                    ("deleted", f"{deleted_count} memories"),
                ]
                title = "MEMORIES DELETED" if deleted_count else "NO MEMORIES DELETED"

            if deleted_count:
                console.print()
                console.print("[bold green]✓ Memory deleted[/bold green]")
                for label, value in rows:
                    console.print(f"{label}: {value}")
            else:
                _render_panel(
                    title,
                    rows,
                    status_chip="⚠ NOT FOUND",
                    style="yellow",
                    console=console,
                )
                if memory_id is not None:
                    console.print()
                    console.print("No memory was deleted.")
                    console.print(f"Check available memories with: matriosha --profile {profile.name} memory list")

        if strict and memory_id is not None and deleted_count == 0:
            raise typer.Exit(code=EXIT_USAGE)
        raise typer.Exit(code=0)

    except InvalidInput as exc:
        _emit_error(
            title="Invalid delete input",
            category="VAL",
            stable_code="VAL-004",
            exit_code=EXIT_USAGE,
            fix="provide exactly one valid delete selector and pass --yes for bulk deletes",
            debug=f"detail={exc}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_USAGE)
    except AuthError as exc:
        _emit_error(
            title="Vault unlock failed",
            category="AUTH",
            stable_code="AUTH-002",
            exit_code=EXIT_AUTH,
            fix="Use the correct vault passphrase and try again.",
            debug=f"provider=local_vault {exc}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_AUTH)
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
            stable_code="STORE-004",
            exit_code=EXIT_UNKNOWN,
            fix="check local memory files and retry",
            debug=f"os_error={type(exc).__name__}",
            json_output=json_output,
            plain=gctx.plain,
            console=console,
        )
        raise typer.Exit(code=EXIT_UNKNOWN)


def _parse_memory_created_at(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def register(app: typer.Typer) -> None:
    app.command("delete")(delete)
