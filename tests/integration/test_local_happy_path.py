from __future__ import annotations

import json

import pytest


@pytest.mark.integration
def test_local_happy_path_end_to_end(initialized_vault: str, cli_runner: IntegrationCliRunner) -> None:
    remembered_ids: list[str] = []

    for idx in range(3):
        remember = cli_runner.invoke(
            ["memory", "remember", f"happy path memory {idx}", "--tag", "happy", "--json"],
        )
        assert remember.exit_code == 0, remember.stdout
        payload = json.loads(remember.stdout)
        remembered_ids.append(payload["data"]["memory_id"])

    listed = cli_runner.invoke(["memory", "list", "--tag", "happy", "--json"])
    assert listed.exit_code == 0, listed.stdout
    listed_payload = json.loads(listed.stdout)
    assert len(listed_payload["data"]["items"]) >= 3

    searched = cli_runner.invoke(["memory", "search", "happy path memory", "--k", "5", "--json"])
    assert searched.exit_code == 0, searched.stdout
    search_payload = json.loads(searched.stdout)
    assert len(search_payload["data"]["results"]) >= 1

    recalled = cli_runner.invoke(["memory", "recall", remembered_ids[0], "--json"])
    assert recalled.exit_code == 0, recalled.stdout
    recalled_payload = json.loads(recalled.stdout)
    assert recalled_payload["data"]["memory_id"] == remembered_ids[0]

    deleted = cli_runner.invoke(["memory", "delete", remembered_ids[1], "--yes", "--json"])
    assert deleted.exit_code == 0, deleted.stdout

    verify = cli_runner.invoke(["vault", "verify", "--deep", "--json"])
    assert verify.exit_code == 0, verify.stdout
    verify_payload = json.loads(verify.stdout)
    assert verify_payload["failed"] == []
