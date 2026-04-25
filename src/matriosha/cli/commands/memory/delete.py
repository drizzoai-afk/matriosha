"""`matriosha memory delete` command."""

from __future__ import annotations

import typer

from .common import *


def register(app: typer.Typer) -> None:
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
