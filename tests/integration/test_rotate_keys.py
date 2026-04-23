from __future__ import annotations

import base64
import json

import pytest


@pytest.mark.integration
def test_rotate_kek_then_data_key_keeps_memories_recallable(
    initialized_vault: str,
    cli_runner: IntegrationCliRunner,
) -> None:
    remember_one = cli_runner.invoke(["memory", "remember", "rotate alpha", "--json"])
    remember_two = cli_runner.invoke(["memory", "remember", "rotate beta", "--json"])
    assert remember_one.exit_code == 0 and remember_two.exit_code == 0

    id_one = json.loads(remember_one.stdout)["data"]["memory_id"]
    id_two = json.loads(remember_two.stdout)["data"]["memory_id"]

    first_rotate = cli_runner.invoke(
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
    assert first_rotate.exit_code == 0, first_rotate.stdout

    second_rotate = cli_runner.invoke(
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
    assert second_rotate.exit_code == 0, second_rotate.stdout

    for memory_id, expected_text in ((id_one, "rotate alpha"), (id_two, "rotate beta")):
        recalled = cli_runner.invoke(
            ["memory", "recall", memory_id, "--json"],
            env={"MATRIOSHA_PASSPHRASE": "integration-pass-v3"},
        )
        assert recalled.exit_code == 0, recalled.stdout
        payload = json.loads(recalled.stdout)
        plaintext = base64.b64decode(payload["data"]["plaintext_b64"]).decode("utf-8")
        assert plaintext == expected_text
