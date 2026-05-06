import base64
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import matriosha.api as api


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self._rows)


class _Db:
    def __init__(self, *, memories):
        self.memories = memories

    def table(self, name):
        if name == "memories":
            return _Query(self.memories)
        if name == "vault_keys":
            return _Query([{"vault_secret_name": "secret/user", "algo": "aes-gcm"}])
        raise AssertionError(f"unexpected table: {name}")


def test_managed_agent_recall_decrypts_then_interprets_selected_memories(monkeypatch):
    decode_calls = []
    interpreter_calls = []

    memories = [
        {
            "id": "mem_1",
            "envelope": {"id": "env_1", "tags": ["profile"]},
            "payload_b64": base64.b64encode(b"encrypted-1").decode("ascii"),
            "tags": ["profile"],
            "safe_metadata": {"source": "test"},
        }
    ]

    monkeypatch.setattr(api, "_supabase_service_client", lambda: _Db(memories=memories))
    monkeypatch.setattr(api, "_managed_data_key_from_passphrase", lambda **_kwargs: b"x" * 32)

    def fake_envelope_from_json(_value):
        return SimpleNamespace(tags=["profile"], filename=None, mime_type=None, content_kind=None)

    def fake_decode_envelope(env, payload, key):
        decode_calls.append((env, payload, key))
        return b"decrypted memory text"

    def fake_decode_semantic_content(payload, metadata=None):
        interpreter_calls.append((payload, metadata))
        return {
            "text": payload.decode("utf-8"),
            "preview": payload.decode("utf-8")[:20],
            "metadata": metadata or {},
        }

    monkeypatch.setattr(api, "envelope_from_json", fake_envelope_from_json)
    monkeypatch.setattr(api, "decode_envelope", fake_decode_envelope)
    monkeypatch.setattr(api, "decode_semantic_content", fake_decode_semantic_content)

    response = api.managed_agent_recall(
        api.ManagedAgentRecallRequest(
            memory_ids=["mem_1"],
            k=5,
            managed_passphrase="passphrase",
        ),
        entitlement={"user_id": "user_1"},
    )

    assert response["k"] == 5
    assert response["items"][0]["memory_id"] == "mem_1"
    assert response["items"][0]["text"] == "decrypted memory text"
    assert response["items"][0]["semantic"]["text"] == "decrypted memory text"
    assert "payload_b64" not in response["items"][0]
    assert len(decode_calls) == 1
    assert decode_calls[0][1] == base64.b64encode(b"encrypted-1").decode("ascii").encode("ascii")
    assert decode_calls[0][2] == b"x" * 32
    assert interpreter_calls == [
        (
            b"decrypted memory text",
            {
                "filename": None,
                "mime_type": None,
                "content_kind": None,
                "tags": ["profile"],
            },
        )
    ]


def test_managed_agent_recall_uses_agent_token_key_without_passphrase(monkeypatch):
    decode_calls = []

    memories = [
        {
            "id": "mem_token",
            "envelope": {"id": "env_token", "tags": ["agent"]},
            "payload_b64": base64.b64encode(b"encrypted-token").decode("ascii"),
            "tags": ["agent"],
            "safe_metadata": {},
        }
    ]

    monkeypatch.setattr(api, "_supabase_service_client", lambda: _Db(memories=memories))
    monkeypatch.setattr(api, "_managed_data_key_from_agent_token", lambda **_kwargs: b"t" * 32)

    def fail_passphrase_path(**_kwargs):
        raise AssertionError("passphrase path should not be used for agent token recall")

    monkeypatch.setattr(api, "_managed_data_key_from_passphrase", fail_passphrase_path)
    monkeypatch.setattr(
        api,
        "envelope_from_json",
        lambda _value: SimpleNamespace(
            tags=["agent"], filename=None, mime_type=None, content_kind=None
        ),
    )

    def fake_decode_envelope(_env, payload, key):
        decode_calls.append((payload, key))
        return b"agent token decrypted"

    monkeypatch.setattr(api, "decode_envelope", fake_decode_envelope)
    monkeypatch.setattr(
        api,
        "decode_semantic_content",
        lambda payload, metadata=None: {
            "text": payload.decode("utf-8"),
            "preview": payload.decode("utf-8"),
        },
    )

    response = api.managed_agent_recall(
        api.ManagedAgentRecallRequest(
            memory_ids=["mem_token"],
            k=5,
        ),
        entitlement={
            "auth_kind": "agent",
            "user_id": "user_1",
            "agent_token_hash": "hash_1",
            "agent_plaintext_token": "mt_plaintext",
        },
    )

    assert response["items"][0]["memory_id"] == "mem_token"
    assert response["items"][0]["text"] == "agent token decrypted"
    assert decode_calls == [
        (
            base64.b64encode(b"encrypted-token").decode("ascii").encode("ascii"),
            b"t" * 32,
        )
    ]


def test_managed_agent_recall_clamps_and_dedupes_before_decrypt(monkeypatch):
    decode_calls = []

    memories = [
        {
            "id": f"mem_{i}",
            "envelope": {"id": f"env_{i}", "tags": []},
            "payload_b64": base64.b64encode(f"encrypted-{i}".encode()).decode("ascii"),
            "tags": [],
            "safe_metadata": {},
        }
        for i in range(10)
    ]

    monkeypatch.setattr(api, "_supabase_service_client", lambda: _Db(memories=memories))
    monkeypatch.setattr(api, "_managed_data_key_from_passphrase", lambda **_kwargs: b"x" * 32)
    monkeypatch.setattr(
        api,
        "envelope_from_json",
        lambda _value: SimpleNamespace(tags=[], filename=None, mime_type=None, content_kind=None),
    )

    def fake_decode_envelope(_env, payload, _key):
        decode_calls.append(payload)
        return b"decrypted"

    monkeypatch.setattr(api, "decode_envelope", fake_decode_envelope)
    monkeypatch.setattr(
        api,
        "decode_semantic_content",
        lambda payload, metadata=None: {
            "text": payload.decode("utf-8"),
            "preview": payload.decode("utf-8"),
        },
    )

    response = api.managed_agent_recall(
        api.ManagedAgentRecallRequest(
            memory_ids=[
                "mem_0",
                "mem_0",
                "mem_1",
                "mem_2",
                "mem_3",
                "mem_4",
                "mem_5",
                "mem_6",
            ],
            k=50,
            managed_passphrase="passphrase",
        ),
        entitlement={"user_id": "user_1"},
    )

    assert response["k"] == 5
    assert [item["memory_id"] for item in response["items"]] == [
        "mem_0",
        "mem_1",
        "mem_2",
        "mem_3",
        "mem_4",
    ]
    assert len(decode_calls) == 5


def test_managed_agent_recall_requires_memory_ids():
    with pytest.raises(HTTPException) as exc_info:
        api.managed_agent_recall(
            api.ManagedAgentRecallRequest(
                memory_ids=[],
                k=5,
                managed_passphrase="passphrase",
            ),
            entitlement={"user_id": "user_1"},
        )

    assert exc_info.value.status_code == 400
    assert "memory_ids" in exc_info.value.detail
