from __future__ import annotations

import json

import pytest


@pytest.mark.integration
def test_doctor_green_path_reports_expected_checks(
    initialized_vault: str,
    cli_runner: IntegrationCliRunner,
) -> None:
    doctor = cli_runner.invoke(["doctor", "--json", "--test-passphrase", "integration-pass"])
    assert doctor.exit_code == 0, doctor.stdout

    payload = json.loads(doctor.stdout)
    checks = payload["checks"]
    by_name = {item["name"]: item for item in checks}

    expected_checks = {
        "python.version",
        "dependencies",
        "config.file",
        "vault.material",
        "vector.index",
        "managed.auth",
        "managed.subscription",
        "managed.endpoint",
        "crypto.self_test",
        "merkle.self_test",
        "time.drift",
    }
    assert expected_checks.issubset(by_name.keys())
    assert all(item["status"] != "fail" for item in checks)

    assert by_name["vault.material"]["status"] == "ok"
    assert "unlock succeeded" in by_name["vault.material"]["detail"]
    assert by_name["managed.auth"]["status"] == "ok"
    assert "local mode; managed auth check skipped" in by_name["managed.auth"]["detail"]


@pytest.mark.integration
@pytest.mark.adversarial
def test_doctor_red_path_without_vault_reports_actionable_failure(cli_runner: IntegrationCliRunner) -> None:
    doctor = cli_runner.invoke(["doctor", "--json", "--test-passphrase", "integration-pass"])
    assert doctor.exit_code == 10, doctor.stdout

    payload = json.loads(doctor.stdout)
    checks = payload["checks"]
    failures = [item for item in checks if item["status"] == "fail"]
    assert failures

    by_name = {item["name"]: item for item in checks}
    assert by_name["vault.material"]["status"] == "fail"
    assert "vault missing/corrupt" in by_name["vault.material"]["detail"]
    assert "Initialize or repair vault" in by_name["vault.material"]["hint"]
