from __future__ import annotations

import asyncio
import os
import shlex
import site
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pexpect
import pytest
from typer.testing import CliRunner

from cli.main import app
from core.config import MatrioshaConfig, Profile, save_config
from core.managed.client import ManagedClient

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PASSPHRASE = "integration-pass"


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
        cmd = [sys.executable, "-m", "cli.main", *args]
        quoted = " ".join(shlex.quote(part) for part in cmd)
        return pexpect.spawn(
            quoted,
            cwd=str(REPO_ROOT),
            env=merged,
            encoding="utf-8",
            timeout=timeout,
        )


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
            "PYTHONPATH": os.pathsep.join(pythonpath_parts),
        }
    )
    return env


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
    result = cli_runner.invoke(
        ["--plain", "vault", "init", "--passphrase", DEFAULT_PASSPHRASE],
    )
    assert result.exit_code == 0, result.stdout
    return DEFAULT_PASSPHRASE


@pytest.fixture()
def managed_profile(initialized_vault: str, temp_home: Path) -> dict[str, Any]:
    endpoint = os.getenv("MATRIOSHA_MANAGED_ENDPOINT")
    token = os.getenv("MATRIOSHA_MANAGED_TOKEN")

    if not endpoint or not token:
        pytest.skip("managed integration tests require MATRIOSHA_MANAGED_ENDPOINT and MATRIOSHA_MANAGED_TOKEN")

    cfg = MatrioshaConfig(
        profiles={
            "default": Profile(
                name="default",
                mode="managed",
                managed_endpoint=endpoint,
                created_at=datetime.now(timezone.utc),
            )
        },
        active_profile="default",
    )
    save_config(cfg)

    async def _whoami() -> dict[str, Any]:
        async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
            return await client.whoami()

    whoami = asyncio.run(_whoami())
    assert isinstance(whoami, dict) and whoami, "Managed endpoint/token could not authenticate"

    return {"endpoint": endpoint, "token": token, "whoami": whoami}
