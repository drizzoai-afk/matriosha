from __future__ import annotations

from collections.abc import Generator
import asyncio
import hashlib
import json
import os
import shlex
import site
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pexpect
import pytest
import respx
from httpx import Request, Response
from typer.testing import CliRunner

from matriosha.cli.main import app
from matriosha.core.config import MatrioshaConfig, Profile, save_config
from matriosha.core.managed.client import ManagedClient

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PASSPHRASE = "integration-pass"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--real-backend",
        action="store_true",
        default=False,
        help="Run integration tests against the real managed backend.",
    )


@dataclass
class IntegrationCliRunner:
    runner: CliRunner
    base_env: dict[str, str]

    def invoke(self, args: list[str], *, env: dict[str, str] | None = None):
        merged = dict(self.base_env)
        if env:
            merged.update(env)
        return self.runner.invoke(app, args, env=merged)

    def spawn(
        self,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> pexpect.spawn:
        merged = dict(self.base_env)
        if env:
            merged.update(env)
        cmd = [sys.executable, "-m", "matriosha.cli.main", *args]
        quoted = " ".join(shlex.quote(part) for part in cmd)
        return pexpect.spawn(
            quoted,
            cwd=str(REPO_ROOT),
            env=merged,
            encoding="utf-8",
            timeout=timeout,
        )


@dataclass
class ManagedHarness:
    mode: str
    endpoint: str
    token: str
    user_id: str
    cleanup_tag: str
    remote_store: dict[str, dict[str, Any]] = field(default_factory=dict)
    created_remote_ids: set[str] = field(default_factory=set)

    @property
    def env(self) -> dict[str, str]:
        return {
            "MATRIOSHA_MANAGED_ENDPOINT": self.endpoint,
            "MATRIOSHA_MANAGED_TOKEN": self.token,
        }


def _base_env_for_home(home: Path) -> dict[str, str]:
    xdg_config = home / ".config"
    xdg_data = home / ".local" / "share"
    xdg_cache = home / ".cache"
    for path in (xdg_config, xdg_data, xdg_cache):
        path.mkdir(parents=True, exist_ok=True)

    user_site = site.getusersitepackages()
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    pythonpath_parts = [str(REPO_ROOT), user_site]
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(xdg_config),
            "XDG_DATA_HOME": str(xdg_data),
            "XDG_CACHE_HOME": str(xdg_cache),
            "MATRIOSHA_EMBEDDER": "hash",
            "MATRIOSHA_PASSPHRASE": DEFAULT_PASSPHRASE,
            "MATRIOSHA_AUTH_OTP_CODE": "123456",
            "PYTHONPATH": os.pathsep.join(pythonpath_parts),
        }
    )
    env.setdefault("SUPABASE_URL", "https://managed.mock")
    env.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role")
    env.setdefault("SUPABASE_ANON_KEY", "test-anon")
    env.setdefault("STRIPE_SECRET_KEY", "sk_test_stub")
    env.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_stub")
    return env


