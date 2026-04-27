from __future__ import annotations

from matriosha.api import ManagedSearchRequest, managed_search


class _Result:
    def __init__(self, data):
        self.data = data


class _RpcCall:
    def __init__(self, db):
        self._db = db

    def execute(self):
        return _Result(
            [
                {
                    "memory_id": "mem_1",
                    "score": 0.875,
                    "envelope": {"mode": "managed"},
                    "payload_b64": "abc",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ]
        )


class _DB:
    def __init__(self):
        self.rpc_name = None
        self.rpc_params = None
        self.table_called = False

    def rpc(self, name, params):
        self.rpc_name = name
        self.rpc_params = params
        return _RpcCall(self)

    def table(self, name):
        self.table_called = True
        raise AssertionError("embedding search must use pgvector RPC, not table-scan ranking")


def test_managed_search_embedding_uses_pgvector_rpc(monkeypatch):
    db = _DB()
    monkeypatch.setattr("matriosha.api._supabase_service_client", lambda: db)
    monkeypatch.setattr("matriosha.api._require_agent_scope", lambda entitlement, scopes: None)

    response = managed_search(
        ManagedSearchRequest(embedding=[1.0] * 384, limit=5),
        entitlement={"user_id": "user_123"},
    )

    assert db.rpc_name == "match_memory_vectors"
    assert db.rpc_params == {"p_user_id": "user_123", "p_embedding": [1.0] * 384, "p_limit": 5}
    assert db.table_called is False
    assert response["items"][0]["memory_id"] == "mem_1"
    assert response["results"] == response["items"]
