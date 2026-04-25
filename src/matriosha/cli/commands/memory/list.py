"""`matriosha memory list` command."""

from __future__ import annotations

import typer

from .common import *


def register(app: typer.Typer) -> None:
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
