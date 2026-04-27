from __future__ import annotations

import json

from matriosha.core.audit import AuditEvent, AuditJournal, hash_remote_hint, redact


def test_audit_journal_appends_hash_chain_and_verifies(tmp_path):
    journal = AuditJournal("default", root=tmp_path)

    first = journal.append(
        AuditEvent.create(
            profile="default",
            mode="local",
            action="memory.remember",
            target_type="memory",
            target_id="mem_1",
            outcome="success",
        )
    )
    second = journal.append(
        AuditEvent.create(
            profile="default",
            mode="local",
            action="memory.delete",
            target_type="memory",
            target_id="mem_1",
            outcome="success",
        )
    )

    assert first["previous_hash"] is None
    assert second["previous_hash"] == first["event_hash"]
    assert journal.verify() == (True, None)


def test_audit_journal_detects_tampering(tmp_path):
    journal = AuditJournal("default", root=tmp_path)
    journal.append(
        AuditEvent.create(
            profile="default",
            mode="local",
            action="vault.rotate",
            target_type="vault",
            outcome="success",
        )
    )

    record = json.loads(journal.path.read_text(encoding="utf-8"))
    record["outcome"] = "failure"
    journal.path.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")

    ok, reason = journal.verify()
    assert ok is False
    assert reason == "line 1: event hash mismatch"


def test_redaction_removes_secret_values_recursively():
    assert redact(
        {
            "access_token": "abc",
            "nested": {"passphrase": "secret", "safe": "value"},
            "items": [{"api_key": "key"}],
        }
    ) == {
        "access_token": "[REDACTED]",
        "nested": {"passphrase": "[REDACTED]", "safe": "value"},
        "items": [{"api_key": "[REDACTED]"}],
    }


def test_hash_remote_hint_is_stable_without_leaking_value():
    hashed = hash_remote_hint("192.0.2.1")
    assert hashed == hash_remote_hint("192.0.2.1")
    assert hashed != "192.0.2.1"
