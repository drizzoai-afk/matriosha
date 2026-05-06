from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner

from matriosha.core.managed.client import ManagedClient, ScopeError
from matriosha.core.secrets import get_secret

_EXIT_SCOPE_DENIED = 20
_runner = CliRunner()


def _jwt_secret() -> str:
    os.environ.setdefault("GCP_PROJECT_ID", "test-project")
    secret = get_secret("SUPABASE_JWT_SECRET")
    if not secret:
        pytest.skip("SUPABASE_JWT_SECRET missing (env/GSM); skipping scope enforcement tests")
    return secret


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _build_jwt(*, secret: str, scope: str) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": "00000000-0000-0000-0000-000000000001",
        "role": "authenticated",
        "scope": scope,
        "iat": now,
        "exp": now + 3600,
        "aud": "authenticated",
    }
    encoded_header = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{_b64url(signature)}"


def _scope_test_cli() -> typer.Typer:
    app = typer.Typer()

    @app.command("delete-memory")
    def delete_memory(token: str = typer.Option(..., "--token")) -> None:
        async def _delete() -> None:
            async with ManagedClient(
                token=token,
                base_url="https://managed.example",
                managed_mode=False,
            ) as client:
                await client.delete_memory("mem_scope")

        try:
            asyncio.run(_delete())
            typer.echo("ok")
            raise typer.Exit(code=0)
        except ScopeError as exc:
            typer.echo(str(exc))
            raise typer.Exit(code=_EXIT_SCOPE_DENIED)

    return app


def test_read_scope_delete_memory_exits_20_with_actionable_error() -> None:
    secret = _jwt_secret()
    read_token = _build_jwt(secret=secret, scope="read")
    app = _scope_test_cli()

    with respx.mock(assert_all_mocked=True) as mock:
        mock.delete("https://managed.example/managed/memories/mem_scope").mock(
            return_value=httpx.Response(
                403,
                json={
                    "error": {
                        "code": "insufficient_scope",
                        "required_scope": "admin",
                        "provided_scope": "read",
                    }
                },
            )
        )

        result = _runner.invoke(app, ["--token", read_token])

    assert result.exit_code == _EXIT_SCOPE_DENIED
    assert "Token scope is insufficient" in result.stdout
    assert "scope_required=admin" in result.stdout
    assert "scope_provided=read" in result.stdout
    assert "matriosha token generate --scope admin" in result.stdout


def test_admin_scope_token_allows_memory_upload_fetch_and_delete() -> None:
    secret = _jwt_secret()
    admin_token = _build_jwt(secret=secret, scope="admin")

    async def _run() -> dict[str, Any]:
        with respx.mock(assert_all_mocked=True) as mock:
            mock.post("https://managed.example/managed/memories").mock(
                return_value=httpx.Response(200, json={"id": "mem_admin"})
            )
            mock.get("https://managed.example/managed/memories/mem_admin").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "envelope": {"memory_id": "mem_admin", "tags": ["scope"]},
                        "payload_b64": "SGVsbG8=",
                    },
                )
            )
            mock.delete("https://managed.example/managed/memories/mem_admin").mock(
                return_value=httpx.Response(204)
            )

            async with ManagedClient(
                token=admin_token,
                base_url="https://managed.example",
                managed_mode=False,
            ) as client:
                memory_id = await client.upload_memory(
                    envelope={"memory_id": "mem_admin", "tags": ["scope"]},
                    payload_b64="SGVsbG8=",
                )
                envelope, payload_b64 = await client.fetch_memory(memory_id)
                deleted = await client.delete_memory(memory_id)

            return {
                "memory_id": memory_id,
                "envelope": envelope,
                "payload": payload_b64,
                "deleted": deleted,
            }

    result = asyncio.run(_run())
    assert result["memory_id"] == "mem_admin"
    assert result["envelope"]["memory_id"] == "mem_admin"
    assert result["payload"] == "SGVsbG8="
    assert result["deleted"] is True
