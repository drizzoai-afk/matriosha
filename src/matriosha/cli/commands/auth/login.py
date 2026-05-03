"""Auth login command."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

import typer

from matriosha.cli.utils.context import get_global_context
from matriosha.cli.utils.errors import EXIT_AUTH, EXIT_UNKNOWN, EXIT_USAGE

from .common import (
    AuthCommandError,
    EmailOtpFlow,
    EmailOtpFlowError,
    LoginRateLimiter,
    ManagedClient,
    ManagedClientError,
    TokenStore,
    TokenStoreError,
    _emit_error,
    _map_managed_error,
    _profile_and_endpoint,
    ensure_managed_key_bootstrap,
    ensure_managed_passphrase_in_payload,
)

def register(app: typer.Typer) -> None:
    @app.command("login")
    def login(
        ctx: typer.Context,
        email_option: str | None = typer.Option(None, "--email", help="Email address for managed login."),
        code_option: str | None = typer.Option(
            None,
            "--code",
            help="Email OTP code. Recommended for non-interactive automation with --json.",
        ),
        json_flag: bool = typer.Option(False, "--json", help="Show JSON output for scripts and automation."),
    ) -> None:
        """Log in to managed mode and set up managed encryption automatically."""

        gctx = get_global_context(ctx)
        json_output = gctx.json_output or json_flag

        try:
            email = (email_option or "").strip()
            if not email and not json_output:
                email = typer.prompt("Email").strip()
            if not email or "@" not in email:
                raise AuthCommandError(
                    "Valid email is required",
                    category="USAGE",
                    code="USAGE-602",
                    exit_code=EXIT_USAGE,
                    fix="provide --email <you@example.com> or rerun and enter your email",
                    debug="email-missing-or-invalid",
                )

            profile, endpoint = _profile_and_endpoint(ctx)
            limiter = LoginRateLimiter(profile.name)
            limiter.apply_backoff_if_needed()
            limiter.record_attempt()

            flow = EmailOtpFlow(endpoint)

            env_code = os.getenv("MATRIOSHA_AUTH_OTP_CODE", "")
            code = (code_option or env_code).strip().replace(" ", "")

            if code:
                tokens = asyncio.run(flow.verify(email=email, code=code))
            else:
                asyncio.run(flow.start(email))
                if json_output:
                    typer.echo(
                        json.dumps(
                            {
                                "status": "otp_sent",
                                "operation": "auth.login",
                                "email": email,
                                "next_step": (
                                    "rerun with --email and --code (or MATRIOSHA_AUTH_OTP_CODE) "
                                    "to complete authentication"
                                ),
                            },
                            sort_keys=True,
                        )
                    )
                    raise typer.Exit(code=0)

                typer.echo("✓ Login code sent. Check your email.")
                code = typer.prompt("Code").strip().replace(" ", "")
                if not code:
                    raise AuthCommandError(
                        "Login code is required",
                        category="USAGE",
                        code="USAGE-603",
                        exit_code=EXIT_USAGE,
                        fix="rerun `matriosha auth login` and enter the code from your email",
                        debug="otp-missing",
                    )
                tokens = asyncio.run(flow.verify(email=email, code=code))
            token_payload = ensure_managed_passphrase_in_payload(tokens.as_dict())

            async def _bootstrap() -> dict[str, str]:
                async with ManagedClient(token=tokens.access_token, base_url=endpoint, managed_mode=False) as client:
                    result = await ensure_managed_key_bootstrap(
                        client,
                        profile_name=profile.name,
                        managed_passphrase=str(token_payload["managed_passphrase"]),
                    )
                    who = await client.whoami()
                    return {
                        "bootstrap": str(result.get("status") or "existing"),
                        "user_id": str(who.get("user_id") or who.get("id") or ""),
                        "email": str(who.get("email") or ""),
                    }

            bootstrap = asyncio.run(_bootstrap())
            token_payload["endpoint"] = endpoint
            token_payload["profile"] = profile.name
            token_payload["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            TokenStore(profile.name).save(token_payload)

            limiter.clear()

            if json_output:
                typer.echo(
                    json.dumps(
                        {
                            "status": "authenticated",
                            "operation": "auth.login",
                            "managed_key_bootstrap": bootstrap["bootstrap"],
                            "user_id": bootstrap["user_id"],
                            "email": bootstrap["email"],
                            "profile": profile.name,
                        },
                        sort_keys=True,
                    )
                )
                raise typer.Exit(code=0)

            typer.echo("✓ Managed session authenticated")
            typer.echo(f"profile: {profile.name}")
            typer.echo(f"managed key bootstrap: {bootstrap['bootstrap']}")
            raise typer.Exit(code=0)

        except AuthCommandError as exc:
            _emit_error(exc, json_output=json_output, plain=gctx.plain)
        except EmailOtpFlowError as exc:
            _emit_error(
                AuthCommandError(
                    str(exc),
                    category="AUTH",
                    code="AUTH-601",
                    exit_code=EXIT_AUTH,
                    fix="rerun `matriosha auth login` and enter the code from your email",
                    debug="email-otp-flow",
                ),
                json_output=json_output,
                plain=gctx.plain,
            )
        except ManagedClientError as exc:
            _emit_error(_map_managed_error(exc), json_output=json_output, plain=gctx.plain)
        except TokenStoreError as exc:
            _emit_error(
                AuthCommandError(
                    "Failed to persist managed session",
                    category="SYS",
                    code="SYS-602",
                    exit_code=EXIT_UNKNOWN,
                    fix="fix local filesystem permissions and retry login",
                    debug=str(exc),
                ),
                json_output=json_output,
                plain=gctx.plain,
            )

