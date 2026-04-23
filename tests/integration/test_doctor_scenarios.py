from __future__ import annotations

import json

import pytest


@pytest.mark.integration
def test_doctor_green_path(initialized_vault: str, cli_runner: IntegrationCliRunner) -> None:
    doctor = cli_runner.invoke(["doctor", "--json", "--test-passphrase", "integration-pass"])
    assert doctor.exit_code == 0, doctor.stdout
    payload = json.loads(doctor.stdout)
    statuses = {item["status"] for item in payload["checks"]}
    assert "fail" not in statuses


@pytest.mark.integration
@pytest.mark.adversarial
def test_doctor_red_path_without_vault(cli_runner: IntegrationCliRunner) -> None:
    doctor = cli_runner.invoke(["doctor", "--json"])
    assert doctor.exit_code == 10, doctor.stdout
    payload = json.loads(doctor.stdout)
    failures = [item for item in payload["checks"] if item["status"] == "fail"]
    assert failures
