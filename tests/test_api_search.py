from __future__ import annotations

import pytest
from fastapi import HTTPException

from matriosha.api import ManagedSearchRequest, managed_search


def test_managed_search_is_disabled(monkeypatch):
    monkeypatch.setattr("matriosha.api._require_agent_scope", lambda entitlement, scopes: None)

    with pytest.raises(HTTPException) as exc:
        managed_search(
            ManagedSearchRequest(embedding=[1.0] * 384, limit=5),
            entitlement={"user_id": "user_123"},
        )

    assert exc.value.status_code == 410
    assert "local retrieval" in str(exc.value.detail).lower()
