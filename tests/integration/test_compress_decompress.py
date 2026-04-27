from __future__ import annotations
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from tests.integration.conftest import IntegrationCliRunner
import json

import pytest


@pytest.mark.integration
def test_compress_decompress_full_cycle(initialized_vault: str, cli_runner: IntegrationCliRunner) -> None:
    for _ in range(3):
        remember = cli_runner.invoke(["memory", "remember", "dedup me", "--tag", "cluster", "--json"])
        assert remember.exit_code == 0, remember.stdout

    compressed = cli_runner.invoke(["memory", "compress", "--threshold", "0.9", "--tag", "cluster", "--json"])
    assert compressed.exit_code == 0, compressed.stdout
    compressed_payload = json.loads(compressed.stdout)

    assert compressed_payload["cluster_count"] >= 1
    parent_id = compressed_payload["created_parents"][0]["parent_id"]

    decompressed = cli_runner.invoke(["memory", "decompress", parent_id, "--json"])
    assert decompressed.exit_code == 0, decompressed.stdout
    decompressed_payload = json.loads(decompressed.stdout)

    assert len(decompressed_payload["restored"]) >= 2
    assert decompressed_payload["parent_deleted"] is True
