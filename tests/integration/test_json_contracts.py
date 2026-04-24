from __future__ import annotations

import json
import re

import pexpect
import pytest


def _run_json_with_pexpect(cli_runner: IntegrationCliRunner, args: list[str]) -> tuple[int, dict]:
    proc = cli_runner.spawn(args, timeout=90)
    proc.expect(pexpect.EOF)
    proc.close()
    output = proc.before.strip()
    assert output, f"No output for command: {' '.join(args)}"
    payload = json.loads(output.splitlines()[-1])
    code = proc.exitstatus if proc.exitstatus is not None else 1
    return code, payload


def _normalize_snapshot(raw: str) -> str:
    normalized = re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27}", "<MEMORY_ID>", raw)
    normalized = re.sub(r"\d{4}-\d{2}-\d{2}T[^\"]+Z", "<TIMESTAMP>", normalized)
    normalized = re.sub(r"[0-9a-f]{64}", "<HASH64>", normalized)
    return normalized


@pytest.mark.integration
def test_json_contract_snapshots_via_pexpect(initialized_vault: str, cli_runner: IntegrationCliRunner) -> None:
    status, remembered = _run_json_with_pexpect(cli_runner, ["memory", "remember", "snapshot payload", "--json"])
    assert status == 0
    memory_id = remembered["data"]["memory_id"]

    snapshots: dict[str, str] = {}
    snapshots["remember"] = _normalize_snapshot(json.dumps(remembered, sort_keys=True))

    status, listed = _run_json_with_pexpect(cli_runner, ["memory", "list", "--json"])
    assert status == 0
    snapshots["list"] = _normalize_snapshot(json.dumps(listed, sort_keys=True))

    searched = cli_runner.invoke(["memory", "search", "snapshot", "--json"])
    assert searched.exit_code == 0, searched.stdout
    searched_payload = json.loads(searched.stdout)
    assert searched_payload["data"]["results"]
    assert "semantic" in searched_payload["data"]["results"][0]
    snapshots["search"] = _normalize_snapshot(json.dumps(searched_payload, sort_keys=True))

    recalled = cli_runner.invoke(["memory", "recall", memory_id, "--json"])
    assert recalled.exit_code == 0, recalled.stdout
    recalled_payload = json.loads(recalled.stdout)
    assert "semantic" in recalled_payload["data"]
    assert "preview" in recalled_payload["data"]
    snapshots["recall"] = _normalize_snapshot(json.dumps(recalled_payload, sort_keys=True))

    deleted = cli_runner.invoke(["memory", "delete", memory_id, "--yes", "--json"])
    assert deleted.exit_code == 0, deleted.stdout
    snapshots["delete"] = _normalize_snapshot(json.dumps(json.loads(deleted.stdout), sort_keys=True))

    assert "\"operation\": \"memory.remember\"" in snapshots["remember"]
    assert "\"operation\": \"memory.list\"" in snapshots["list"]
    assert "\"operation\": \"memory.search\"" in snapshots["search"]
    assert "\"operation\": \"memory.recall\"" in snapshots["recall"]
    assert "\"operation\": \"memory.delete\"" in snapshots["delete"]
