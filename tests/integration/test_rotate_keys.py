from __future__ import annotations

import base64
import json

import pytest


@pytest.mark.integration
def test_rotate_kek_then_data_key_keeps_memories_recallable(
    initialized_vault: str,
    cli_runner: IntegrationCliRunner,
) -> None:
    remembered: list[tuple[str, str]] = []
    for plaintext in ("rotate alpha", "rotate beta"):
        result = cli_runner.invoke(["memory", "remember", plaintext, "--json"])
        assert result.exit_code == 0, result.stdout
        remembered.append((json.loads(result.stdout)["data"]["memory_id"], plaintext))

    kek_rotate = cli_runner.invoke(
        [
            "vault",
            "rotate",
            "--current-passphrase",
            "integration-pass",
            "--new-passphrase",
            "integration-pass-v2",
            "--json",
        ]
    )
    assert kek_rotate.exit_code == 0, kek_rotate.stdout
    kek_payload = json.loads(kek_rotate.stdout)
    assert kek_payload["rotate_data_key"] is False
    assert kek_payload["reencrypted_memories"] == 0
    assert kek_payload["resumed"] is False

    data_key_rotate = cli_runner.invoke(
        [
            "vault",
            "rotate",
            "--current-passphrase",
            "integration-pass-v2",
            "--new-passphrase",
            "integration-pass-v3",
            "--rotate-data-key",
            "--confirm-bulk",
            "--json",
        ],
        env={"MATRIOSHA_PASSPHRASE": "integration-pass-v2"},
    )
    assert data_key_rotate.exit_code == 0, data_key_rotate.stdout
    data_key_payload = json.loads(data_key_rotate.stdout)
    assert data_key_payload["rotate_data_key"] is True
    assert data_key_payload["reencrypted_memories"] == len(remembered)
    assert data_key_payload["resumed"] is False

    for memory_id, expected_text in remembered:
        recalled = cli_runner.invoke(
            ["memory", "recall", memory_id, "--json"],
            env={"MATRIOSHA_PASSPHRASE": "integration-pass-v3"},
        )
        assert recalled.exit_code == 0, recalled.stdout
        payload = json.loads(recalled.stdout)["data"]
        plaintext = base64.b64decode(payload["plaintext_b64"]).decode("utf-8")
        assert plaintext == expected_text
        assert payload["integrity_warning"] is None


@pytest.mark.integration
@pytest.mark.adversarial
def test_rotate_data_key_resume_after_crash_path(
    initialized_vault: str,
    cli_runner: IntegrationCliRunner,
) -> None:
    remembered_ids: list[str] = []
    for text in ("resume one", "resume two", "resume three"):
        remembered = cli_runner.invoke(["memory", "remember", text, "--json"])
        assert remembered.exit_code == 0, remembered.stdout
        remembered_ids.append(json.loads(remembered.stdout)["data"]["memory_id"])

    crashed = cli_runner.invoke(
        [
            "vault",
            "rotate",
            "--current-passphrase",
            "integration-pass",
            "--new-passphrase",
            "integration-pass-v2",
            "--rotate-data-key",
            "--confirm-bulk",
            "--json",
        ],
        env={"MATRIOSHA_ROTATE_CRASH_AFTER": "1"},
    )
    assert crashed.exit_code == 2, crashed.stdout
    assert "simulated rotate crash" in crashed.stdout

    resumed = cli_runner.invoke(
        [
            "vault",
            "rotate",
            "--current-passphrase",
            "integration-pass",
            "--new-passphrase",
            "integration-pass-v2",
            "--rotate-data-key",
            "--confirm-bulk",
            "--json",
        ]
    )
    assert resumed.exit_code == 0, resumed.stdout
    resumed_payload = json.loads(resumed.stdout)
    assert resumed_payload["rotate_data_key"] is True
    assert resumed_payload["reencrypted_memories"] == len(remembered_ids)
    assert resumed_payload["resumed"] is True

    for memory_id in remembered_ids:
        recalled = cli_runner.invoke(
            ["memory", "recall", memory_id, "--json"],
            env={"MATRIOSHA_PASSPHRASE": "integration-pass-v2"},
        )
        assert recalled.exit_code == 0, recalled.stdout
