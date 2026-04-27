from __future__ import annotations

import json

from typer.testing import CliRunner

from matriosha.cli.main import app
from matriosha.core import audit as audit_module
from matriosha.core import config as config_module
from matriosha.core.audit import AuditEvent, AuditJournal

runner = CliRunner()


def _patch_dirs(monkeypatch, tmp_path):
    config_root = tmp_path / ".config" / "matriosha"
    data_root = tmp_path / ".local" / "share" / "matriosha"
    monkeypatch.setattr(config_module.platformdirs, "user_config_dir", lambda appname: str(config_root))
    monkeypatch.setattr(audit_module.platformdirs, "user_data_dir", lambda appname: str(data_root))
    return data_root


def test_audit_verify_json_success(monkeypatch, tmp_path):
    data_root = _patch_dirs(monkeypatch, tmp_path)
    journal = AuditJournal("default", root=data_root / "default")
    journal.append(
        AuditEvent.create(
            profile="default",
            mode="local",
            action="memory.remember",
            target_type="memory",
            target_id="mem_1",
            outcome="success",
        )
    )

    result = runner.invoke(app, ["audit", "verify", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "ok"
    assert payload["operation"] == "audit.verify"
    assert payload["data"]["valid"] is True


def test_audit_verify_json_tamper_failure(monkeypatch, tmp_path):
    data_root = _patch_dirs(monkeypatch, tmp_path)
    journal = AuditJournal("default", root=data_root / "default")
    journal.append(
        AuditEvent.create(
            profile="default",
            mode="local",
            action="memory.delete",
            target_type="memory",
            target_id="mem_1",
            outcome="success",
        )
    )
    record = json.loads(journal.path.read_text(encoding="utf-8"))
    record["outcome"] = "failure"
    journal.path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    result = runner.invoke(app, ["audit", "verify", "--json"])

    assert result.exit_code == 10
    payload = json.loads(result.stdout)
    assert payload["status"] == "error"
    assert payload["data"]["valid"] is False
    assert payload["error"]["code"] == "INT-901"
