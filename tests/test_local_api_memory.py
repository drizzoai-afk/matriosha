from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from matriosha.core.local_api.app import create_local_app
from matriosha.core.local_tokens import create_local_agent_token
from matriosha.core.vault import Vault


def _headers(token: str, passphrase: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if passphrase is not None:
        headers["X-Matriosha-Vault-Passphrase"] = passphrase
    return headers


def test_local_api_memory_crud_search_and_scope(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("platformdirs.user_data_dir", lambda appname: str(tmp_path / appname))

    profile_name = "default"
    passphrase = "correct horse battery staple"
    Vault.init(profile_name, passphrase)

    writer = create_local_agent_token(
        profile_name=profile_name,
        name="writer-agent",
        scope="write",
        expires_at=None,
    )
    reader = create_local_agent_token(
        profile_name=profile_name,
        name="reader-agent",
        scope="read",
        expires_at=None,
    )

    client = TestClient(create_local_app(profile_name=profile_name))

    missing_token = client.get("/memories")
    assert missing_token.status_code == 401

    created = client.post(
        "/memories",
        headers=_headers(writer["token"], passphrase),
        json={"text": "Daniele is validating local API memory access.", "tags": ["agent", "local"]},
    )
    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["status"] == "ok"
    assert created_payload["bytes"] == len("Daniele is validating local API memory access.".encode("utf-8"))
    assert created_payload["tags"] == ["agent", "local"]
    memory_id = created_payload["memory_id"]

    listed = client.get("/memories", headers=_headers(reader["token"]))
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["status"] == "ok"
    assert [item["memory_id"] for item in listed_payload["memories"]] == [memory_id]

    recalled = client.get(
        f"/memories/{memory_id}",
        headers=_headers(reader["token"], passphrase),
    )
    assert recalled.status_code == 200
    recalled_memory = recalled.json()["memory"]
    assert recalled_memory["memory_id"] == memory_id
    assert base64.b64decode(recalled_memory["plaintext_b64"]).decode("utf-8") == (
        "Daniele is validating local API memory access."
    )
    assert "validating local API" in recalled_memory["preview"]

    wrong_passphrase = client.get(
        f"/memories/{memory_id}",
        headers=_headers(reader["token"], "wrong passphrase"),
    )
    assert wrong_passphrase.status_code == 401
    assert "passphrase" in wrong_passphrase.json()["detail"]

    revoked_reader_search = client.get(
        "/memories/search",
        params={"q": "local API validation", "k": 3},
        headers=_headers(reader["token"], passphrase),
    )
    assert revoked_reader_search.status_code == 403
    assert "revoked" in revoked_reader_search.json()["detail"].lower()

    replacement_reader = create_local_agent_token(
        profile_name=profile_name,
        name="replacement-reader-agent",
        scope="read",
        expires_at=None,
    )

    searched = client.get(
        "/memories/search",
        params={"q": "local API validation", "k": 3},
        headers=_headers(replacement_reader["token"], passphrase),
    )
    assert searched.status_code == 200
    results = searched.json()["results"]
    assert results
    assert results[0]["memory_id"] == memory_id
    assert results[0]["tags"] == ["agent", "local"]

    read_delete = client.delete(f"/memories/{memory_id}", headers=_headers(replacement_reader["token"]))
    assert read_delete.status_code == 403

    deleted = client.delete(f"/memories/{memory_id}", headers=_headers(writer["token"]))
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True

    listed_after_delete = client.get("/memories", headers=_headers(replacement_reader["token"]))
    assert listed_after_delete.status_code == 200
    assert listed_after_delete.json()["memories"] == []


def test_local_api_memory_requires_write_scope_for_create(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("platformdirs.user_data_dir", lambda appname: str(tmp_path / appname))

    profile_name = "default"
    passphrase = "correct horse battery staple"
    Vault.init(profile_name, passphrase)

    reader = create_local_agent_token(
        profile_name=profile_name,
        name="reader-agent",
        scope="read",
        expires_at=None,
    )

    client = TestClient(create_local_app(profile_name=profile_name))

    response = client.post(
        "/memories",
        headers=_headers(reader["token"], passphrase),
        json={"text": "This should not be written.", "tags": ["local"]},
    )

    assert response.status_code == 403
    assert "scope" in response.json()["detail"].lower()
