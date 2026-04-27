from __future__ import annotations
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from tests.integration.conftest import IntegrationCliRunner
import asyncio
import json
import uuid

import pytest

from matriosha.core.managed.client import ManagedClient


@pytest.mark.integration
@pytest.mark.managed
def test_managed_whoami_works_with_profile_token(
    cli_runner: IntegrationCliRunner,
    managed_profile: dict[str, str],
) -> None:
    token = managed_profile["token"]
    endpoint = managed_profile["endpoint"]

    result = cli_runner.invoke(
        ["auth", "whoami", "--json"],
        env={"MATRIOSHA_MANAGED_TOKEN": token, "MATRIOSHA_MANAGED_ENDPOINT": endpoint},
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["operation"] == "auth.whoami"


@pytest.mark.integration
@pytest.mark.managed
def test_managed_sync_pushes_to_real_backend(cli_runner: IntegrationCliRunner, managed_profile: dict[str, str]) -> None:
    token = managed_profile["token"]
    endpoint = managed_profile["endpoint"]

    async def _count_remote() -> int:
        async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
            return len(await client.list_memories(limit=10_000))

    before_count = asyncio.run(_count_remote())

    payload_text = f"managed sync integration {uuid.uuid4()}"
    remember = cli_runner.invoke(
        ["memory", "remember", payload_text, "--tag", "integration", "--json"],
        env={"MATRIOSHA_MANAGED_TOKEN": token, "MATRIOSHA_MANAGED_ENDPOINT": endpoint},
    )
    assert remember.exit_code == 0, remember.stdout

    synced = cli_runner.invoke(
        ["vault", "sync", "--json"],
        env={"MATRIOSHA_MANAGED_TOKEN": token, "MATRIOSHA_MANAGED_ENDPOINT": endpoint},
    )
    assert synced.exit_code == 0, synced.stdout

    after_count = asyncio.run(_count_remote())
    assert after_count >= before_count + 1
