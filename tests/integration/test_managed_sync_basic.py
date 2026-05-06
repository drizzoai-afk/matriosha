from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from matriosha.core.managed.client import ManagedClient


@pytest.mark.integration
@pytest.mark.managed
def test_managed_sync_basic_flow(initialized_vault, cli_runner, managed_client) -> None:
    mode_set = cli_runner.invoke(
        ["--json", "mode", "set", "managed"],
        env={"MATRIOSHA_MANAGED_TOKEN": managed_client.token},
    )
    assert mode_set.exit_code == 0, mode_set.stdout

    managed_env = {
        "MATRIOSHA_MANAGED_ENDPOINT": managed_client.endpoint,
        "MATRIOSHA_PASSPHRASE": "",
    }

    runtime_env = dict(managed_env)
    if managed_client.mode == "mocked":
        login = cli_runner.invoke(
            [
                "auth",
                "login",
                "--json",
                "--email",
                "integration@example.test",
                "--code",
                runtime_env.get("MATRIOSHA_AUTH_OTP_CODE", "123456"),
            ],
            env=runtime_env,
        )
        assert login.exit_code == 0, login.stdout
        login_payload = json.loads(login.stdout.splitlines()[-1])
        assert login_payload["status"] == "authenticated"
    else:
        runtime_env["MATRIOSHA_MANAGED_TOKEN"] = managed_client.token
        whoami = cli_runner.invoke(["auth", "whoami", "--json"], env=runtime_env)
        assert whoami.exit_code == 0, whoami.stdout

    marker = f"sync-basic-{uuid.uuid4().hex[:8]}"
    remember = cli_runner.invoke(
        [
            "memory",
            "remember",
            f"managed sync integration payload {marker}",
            "--tag",
            managed_client.cleanup_tag,
            "--tag",
            "p71a-managed",
            "--json",
        ],
        env=runtime_env,
    )
    assert remember.exit_code == 0, remember.stdout
    local_memory_id = json.loads(remember.stdout)["data"]["memory_id"]

    synced = cli_runner.invoke(["vault", "sync", "--json"], env=runtime_env)
    assert synced.exit_code == 0, synced.stdout
    sync_payload = json.loads(synced.stdout)
    assert isinstance(sync_payload["pushed"], int)

    if managed_client.mode == "mocked":
        assert managed_client.remote_store
        assert any(
            local_memory_id == record.get("memory_id")
            and managed_client.cleanup_tag in (record.get("envelope") or {}).get("tags", [])
            for record in managed_client.remote_store.values()
        )
    else:

        async def _list_remote() -> list[dict]:
            async with ManagedClient(
                token=managed_client.token,
                base_url=managed_client.endpoint,
                managed_mode=False,
            ) as client:
                return await client.list_memories(tag=managed_client.cleanup_tag, limit=200)

        remote_items = asyncio.run(_list_remote())
        assert remote_items
        remote_ids = {
            str(item.get("id") or item.get("memory_id") or "")
            for item in remote_items
            if item.get("id") or item.get("memory_id")
        }
        managed_client.created_remote_ids.update(remote_ids)
