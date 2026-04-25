"""Vault init command."""

from __future__ import annotations

from .common import *

def register(app: typer.Typer) -> None:
    @app.command("init")
    def init(
        ctx: typer.Context,
        force: bool = typer.Option(False, "--force", help="Overwrite existing local vault files."),
        passphrase: str | None = typer.Option(None, "--passphrase", help="Vault passphrase."),
        json_output_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    ) -> None:
        """Initialize local-mode vault key material for the selected profile."""

        gctx = get_global_context(ctx)
        effective_json = gctx.json_output or json_output_flag
        profile = _resolve_target_profile(gctx.profile)

        if profile.mode == "managed":
            _emit_refusal("vault init is local-mode only", json_output=effective_json, code=EXIT_USAGE)

        limiter = _RateLimiter()
        limiter.apply_backoff_if_needed()

        resolved_passphrase = _resolve_passphrase(provided=passphrase, json_output=effective_json)

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
                _render_card(
                    "VAULT INITIALIZED",
                    [
                        ("profile", profile.name),
                        ("key file", str(vault.key_file)),
                        ("salt file", str(vault.salt_file)),
                        ("next", "matriosha memory remember \"hello\" --tag test"),
                    ],
                    status_chip="✓ INITIALIZED",
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

