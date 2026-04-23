from __future__ import annotations

import json
import uuid

import pytest


@pytest.mark.integration
@pytest.mark.managed
def test_token_lifecycle_real_backend(cli_runner: IntegrationCliRunner, managed_profile: dict[str, str]) -> None:
    token_env = {
        "MATRIOSHA_MANAGED_TOKEN": managed_profile["token"],
        "MATRIOSHA_MANAGED_ENDPOINT": managed_profile["endpoint"],
    }

    login = cli_runner.invoke(["auth", "login", "--json"], env=token_env)
    assert login.exit_code == 99, login.stdout

    token_name = f"itest-{uuid.uuid4().hex[:10]}"
    generated = cli_runner.invoke(
        ["token", "generate", token_name, "--scope", "write", "--expires", "30m", "--json"],
        env=token_env,
    )
    assert generated.exit_code == 0, generated.stdout
    generated_payload = json.loads(generated.stdout)
    token_id = generated_payload["id"]

    listed = cli_runner.invoke(["token", "list", "--json"], env=token_env)
    assert listed.exit_code == 0, listed.stdout
    listed_payload = json.loads(listed.stdout)
    matched = [row for row in listed_payload if row["id"] == token_id]
    assert matched, f"Token {token_id} not found in token list"

    revoked = cli_runner.invoke(["token", "revoke", token_id[:12], "--yes", "--json"], env=token_env)
    assert revoked.exit_code == 0, revoked.stdout

    inspected = cli_runner.invoke(["token", "inspect", token_id[:12], "--json"], env=token_env)
    assert inspected.exit_code == 0, inspected.stdout
    inspected_payload = json.loads(inspected.stdout)
    assert inspected_payload["id"] == token_id
    assert inspected_payload["revoked"] is True
