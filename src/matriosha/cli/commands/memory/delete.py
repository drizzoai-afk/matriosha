"""`matriosha memory delete` command."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import typer

from .common import *


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
        store = LocalStore(profile.name)

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
            index = LocalVectorIndex(profile.name)
            embedder = get_default_embedder()
            query_vec = embedder.embed(query)
            for candidate_id, score in index.search(query_vec, k=limit, entry_types={"memory", "parent"}):
                if score >= threshold:
                    target_ids.append(candidate_id)

        is_bulk = memory_id is None

        if is_bulk and target_ids and not yes:
            if json_output:
                raise InvalidInput("bulk delete requires --yes")
            confirmed = Confirm.ask(f"Delete {len(target_ids)} memories?", default=False)
            if not confirmed:
                raise typer.Exit(code=0)
        elif memory_id is not None and not yes and not json_output:
            confirmed = Confirm.ask(f"Delete memory '{memory_id}'?", default=False)
            if not confirmed:
                raise typer.Exit(code=0)

        deleted_ids: list[str] = []
        for target_id in target_ids:
            removed = store.delete(target_id)
            if removed:
                deleted_ids.append(target_id)

        deleted_count = len(deleted_ids)
        if deleted_count:
            _schedule_managed_auto_sync_if_enabled(
                profile.name,
                profile_mode=profile.mode,
                auto_sync_enabled=cfg.managed.auto_sync,
                managed_endpoint=profile.managed_endpoint,
            )

        result_data = {
            "selector": selector,
            "memory_id": memory_id,
            "deleted": deleted_count,
            "memory_ids": deleted_ids,
        }

        if json_output:
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
            rows = [
                ("selector", str(selector["type"])),
                ("deleted", str(deleted_count)),
            ]
            if memory_id is not None:
                rows.insert(1, ("id", _short(memory_id, head=12, tail=6)))
            _render_panel(
                "MEMORY DELETE",
                rows,
                status_chip="✓ SUCCESS" if deleted_count else "⚠ NOOP",
                style="success" if deleted_count else "yellow",
                console=console,
            )

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
