"""`matriosha memory list` command."""

from __future__ import annotations

import typer
from typing import cast

from .common import (
    AuthError,
    EXIT_AUTH,
    EXIT_UNKNOWN,
    EXIT_USAGE,
    InvalidInput,
    LocalStore,
    Vault,
    VaultIntegrityError,
    _emit_error,
    _is_missing_vault_error,
    _memory_summary_dict,
    _parse_iso8601,
    _require_managed_session_for_memory,
    _resolve_passphrase,
    _short,
    get_active_profile,
    load_config,
    make_console,
    resolve_output,
)


def register(app: typer.Typer) -> None:
    @app.command("list")
    def list_memories(
        ctx: typer.Context,
        tag: str | None = typer.Option(None, "--tag", help="Filter by one tag value."),
        limit: int = typer.Option(
            50, "--limit", min=1, help="Maximum rows to return (default 50)."
        ),
        since: str | None = typer.Option(
            None, "--since", help="Filter to created_at >= ISO-8601 timestamp."
        ),
        json_output_flag: bool = typer.Option(
            False, "--json", help="Show JSON output for scripts and automation."
        ),
    ) -> None:
        """List saved memories."""

        output = resolve_output(ctx, json_flag=json_output_flag)
        gctx = output.ctx
        json_output = gctx.json_output
        console = make_console()

        try:
            cfg = load_config()
            profile = get_active_profile(cfg, gctx.profile)
            _require_managed_session_for_memory(
                profile, json_output=json_output, plain=gctx.plain, console=console
            )
            Vault.unlock(
                profile.name,
                _resolve_passphrase(
                    profile_name=profile.name, profile_mode=profile.mode, json_output=json_output
                ),
            )
            store = LocalStore(profile.name)

            since_dt = _parse_iso8601(since) if since else None
            envelopes = store.list(tag=tag, limit=1_000_000)

            rows: list[dict[str, object]] = []
            for env in envelopes:
                if since_dt is not None and _parse_iso8601(env.created_at) < since_dt:
                    continue
                _, raw_payload = store.get(env.memory_id)
                rows.append(_memory_summary_dict(env.memory_id, env, len(raw_payload)))
                if len(rows) >= limit:
                    break

            if json_output:
                result_payload = {
                    "status": "ok",
                    "operation": "memory.list",
                    "data": {
                        "tag": tag,
                        "limit": limit,
                        "since": since,
                        "items": rows,
                    },
                    "error": None,
                }
                output.json(result_payload)
                raise typer.Exit(code=0)

            if gctx.plain:
                for row in rows:
                    typer.echo(
                        f"{_short(str(row['id']), head=12, tail=6)}\t{row['created']}\t"
                        f"{','.join(cast(list[str], row['tags'])) if row['tags'] else '-'}\t{row['bytes']}\t"
                        f"{_short(str(row['merkle_root']), head=12, tail=6)}"
                    )
                if not rows:
                    typer.echo("no memories found")
                raise typer.Exit(code=0)

            def _human_size(num_bytes: int) -> str:
                size = float(num_bytes)
                for unit in ("bytes", "KB", "MB", "GB"):
                    if size < 1024 or unit == "GB":
                        if unit == "bytes":
                            return f"{int(size):,} bytes"
                        return f"{size:.1f} {unit}"
                    size /= 1024
                return f"{num_bytes:,} bytes"

            result_word = "memory" if len(rows) == 1 else "memories"
            if tag:
                console.print(
                    f"Found [bold]{len(rows)}[/bold] {result_word} tagged [cyan]#{tag}[/cyan]"
                )
            else:
                console.print(f"Found [bold]{len(rows)}[/bold] {result_word}")

            if not rows:
                remember_command = f'matriosha --profile {profile.name} memory remember "your note"'
                console.print("Nothing to show yet. Save one with:")
                console.print(
                    f"  {remember_command}", overflow="ignore", crop=False, soft_wrap=False
                )
                raise typer.Exit(code=0)

            for index, row in enumerate(rows, start=1):
                memory_id = str(row["id"])
                row_tags = cast(list[str], row["tags"])
                tags_str = " ".join(f"#{t}" for t in row_tags) if row_tags else "-"
                created = str(row["created"]).replace("T", " ").replace("Z", " UTC").split(".")[0]
                console.print()
                console.print(f"[bold]{index}. {_short(memory_id, head=8, tail=6)}[/bold]")
                console.print(f"   When: {created}")
                console.print(f"   Tags: {tags_str}")
                console.print(f"   Size: {_human_size(int(cast(int | str, row['bytes'])))}")
                console.print(f"   Integrity: {_short(str(row['merkle_root']), head=12, tail=6)}")

            console.print()
            first_id = str(rows[0]["id"])
            recall_command = f"matriosha --profile {profile.name} memory recall {first_id}"
            console.print("Read the full memory:")
            console.print(f"  {recall_command}", overflow="ignore", crop=False, soft_wrap=False)
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
                stable_code="STORE-003",
                exit_code=EXIT_UNKNOWN,
                fix="check local memory files and retry",
                debug=f"os_error={type(exc).__name__}",
                json_output=json_output,
                plain=gctx.plain,
                console=console,
            )
            raise typer.Exit(code=EXIT_UNKNOWN)
