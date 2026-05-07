from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from matriosha.cli.utils.errors import EXIT_NETWORK, EXIT_UNKNOWN, EXIT_USAGE
from matriosha.core.managed.client import NetworkError


def _assert_error_contract(
    raw: str,
    *,
    expected_exit: int,
    expected_category: str,
    remediation_contains: str,
) -> dict[str, Any]:
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert payload["exit"] == expected_exit
    assert payload["category"] == expected_category
    assert isinstance(payload.get("code"), str) and payload["code"]
    assert isinstance(payload.get("title"), str) and payload["title"]
    assert isinstance(payload.get("debug"), str) and payload["debug"]
    fix = str(payload.get("fix") or "")
    assert remediation_contains in fix
    return payload


@pytest.mark.integration
@pytest.mark.adversarial
def test_adversarial_malformed_command_contract_local(initialized_vault, cli_runner) -> None:
    malformed = cli_runner.invoke(["memory", "remember", "payload", "--stdin", "--json"])
    assert malformed.exit_code == EXIT_USAGE

    payload = _assert_error_contract(
        malformed.stdout,
        expected_exit=EXIT_USAGE,
        expected_category="VAL",
        remediation_contains="provide exactly one source",
    )
    assert payload["code"] == "VAL-001"


@pytest.mark.integration
@pytest.mark.adversarial
def test_adversarial_invalid_file_payload_contract_local(initialized_vault, cli_runner) -> None:
    missing_file = cli_runner.invoke(
        ["memory", "remember", "--file", "/definitely/missing-file.bin", "--json"]
    )
    assert missing_file.exit_code == EXIT_USAGE

    payload = _assert_error_contract(
        missing_file.stdout,
        expected_exit=EXIT_USAGE,
        expected_category="VAL",
        remediation_contains="valid tags",
    )
    assert payload["code"] == "VAL-001"


@pytest.mark.integration
@pytest.mark.adversarial
def test_adversarial_permission_denied_path_contract_local(
    initialized_vault,
    cli_runner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked = tmp_path / "blocked.txt"
    blocked.write_text("permission denied test", encoding="utf-8")

    original_read_bytes = Path.read_bytes

    def _permission_denied(path: Path) -> bytes:
        if path == blocked:
            raise PermissionError("simulated permission denied")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", _permission_denied)

    denied = cli_runner.invoke(["memory", "remember", "--file", str(blocked), "--json"])

    assert denied.exit_code == EXIT_UNKNOWN
    payload = _assert_error_contract(
        denied.stdout,
        expected_exit=EXIT_UNKNOWN,
        expected_category="STORE",
        remediation_contains="check file permissions",
    )
    assert payload["code"] == "STORE-001"


@pytest.mark.integration
@pytest.mark.adversarial
def test_adversarial_managed_network_fault_injection(
    initialized_vault,
    cli_runner,
    managed_client,
    managed_profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mode_set = cli_runner.invoke(
        ["--json", "mode", "set", "managed"],
        env={"MATRIOSHA_MANAGED_TOKEN": managed_client.token},
    )
    assert mode_set.exit_code == 0, mode_set.stdout

    async def _fault(*args, **kwargs):  # noqa: ANN002,ANN003
        raise NetworkError(
            "Simulated managed connectivity outage",
            category="NET",
            code="NET-599",
            remediation="retry after network recovers or run `matriosha auth login`",
            debug_hint="fault_injection=whoami timeout",
        )

    monkeypatch.setattr("matriosha.core.managed.client.ManagedClient.whoami", _fault)

    managed_env = {
        "MATRIOSHA_MANAGED_ENDPOINT": managed_client.endpoint,
        "MATRIOSHA_MANAGED_TOKEN": managed_client.token,
    }
    whoami = cli_runner.invoke(["auth", "whoami", "--json"], env=managed_env)

    assert whoami.exit_code == EXIT_NETWORK
    payload = _assert_error_contract(
        whoami.stdout,
        expected_exit=EXIT_NETWORK,
        expected_category="NET",
        remediation_contains="matriosha auth login",
    )
    assert payload["code"] == "NET-599"


@pytest.mark.integration
@pytest.mark.adversarial
def test_adversarial_preview_truncation_and_semantic_snapshot(
    initialized_vault, cli_runner
) -> None:
    long_payload = "L" * 5000 + " semantic-tail"
    remembered = cli_runner.invoke(["memory", "remember", long_payload, "--json"])
    assert remembered.exit_code == 0, remembered.stdout
    remember_payload = json.loads(remembered.stdout)
    memory_id = remember_payload["data"]["memory_id"]

    recalled = cli_runner.invoke(["memory", "recall", memory_id, "--json"])
    assert recalled.exit_code == 0, recalled.stdout
    recalled_payload = json.loads(recalled.stdout)

    searched = cli_runner.invoke(["memory", "search", "semantic-tail", "--k", "1", "--json"])
    assert searched.exit_code == 0, searched.stdout
    searched_payload = json.loads(searched.stdout)

    preview = recalled_payload["data"]["preview"]
    semantic = recalled_payload["data"]["semantic"]

    assert len(preview) == 4096
    assert preview == semantic["preview"]
    assert semantic["kind"]
    assert semantic["mime_type"]
    assert isinstance(semantic.get("metadata"), dict)
    assert isinstance(semantic.get("warnings"), list)
    assert isinstance(semantic.get("text"), str)

    row = searched_payload["data"]["results"][0]
    assert "semantic" in row
    assert row["semantic"]["preview"]

    normalized = {
        "recall": {
            "operation": recalled_payload["operation"],
            "preview_len": len(preview),
            "semantic_keys": sorted(semantic.keys()),
            "semantic_kind": semantic["kind"],
            "semantic_mime": semantic["mime_type"],
            "warnings": semantic["warnings"],
        },
        "search": {
            "operation": searched_payload["operation"],
            "result_count": len(searched_payload["data"]["results"]),
            "first_result_semantic_keys": sorted(row["semantic"].keys()),
            "first_result_preview_len": len(str(row["semantic"].get("preview") or "")),
        },
    }

    assert normalized["recall"]["operation"] == "memory.recall"
    assert normalized["recall"]["preview_len"] == 4096
    assert "filename" in normalized["recall"]["semantic_keys"]
    assert "metadata" in normalized["recall"]["semantic_keys"]
    assert "mime_type" in normalized["recall"]["semantic_keys"]
    assert "preview" in normalized["recall"]["semantic_keys"]
    assert "tables" in normalized["recall"]["semantic_keys"]
    assert "text" in normalized["recall"]["semantic_keys"]
    assert "warnings" in normalized["recall"]["semantic_keys"]
    assert normalized["recall"]["semantic_kind"]
    assert normalized["recall"]["semantic_mime"]
    assert isinstance(normalized["recall"]["warnings"], list)
    assert normalized["search"]["operation"] == "memory.search"
    assert normalized["search"]["result_count"] == 1
    assert "preview" in normalized["search"]["first_result_semantic_keys"]
    assert normalized["search"]["first_result_preview_len"] > 0
