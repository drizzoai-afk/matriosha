from __future__ import annotations
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from tests.integration.conftest import IntegrationCliRunner
import json
import uuid

import pytest


@pytest.mark.integration
@pytest.mark.managed
def test_token_lifecycle_login_generate_list_inspect_revoke(
    cli_runner: IntegrationCliRunner,
    managed_profile: dict[str, str],
) -> None:
    """Exercise the full token lifecycle with deterministic state assertions."""

    token_env = {
        "MATRIOSHA_MANAGED_TOKEN": managed_profile["token"],
        "MATRIOSHA_MANAGED_ENDPOINT": managed_profile["endpoint"],
    }

    whoami = cli_runner.invoke(["auth", "whoami", "--json"], env=token_env)
    assert whoami.exit_code == 0, whoami.stdout
    whoami_payload = json.loads(whoami.stdout)
    assert whoami_payload["status"] == "ok"

    token_name = f"p71b-token-{uuid.uuid4().hex[:10]}"
    generated = cli_runner.invoke(
        ["token", "generate", token_name, "--scope", "write", "--expires", "30m", "--json"],
        env=token_env,
    )
    assert generated.exit_code == 0, generated.stdout
    generated_payload = json.loads(generated.stdout)

    token_id = str(generated_payload["id"])
    assert token_id
    assert generated_payload["name"] == token_name
    assert generated_payload["scope"] == "write"
    assert str(generated_payload["token"])
    assert generated_payload["expires_at"] != "-"

    listed_before = cli_runner.invoke(["token", "list", "--json"], env=token_env)
    assert listed_before.exit_code == 0, listed_before.stdout
    listed_before_payload = json.loads(listed_before.stdout)
    rows_before = [row for row in listed_before_payload if row["id"] == token_id]
    assert len(rows_before) == 1
    assert rows_before[0]["name"] == token_name
    assert rows_before[0]["scope"] == "write"
    assert rows_before[0]["revoked"] is False

    inspected_before = cli_runner.invoke(["token", "inspect", token_id[:12], "--json"], env=token_env)
    assert inspected_before.exit_code == 0, inspected_before.stdout
    inspected_before_payload = json.loads(inspected_before.stdout)
    assert inspected_before_payload["id"] == token_id
    assert inspected_before_payload["name"] == token_name
    assert inspected_before_payload["scope"] == "write"
    assert inspected_before_payload["revoked"] is False
    assert "token" not in inspected_before_payload

    revoked = cli_runner.invoke(["token", "revoke", token_id[:12], "--yes", "--json"], env=token_env)
    assert revoked.exit_code == 0, revoked.stdout
    revoked_payload = json.loads(revoked.stdout)
    assert revoked_payload == {"id": token_id, "revoked": True, "status": "ok"}

    listed_after = cli_runner.invoke(["token", "list", "--json"], env=token_env)
    assert listed_after.exit_code == 0, listed_after.stdout
    listed_after_payload = json.loads(listed_after.stdout)
    rows_after = [row for row in listed_after_payload if row["id"] == token_id]
    assert len(rows_after) == 1
    assert rows_after[0]["revoked"] is True

    inspected_after = cli_runner.invoke(["token", "inspect", token_id[:12], "--json"], env=token_env)
    assert inspected_after.exit_code == 0, inspected_after.stdout
    inspected_after_payload = json.loads(inspected_after.stdout)
    assert inspected_after_payload["id"] == token_id
    assert inspected_after_payload["revoked"] is True
