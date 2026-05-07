from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _normalize_failure_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(payload))
    failures = normalized.get("failed") or []
    for item in failures:
        if isinstance(item, dict):
            item["id"] = "<MEMORY_ID>"
    return normalized


@pytest.mark.integration
@pytest.mark.adversarial
def test_integrity_corruption_detects_and_exits_10(
    initialized_vault, cli_runner, temp_home
) -> None:
    remember = cli_runner.invoke(
        ["memory", "remember", "--file", str(FIXTURES_DIR / "knowledge_base.md"), "--json"]
    )
    assert remember.exit_code == 0, remember.stdout

    memory_id = json.loads(remember.stdout)["data"]["memory_id"]
    payload_file = (
        temp_home
        / ".local"
        / "share"
        / "matriosha"
        / "default"
        / "memories"
        / f"{memory_id}.bin.b64"
    )

    raw = bytearray(payload_file.read_bytes())
    midpoint = len(raw) // 2
    raw[midpoint] = ord("A") if raw[midpoint] != ord("A") else ord("B")
    payload_file.write_bytes(bytes(raw))

    verify = cli_runner.invoke(["vault", "verify", "--deep", "--json"])
    assert verify.exit_code == 10, verify.stdout

    payload = json.loads(verify.stdout)
    failed_ids = {item["id"] for item in payload["failed"]}
    assert memory_id in failed_ids

    normalized = _normalize_failure_payload(payload)
    assert normalized["ok"] == 0
    assert normalized["total"] == 1
    assert isinstance(normalized["failed"], list)
    assert len(normalized["failed"]) == 1
    first_failure = normalized["failed"][0]
    assert first_failure["id"] == "<MEMORY_ID>"
    assert first_failure["reason"] == "Ciphertext integrity check failed"
