"""Vault verify command."""

from __future__ import annotations

import base64
import binascii
import json

import typer
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from matriosha.cli.brand.theme import console as make_console
from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_AUTH, EXIT_INTEGRITY, EXIT_OK, EXIT_USAGE
from matriosha.core.binary_protocol import decode_envelope, merkle_root
from matriosha.core.config import get_active_profile, load_config
from matriosha.core.crypto import IntegrityError
from matriosha.core.managed.auth import ensure_process_managed_passphrase
from matriosha.core.storage_local import LocalStore
from matriosha.core.vault import AuthError, Vault, VaultIntegrityError

from .common import _emit_error, _resolve_passphrase

def register(app: typer.Typer) -> None:
    @app.command("verify")
    def verify(
        ctx: typer.Context,
        deep: bool = typer.Option(False, "--deep", help="Decrypt each memory and verify Merkle integrity end-to-end."),
        json_output_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Check that local memories are intact."""

        gctx = get_global_context(ctx)
        json_output = gctx.json_output or json_output_flag
        console = make_console()

        try:
            cfg = load_config()
            profile = get_active_profile(cfg, gctx.profile)
            store = LocalStore(profile.name)
            envelopes = store.list(limit=1_000_000)

            vault = None
            if deep:
                if profile.mode == "managed":
                    passphrase = ensure_process_managed_passphrase(profile.name)
                    if not passphrase:
                        raise AuthError("managed key session missing; run `matriosha auth login`")
                else:
                    passphrase = _resolve_passphrase(provided=None, json_output=False)
                vault = Vault.unlock(profile.name, passphrase)

            total = len(envelopes)
            ok = 0
            failed: list[dict[str, str]] = []

            progress = None
            task_id = None
            if total > 0 and not json_output and not gctx.plain:
                progress = Progress(
                    SpinnerColumn(),
                    TextColumn("[bold cyan]{task.description}"),
                    BarColumn(),
                    TextColumn("{task.completed}/{task.total}"),
                    TimeElapsedColumn(),
                    console=console,
                )
                progress.start()
                task_id = progress.add_task("vault verify", total=total)

            for env in envelopes:
                reason = ""
                try:
                    env_obj, payload_b64 = store.get(env.memory_id)

                    if deep:
                        assert vault is not None
                        decode_envelope(env_obj, payload_b64, vault.data_key)
                    else:
                        try:
                            encrypted_blob = base64.b64decode(payload_b64, validate=True)
                        except binascii.Error as exc:
                            raise IntegrityError("payload is not valid base64") from exc

                        if len(encrypted_blob) < 12:
                            raise IntegrityError("payload too short")

                        if merkle_root(env_obj.merkle_leaves) != env_obj.merkle_root:
                            raise IntegrityError("merkle root mismatch")

                        for leaf in env_obj.merkle_leaves:
                            if len(leaf) != 64:
                                raise IntegrityError("invalid merkle leaf length")
                            int(leaf, 16)

                    ok += 1
                except (IntegrityError, ValueError) as exc:
                    reason = str(exc)
                except Exception as exc:  # noqa: BLE001
                    reason = f"{type(exc).__name__}: {exc}"

                if reason:
                    failed.append({"id": env.memory_id, "reason": reason})

                if progress is not None and task_id is not None:
                    progress.update(task_id, advance=1)

            if progress is not None:
                progress.stop()

            summary = {"total": total, "ok": ok, "failed": failed}
            has_failures = len(failed) > 0

            if json_output:
                typer.echo(json.dumps(summary))
                raise typer.Exit(code=EXIT_INTEGRITY if has_failures else EXIT_OK)

            if gctx.plain:
                typer.echo(f"total: {total}")
                typer.echo(f"ok: {ok}")
                typer.echo(f"failed: {len(failed)}")
                for item in failed:
                    typer.echo(f"- {item['id']}: {item['reason']}")
            else:
                if total == 0:
                    console.print("[bold green]✓ Vault is ready[/bold green]")
                    console.print("No memories found yet.")
                    console.print('Next: matriosha memory remember "hello" --tag test')
                else:
                    summary_table = Table(title="Vault Verify Summary", show_header=True, header_style="bold cyan")
                    summary_table.add_column("metric")
                    summary_table.add_column("value", justify="right")
                    summary_table.add_row("total", str(total))
                    summary_table.add_row("ok", str(ok))
                    summary_table.add_row("failed", str(len(failed)))
                    console.print(summary_table)

                    if failed:
                        failed_table = Table(title="Verification Failures", show_header=True, header_style="bold red")
                        failed_table.add_column("id")
                        failed_table.add_column("reason")
                        for item in failed:
                            failed_table.add_row(item["id"], item["reason"])
                        console.print(failed_table)

            raise typer.Exit(code=EXIT_INTEGRITY if has_failures else EXIT_OK)

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
            )
            raise typer.Exit(code=EXIT_AUTH)
        except (OSError, VaultIntegrityError, ValueError) as exc:
            _emit_error(
                title="Vault verify storage failure",
                category="STORE",
                stable_code="STORE-010",
                exit_code=EXIT_USAGE,
                fix="check local vault files and run `matriosha doctor`",
                debug=f"os_error={type(exc).__name__}",
                json_output=json_output,
                plain=gctx.plain,
            )
            raise typer.Exit(code=EXIT_USAGE)

