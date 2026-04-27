"""Vault init command."""

from __future__ import annotations

import json

import typer

from matriosha.cli.brand.banner import print_banner
from matriosha.cli.brand.theme import console as make_console
from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_AUTH, EXIT_INTEGRITY, EXIT_OK, EXIT_USAGE
from matriosha.core.audit import AuditEvent, AuditJournal
from matriosha.core.vault import AuthError, Vault, VaultAlreadyInitializedError, VaultIntegrityError

from .common import (
    _RateLimiter,
    _emit_refusal,
    _render_card,
    _resolve_passphrase,
    _resolve_target_profile,
)

def register(app: typer.Typer) -> None:
    @app.command("init")
    def init(
        ctx: typer.Context,
        force: bool = typer.Option(False, "--force", help="Overwrite existing local vault files."),
        passphrase: str | None = typer.Option(None, "--passphrase", help="Passphrase for this local encrypted vault. Prefer the hidden prompt for normal use."),
        json_output_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Set up encryption for this local workspace."""

        gctx = get_global_context(ctx)
        effective_json = gctx.json_output or json_output_flag
        profile = _resolve_target_profile(gctx.profile)

        if profile.mode == "managed":
            _emit_refusal("vault init is local-mode only", json_output=effective_json, code=EXIT_USAGE)

        limiter = _RateLimiter()
        limiter.apply_backoff_if_needed()

        resolved_passphrase, passphrase_source = _resolve_passphrase(provided=passphrase, json_output=effective_json, with_source=True)

        try:
            key_file, salt_file = Vault._paths(profile.name)
            if key_file.exists() and not force:
                limiter.record_failure()
                _emit_refusal(
                    f"vault already exists for profile '{profile.name}'",
                    json_output=effective_json,
                    code=EXIT_USAGE,
                )

            if force and (key_file.exists() or salt_file.exists()):
                Vault.validate_material(profile.name)

            vault = Vault.init(profile.name, resolved_passphrase, force=force)
            try:
                AuditJournal(profile.name).append(
                    AuditEvent.create(
                        profile=profile.name,
                        mode=profile.mode,
                        action="vault.init",
                        target_type="vault",
                        target_id=profile.name,
                        outcome="success",
                        metadata={"force": force, "passphrase_source": passphrase_source},
                    )
                )
            except Exception:
                pass
            limiter.clear()

            if effective_json:
                typer.echo(
                    json.dumps(
                        {
                            "status": "ok",
                            "profile": profile.name,
                            "salt_file": str(vault.salt_file),
                            "key_file": str(vault.key_file),
                        }
                    )
                )
                raise typer.Exit(code=EXIT_OK)

            if not gctx.plain:
                branded_console = make_console()
                print_banner(branded_console)
                branded_console.print()
                rows = [
                    ("profile", profile.name),
                    ("key file", "created"),
                    ("salt file", "created"),
                    ("passphrase source", passphrase_source),
                ]
                if passphrase_source == "environment variable":
                    rows.append(("security note", "For normal use, prefer the hidden prompt."))
                rows.extend(
                    [
                        ("important", "Save your passphrase. It cannot be recovered."),
                        ("next", "matriosha memory remember \"hello\" --tag test"),
                    ]
                )
                _render_card(
                    "VAULT INITIALIZED",
                    rows,
                    status_chip="✓",
                    style="success",
                )
            else:
                typer.echo(f"vault initialized for profile '{profile.name}'")
                typer.echo(f"key file: {vault.key_file}")
                typer.echo(f"salt file: {vault.salt_file}")

            raise typer.Exit(code=EXIT_OK)

        except VaultIntegrityError as exc:
            limiter.record_failure()
            if effective_json:
                typer.echo(json.dumps({"status": "error", "error": str(exc)}))
            else:
                _render_card(
                    "VAULT INTEGRITY ERROR",
                    [("reason", str(exc)), ("exit", str(EXIT_INTEGRITY))],
                    status_chip="✖ INTEGRITY",
                    style="danger",
                )
            raise typer.Exit(code=EXIT_INTEGRITY)
        except AuthError as exc:
            limiter.record_failure()
            if effective_json:
                typer.echo(json.dumps({"status": "error", "error": str(exc)}))
            else:
                _render_card(
                    "VAULT AUTH ERROR",
                    [("reason", str(exc)), ("exit", str(EXIT_AUTH))],
                    status_chip="✖ AUTH",
                    style="danger",
                )
            raise typer.Exit(code=EXIT_AUTH)
        except VaultAlreadyInitializedError as exc:
            limiter.record_failure()
            _emit_refusal(str(exc), json_output=effective_json, code=EXIT_USAGE)

