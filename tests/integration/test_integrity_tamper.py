from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.integration
@pytest.mark.adversarial
def test_integrity_tamper_detected_by_deep_verify(initialized_vault: str, cli_runner: IntegrationCliRunner, temp_home: Path) -> None:
    remember = cli_runner.invoke(["memory", "remember", "tamper target", "--json"])
    assert remember.exit_code == 0, remember.stdout

    memory_id = json.loads(remember.stdout)["data"]["memory_id"]
    payload_file = temp_home / ".local" / "share" / "matriosha" / "default" / "memories" / f"{memory_id}.bin.b64"

    raw = bytearray(payload_file.read_bytes())
    raw[-1] = ord("A") if raw[-1] != ord("A") else ord("B")
    payload_file.write_bytes(bytes(raw))

    verify = cli_runner.invoke(["vault", "verify", "--deep", "--json"])
    assert verify.exit_code == 10, verify.stdout

    payload = json.loads(verify.stdout)
    failed_ids = {item["id"] for item in payload["failed"]}
    assert memory_id in failed_ids