def is_real_backend_available() -> bool:
    gca_json_env = os.getenv("GCA_JSON")
    gca_candidates = [
        Path(gca_json_env).expanduser() if gca_json_env else None,
        Path(os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")).expanduser()
        if os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        else None,
        Path("~/.config/matriosha/gca.json").expanduser(),
        Path("/home/ubuntu/.config/matriosha/gca.json"),
    ]
    has_gca = any(candidate and candidate.exists() for candidate in gca_candidates)
    has_project = bool(os.getenv("GCP_PROJECT_ID"))
    has_service_account = bool(os.getenv("GCP_SA_KEY")) or bool(os.getenv("GCA_JSON"))
    has_endpoint = bool(os.getenv("MATRIOSHA_MANAGED_ENDPOINT"))
    has_token = bool(os.getenv("MATRIOSHA_MANAGED_TOKEN"))
    return has_gca and has_project and has_service_account and has_endpoint and has_token


@pytest.fixture()
def backend_mode(pytestconfig: pytest.Config) -> str:
    forced_real = bool(pytestconfig.getoption("--real-backend"))
    env_real = os.getenv("MATRIOSHA_TEST_MODE", "").lower() == "real"
    wants_real = forced_real or env_real

    available = is_real_backend_available()
    if wants_real and not available:
        pytest.fail(
            "Real backend requested but required credentials are unavailable. "
            "Provide GCA_JSON, GCP_PROJECT_ID, GCP_SA_KEY, MATRIOSHA_MANAGED_ENDPOINT, MATRIOSHA_MANAGED_TOKEN."
        )

    return "real" if wants_real and available else "mocked"


@pytest.fixture()
def temp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    monkeypatch.setenv("MATRIOSHA_EMBEDDER", "hash")
    monkeypatch.setenv("MATRIOSHA_PASSPHRASE", DEFAULT_PASSPHRASE)

    return home


@pytest.fixture()
def cli_runner(temp_home: Path) -> IntegrationCliRunner:
    return IntegrationCliRunner(runner=CliRunner(), base_env=_base_env_for_home(temp_home))


@pytest.fixture()
def initialized_vault(cli_runner: IntegrationCliRunner) -> str:
    result = cli_runner.invoke(["--plain", "vault", "init", "--passphrase", DEFAULT_PASSPHRASE])
    assert result.exit_code == 0, result.stdout
    return DEFAULT_PASSPHRASE


@pytest.fixture()
def managed_client(backend_mode: str) -> Generator[ManagedHarness, None, None]:
    cleanup_tag = f"it-p71a-{uuid.uuid4().hex[:10]}"

    if backend_mode == "real":
        endpoint = str(os.getenv("MATRIOSHA_MANAGED_ENDPOINT") or "").rstrip("/")
        token = str(os.getenv("MATRIOSHA_MANAGED_TOKEN") or "")
        harness = ManagedHarness(
            mode="real",
            endpoint=endpoint,
            token=token,
            user_id="real-user",
            cleanup_tag=cleanup_tag,
        )
        yield harness

        if harness.created_remote_ids:
            async def _cleanup() -> None:
                async with ManagedClient(
                    token=harness.token,
                    base_url=harness.endpoint,
                    managed_mode=False,
                ) as client:
                    for remote_id in harness.created_remote_ids:
                        try:
                            await client.delete_memory(remote_id)
                        except Exception:
                            continue

            asyncio.run(_cleanup())
        return

    endpoint = "https://managed.mock"
    token = "mock-token"
    user_id = "mock-user"
    remote_store: dict[str, dict[str, Any]] = {}
    agent_tokens: dict[str, dict[str, Any]] = {}

    def _route_vault_custody(request: Request) -> Response:
        payload = json.loads(request.content.decode("utf-8")) if request.content else {}
        action = payload.get("action")
        if action == "fetch":
            return Response(404, json={"error": "not_found"})
        if action == "seal":
            return Response(200, json={"sealed_b64": payload.get("plaintext_b64", "")})
        if action == "upsert":
            return Response(200, json={"status": "ok"})
        return Response(200, json={"status": "ok"})

    def _route_upload_memory(request: Request) -> Response:
        payload = json.loads(request.content.decode("utf-8"))
        envelope = payload.get("envelope") or {}
        local_id = str(envelope.get("memory_id") or uuid.uuid4().hex)
        remote_id = f"remote-{local_id}"
        remote_store[remote_id] = {
            "id": remote_id,
            "memory_id": local_id,
            "envelope": envelope,
            "payload_b64": payload.get("payload_b64", ""),
        }
        return Response(200, json={"id": remote_id})

    def _route_fetch_memory(request: Request) -> Response:
        remote_id = request.url.path.rstrip("/").split("/")[-1]
        record = remote_store[remote_id]
        return Response(200, json={"envelope": record["envelope"], "payload_b64": record["payload_b64"]})

    def _route_list_memories(_: Request) -> Response:
        items = []
        for remote_id, record in remote_store.items():
            digest = hashlib.sha256(
                (
                    json.dumps(record["envelope"], separators=(",", ":"), sort_keys=True)
                    + "\n"
                    + record["payload_b64"]
                ).encode("utf-8")
            ).hexdigest()
            items.append({"id": remote_id, "envelope": record["envelope"], "roundtrip_hash": digest})
        return Response(200, json={"items": items})

    def _route_create_agent_token(request: Request) -> Response:
        payload = json.loads(request.content.decode("utf-8")) if request.content else {}
        token_id = f"tok-{uuid.uuid4().hex[:12]}"
        token_value = f"agt_{uuid.uuid4().hex}"
        salt = uuid.uuid4().hex[:16]
        token_hash = hashlib.sha256(f"{token_value}:{salt}".encode("utf-8")).hexdigest()
        record = {
            "id": token_id,
            "name": str(payload.get("name") or "token"),
            "scope": str(payload.get("scope") or "write"),
            "token": token_value,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "expires_at": payload.get("expires_at"),
            "last_used": None,
            "revoked": False,
            "token_hash": token_hash,
            "salt": salt,
        }
        agent_tokens[token_id] = record
        return Response(200, json=record)

    def _route_list_agent_tokens(_: Request) -> Response:
        return Response(200, json={"items": list(agent_tokens.values())})

    def _route_delete_agent_token(request: Request) -> Response:
        token_id = request.url.path.rstrip("/").split("/")[-1]
        if token_id in agent_tokens:
            agent_tokens[token_id]["revoked"] = True
        return Response(204)

    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        router.post(f"{endpoint}/managed/auth/otp/start").mock(
            return_value=Response(
                200,
                json={
                    "status": "ok",
                    "message": "login code sent",
                },
            )
        )
        router.post(f"{endpoint}/managed/auth/otp/verify").mock(
            return_value=Response(
                200,
                json={
                    "access_token": token,
                    "refresh_token": "refresh-token",
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "scope": "admin",
                    "user": {"id": user_id, "email": "integration@example.test"},
                },
            )
        )
        router.post(f"{endpoint}/managed/auth/refresh").mock(
            return_value=Response(
                200,
                json={
                    "access_token": token,
                    "refresh_token": "refresh-token",
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "scope": "admin",
                    "user": {"id": user_id, "email": "integration@example.test"},
                },
            )
        )
        router.post(f"{endpoint}/oauth/token").mock(
            return_value=Response(
                200,
                json={
                    "access_token": token,
                    "refresh_token": "refresh-token",
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "scope": "admin",
                },
            )
        )
        router.get(f"{endpoint}/managed/whoami").mock(
            return_value=Response(
                200,
                json={
                    "user_id": user_id,
                    "email": "integration@example.test",
                    "subscription_status": "active",
                },
            )
        )
        router.post(f"{endpoint}/functions/v1/vault-custody").mock(side_effect=_route_vault_custody)
        router.post(f"{endpoint}/managed/memories").mock(side_effect=_route_upload_memory)
        router.get(url__regex=rf"{endpoint}/managed/memories/[^/]+$").mock(side_effect=_route_fetch_memory)
        router.get(f"{endpoint}/managed/memories").mock(side_effect=_route_list_memories)
        router.delete(url__regex=rf"{endpoint}/managed/memories/[^/]+$").mock(return_value=Response(204))
        router.post(f"{endpoint}/managed/agent-tokens").mock(side_effect=_route_create_agent_token)
        router.get(f"{endpoint}/managed/agent-tokens").mock(side_effect=_route_list_agent_tokens)
        router.delete(url__regex=rf"{endpoint}/managed/agent-tokens/[^/]+$").mock(side_effect=_route_delete_agent_token)

        yield ManagedHarness(
            mode="mocked",
            endpoint=endpoint,
            token=token,
            user_id=user_id,
            cleanup_tag=cleanup_tag,
            remote_store=remote_store,
        )



@pytest.fixture()
def managed_profile(initialized_vault: str, managed_client: ManagedHarness) -> dict[str, Any]:
    cfg = MatrioshaConfig(
        profiles={
            "default": Profile(
                name="default",
                mode="managed",
                managed_endpoint=managed_client.endpoint,
                created_at=datetime.now(timezone.utc),
            )
        },
        active_profile="default",
    )
    save_config(cfg)

    if managed_client.mode == "real":
        async def _whoami() -> dict[str, Any]:
            async with ManagedClient(
                token=managed_client.token,
                base_url=managed_client.endpoint,
                managed_mode=False,
            ) as client:
                return await client.whoami()

        whoami = asyncio.run(_whoami())
        assert isinstance(whoami, dict) and whoami, "Managed endpoint/token could not authenticate"
    else:
        whoami = {
            "user_id": managed_client.user_id,
            "email": "integration@example.test",
            "subscription_status": "active",
        }

    return {
        "endpoint": managed_client.endpoint,
        "token": managed_client.token,
        "whoami": whoami,
        "cleanup_tag": managed_client.cleanup_tag,
        "mode": managed_client.mode,
    }
