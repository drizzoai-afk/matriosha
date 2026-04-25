"""Token inspect command."""

from __future__ import annotations

from .common import *

def register(app: typer.Typer) -> None:
    @app.command("inspect")
    def inspect(
        ctx: typer.Context,
        id_or_prefix: str = typer.Argument(..., help="Full token id or unique UUID prefix."),
        json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
    ) -> None:
        """Inspect full token metadata (plaintext token is never shown)."""

        json_output, plain = _resolve_output_mode(ctx, json_flag)
        _validate_backend_credentials(json_output, plain)

        try:
            profile = get_active_profile(load_config(), get_global_context(ctx).profile)
            token = _resolve_managed_token(profile.name, json_output, plain)
            endpoint = profile.managed_endpoint
            tokens = asyncio.run(_list_tokens(token=token, endpoint=endpoint))
            selected = _resolve_token_by_prefix(tokens, id_or_prefix)
        except TokenCommandError as exc:
            _emit_error(exc, json_output=json_output, plain=plain)
        except ManagedClientError as exc:
            _emit_error(_map_managed_error(exc), json_output=json_output, plain=plain)

        payload = {
            "id": str(selected.get("id") or ""),
            "name": str(selected.get("name") or "-"),
            "scope": str(selected.get("scope") or "write"),
            "created_at": _normalize_timestamp(selected.get("created_at")),
            "last_used": _normalize_timestamp(selected.get("last_used")),
            "expires_at": _normalize_timestamp(selected.get("expires_at")),
            "revoked": bool(selected.get("revoked", False)),
            "token_hash": str(selected.get("token_hash") or "-"),
            "salt": str(selected.get("salt") or "-"),
        }

        if json_output:
            typer.echo(json.dumps(payload, sort_keys=True))
            raise typer.Exit(code=0)

        if plain:
            for key, value in payload.items():
                typer.echo(f"{key}: {value}")
            raise typer.Exit(code=0)

        table = Table(title="Token Metadata", show_header=True, header_style="bold accent")
        table.add_column("field", style="bold")
        table.add_column("value")
        for key, value in payload.items():
            table.add_row(key, str(value))
        _console().print(table)
        raise typer.Exit(code=0)

