from __future__ import annotations

import asyncio
import json
from typing import cast

import httpx
import pytest
import respx

import matriosha.core.managed.auth as managed_auth
from matriosha.core.managed.auth import TokenStore, resolve_access_token
from matriosha.core.managed.client import AuthError, ManagedClient, NetworkError, ScopeError
from matriosha.core.binary_protocol import encode_envelope
from matriosha.core.managed.sync import SyncEngine


@pytest.fixture(autouse=True)
def _disable_profile_inference(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATRIOSHA_MANAGED_TOKEN", "env-override-token")


def test_whoami_happy_path() -> None:
    async def _run() -> None:
        with respx.mock(assert_all_mocked=True) as mock:
            route = mock.get("https://managed.example/managed/whoami").mock(
                return_value=httpx.Response(
                    200,
                    json={"user_id": "u_123", "email": "dev@example.com"},
                )
            )

            client = ManagedClient(
                token="token-abc",
                base_url="https://managed.example",
                managed_mode=False,
            )
            try:
                result = await client.whoami()
            finally:
                await client.aclose()

            assert result["user_id"] == "u_123"
            assert route.called

    asyncio.run(_run())


def test_500_retries_three_times_then_raises_network_error() -> None:
    async def _run() -> None:
        with respx.mock(assert_all_mocked=True) as mock:
            route = mock.get("https://managed.example/managed/whoami").mock(
                return_value=httpx.Response(500, json={"error": "temporary"})
            )

            client = ManagedClient(
                token="token-abc",
                base_url="https://managed.example",
                managed_mode=False,
            )
            try:
                with pytest.raises(NetworkError):
                    await client.whoami()
            finally:
                await client.aclose()

            assert route.call_count == 4

    asyncio.run(_run())


def test_upload_memory_sends_expected_json_keys() -> None:
    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json={"id": "mem_42"})

    async def _run() -> None:
        with respx.mock(assert_all_mocked=True) as mock:
            route = mock.post("https://managed.example/managed/memories").mock(side_effect=_capture)

            client = ManagedClient(
                token="token-abc",
                base_url="https://managed.example",
                managed_mode=False,
            )
            try:
                memory_id = await client.upload_memory(
                    envelope={"memory_id": "local-1", "tags": ["ops"]},
                    payload_b64="SGVsbG8=",
                )
            finally:
                await client.aclose()

            assert memory_id == "mem_42"
            assert route.called

    asyncio.run(_run())

    payload = json.loads(cast(str | bytes | bytearray, captured["body"]))
    assert set(payload.keys()) == {"envelope", "payload_b64"}
    assert "embedding" not in payload
    headers = cast(dict[str, str], captured["headers"])
    assert headers["authorization"] == "Bearer token-abc"


def test_upload_memory_omits_embedding_key() -> None:
    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json={"id": "mem_null_vector"})

    async def _run() -> None:
        with respx.mock(assert_all_mocked=True) as mock:
            mock.post("https://managed.example/managed/memories").mock(side_effect=_capture)

            client = ManagedClient(
                token="token-abc",
                base_url="https://managed.example",
                managed_mode=False,
            )
            try:
                memory_id = await client.upload_memory(
                    envelope={"memory_id": "local-1", "tags": ["ops"]},
                    payload_b64="SGVsbG8=",
                )
            finally:
                await client.aclose()

            assert memory_id == "mem_null_vector"

    asyncio.run(_run())

    payload = json.loads(cast(str | bytes | bytearray, captured["body"]))
    assert "embedding" not in payload


def test_search_candidates_sends_metadata_hashes_only_and_clamps_limit() -> None:
    captured: dict[str, object] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "mem-1",
                        "memory_id": "mem-1",
                        "payload_b64": "ZW5jcnlwdGVk",
                        "metadata_hashes": ["hash-alpha"],
                        "score": 1,
                    }
                ],
                "limit": 50,
            },
        )

    async def _run() -> None:
        with respx.mock(assert_all_mocked=True) as mock:
            route = mock.post("https://managed.example/managed/search").mock(side_effect=_capture)

            client = ManagedClient(
                token="token-abc",
                base_url="https://managed.example",
                managed_mode=False,
            )
            try:
                items = await client.search_candidates(
                    [" hash-alpha ", "", "hash-alpha"], limit=200
                )
            finally:
                await client.aclose()

            assert route.called
            assert items[0]["id"] == "mem-1"
            assert items[0]["payload_b64"] == "ZW5jcnlwdGVk"

    asyncio.run(_run())

    payload = json.loads(cast(str | bytes | bytearray, captured["body"]))
    assert payload == {
        "metadata_hashes": ["hash-alpha"],
        "limit": 50,
        "candidate_only": True,
    }
    assert "query" not in payload
    assert "tags" not in payload
    assert "search_keywords" not in payload


def test_auth_failure_401_raises_auth_error_without_retry() -> None:
    async def _run() -> None:
        with respx.mock(assert_all_mocked=True) as mock:
            route = mock.get("https://managed.example/managed/whoami").mock(
                return_value=httpx.Response(401, json={"error": "unauthorized"})
            )

            client = ManagedClient(
                token="token-abc",
                base_url="https://managed.example",
                managed_mode=False,
            )
            try:
                with pytest.raises(AuthError):
                    await client.whoami()
            finally:
                await client.aclose()

            assert route.call_count == 1

    asyncio.run(_run())


def _patch_token_store_dirs(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        managed_auth.platformdirs, "user_data_dir", lambda _app: str(tmp_path / "data")
    )
    monkeypatch.setattr(
        managed_auth.platformdirs, "user_config_dir", lambda _app: str(tmp_path / "cfg")
    )


def test_resolve_access_token_refreshes_expired_token_and_persists_rotation(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("MATRIOSHA_MANAGED_TOKEN", raising=False)
    _patch_token_store_dirs(monkeypatch, tmp_path)

    store = TokenStore("default")
    store.save(
        {
            "access_token": "expired-access",
            "refresh_token": "refresh-old",
            "expires_at": "2000-01-01T00:00:00Z",
            "endpoint": "https://managed.example",
            "profile": "default",
            "updated_at": "2000-01-01T00:00:00Z",
        }
    )

    with respx.mock(assert_all_mocked=True) as mock:
        refresh_route = mock.post("https://managed.example/managed/auth/refresh").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": "access-new",
                    "refresh_token": "refresh-rotated",
                    "expires_in": 3600,
                    "token_type": "bearer",
                    "scope": "openid profile",
                },
            )
        )

        token = resolve_access_token("default")

    assert token == "access-new"
    assert refresh_route.called
    persisted = store.load() or {}
    assert persisted.get("access_token") == "access-new"
    assert persisted.get("refresh_token") == "refresh-rotated"
    assert isinstance(persisted.get("updated_at"), str)


def test_managed_client_preflight_refresh_then_request_success(monkeypatch, tmp_path) -> None:
    _patch_token_store_dirs(monkeypatch, tmp_path)

    store = TokenStore("default")
    store.save(
        {
            "access_token": "expired-access",
            "refresh_token": "refresh-stable",
            "expires_at": "2000-01-01T00:00:00Z",
            "endpoint": "https://managed.example",
            "profile": "default",
        }
    )

    async def _run() -> None:
        with respx.mock(assert_all_mocked=True) as mock:
            mock.post("https://managed.example/managed/auth/refresh").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "access_token": "fresh-access",
                        "expires_in": 3600,
                        "token_type": "bearer",
                    },
                )
            )
            route = mock.get("https://managed.example/managed/whoami").mock(
                return_value=httpx.Response(200, json={"user_id": "u_refresh"})
            )

            client = ManagedClient(
                token="expired-access",
                base_url="https://managed.example",
                managed_mode=False,
                profile_name="default",
            )
            try:
                result = await client.whoami()
            finally:
                await client.aclose()

            assert route.called
            assert result["user_id"] == "u_refresh"

    asyncio.run(_run())
    persisted = store.load() or {}
    assert persisted.get("access_token") == "fresh-access"
    assert persisted.get("refresh_token") == "refresh-stable"


def test_managed_client_401_then_refresh_then_retry_success(monkeypatch, tmp_path) -> None:
    _patch_token_store_dirs(monkeypatch, tmp_path)

    store = TokenStore("default")
    store.save(
        {
            "access_token": "token-old",
            "refresh_token": "refresh-401",
            "expires_at": "2999-01-01T00:00:00Z",
            "endpoint": "https://managed.example",
            "profile": "default",
        }
    )

    async def _run() -> None:
        with respx.mock(assert_all_mocked=True) as mock:
            route = mock.get("https://managed.example/managed/whoami").mock(
                side_effect=[
                    httpx.Response(401, json={"error": "expired"}),
                    httpx.Response(200, json={"user_id": "u_retry"}),
                ]
            )
            mock.post("https://managed.example/managed/auth/refresh").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "access_token": "token-new",
                        "refresh_token": "refresh-next",
                        "expires_in": 3600,
                    },
                )
            )

            client = ManagedClient(
                token="token-old",
                base_url="https://managed.example",
                managed_mode=False,
                profile_name="default",
            )
            try:
                result = await client.whoami()
            finally:
                await client.aclose()

            assert result["user_id"] == "u_retry"
            assert route.call_count == 2

    asyncio.run(_run())
    persisted = store.load() or {}
    assert persisted.get("refresh_token") == "refresh-next"


def test_managed_client_refresh_failure_raises_actionable_auth_error(monkeypatch, tmp_path) -> None:
    _patch_token_store_dirs(monkeypatch, tmp_path)

    store = TokenStore("default")
    store.save(
        {
            "access_token": "token-old",
            "refresh_token": "refresh-revoked",
            "expires_at": "2000-01-01T00:00:00Z",
            "endpoint": "https://managed.example",
            "profile": "default",
        }
    )

    async def _run() -> None:
        with respx.mock(assert_all_mocked=True) as mock:
            mock.post("https://managed.example/managed/auth/refresh").mock(
                return_value=httpx.Response(400, json={"error": "invalid_grant"})
            )

            client = ManagedClient(
                token="token-old",
                base_url="https://managed.example",
                managed_mode=False,
                profile_name="default",
            )
            try:
                with pytest.raises(AuthError) as exc:
                    await client.whoami()
            finally:
                await client.aclose()

            assert "matriosha auth login" in exc.value.remediation
            assert exc.value.code == "AUTH-002"

    asyncio.run(_run())


def test_managed_client_expired_without_refresh_token_fails_predictably(
    monkeypatch, tmp_path
) -> None:
    _patch_token_store_dirs(monkeypatch, tmp_path)

    store = TokenStore("default")
    store.save(
        {
            "access_token": "token-expired",
            "expires_at": "2000-01-01T00:00:00Z",
            "endpoint": "https://managed.example",
            "profile": "default",
        }
    )

    async def _run() -> None:
        client = ManagedClient(
            token="token-expired",
            base_url="https://managed.example",
            managed_mode=False,
            profile_name="default",
        )
        try:
            with pytest.raises(AuthError) as exc:
                await client.whoami()
        finally:
            await client.aclose()

        assert "matriosha auth login" in exc.value.remediation
        assert exc.value.code == "AUTH-002"

    asyncio.run(_run())


def test_managed_client_403_insufficient_scope_unchanged() -> None:
    async def _run() -> None:
        with respx.mock(assert_all_mocked=True) as mock:
            mock.get("https://managed.example/managed/whoami").mock(
                return_value=httpx.Response(
                    403,
                    json={
                        "error": {
                            "code": "insufficient_scope",
                            "required_scope": "admin",
                            "provided_scope": "read",
                        }
                    },
                )
            )

            client = ManagedClient(
                token="token-abc",
                base_url="https://managed.example",
                managed_mode=False,
            )
            try:
                with pytest.raises(ScopeError):
                    await client.whoami()
            finally:
                await client.aclose()

    asyncio.run(_run())


def test_sync_engine_does_not_upload_raw_embedding(tmp_path) -> None:
    data_key = b"x" * 32
    env, payload_b64 = encode_envelope(
        b"private semantic text",
        data_key,
        mode="managed",
        tags=["privacy"],
    )

    class FakeLocal:
        root = str(tmp_path)

        def list(self, limit: int):
            return [env]

        def get(self, memory_id: str):
            assert memory_id == env.memory_id
            return env, payload_b64

    class RecordingRemote:
        def __init__(self) -> None:
            self.records: dict[str, tuple[dict, str]] = {}
            self.upload_calls: list[dict[str, object]] = []

        async def upload_memory(self, **kwargs):
            assert "embedding" not in kwargs
            envelope = kwargs["envelope"]
            payload_b64 = kwargs["payload_b64"]
            remote_id = f"remote-{len(self.records) + 1}"
            self.records[remote_id] = (envelope, payload_b64)
            self.upload_calls.append(kwargs)
            return remote_id

        async def fetch_memory(self, memory_id: str):
            return self.records[memory_id]

    class ExplodingEmbedder:
        def embed(self, text: str):
            raise AssertionError("embedder should not run for managed upload in local vector mode")

    local = FakeLocal()
    remote = RecordingRemote()
    engine = SyncEngine(
        local=local,  # type: ignore[arg-type]
        remote=remote,  # type: ignore[arg-type]
        embedder=ExplodingEmbedder(),  # type: ignore[arg-type]
        data_key=data_key,
    )

    report = asyncio.run(engine.push())

    assert report.errors == []
    assert report.pushed == 1
    assert len(remote.upload_calls) == 1
    assert "embedding" not in remote.upload_calls[0]


def test_sync_engine_push_deletes_remote_when_local_memory_removed(tmp_path) -> None:
    data_key = b"x" * 32
    env, payload_b64 = encode_envelope(
        b"delete me",
        data_key,
        mode="managed",
        tags=["delete-probe"],
    )

    class FakeLocal:
        def __init__(self) -> None:
            self.root = str(tmp_path)
            self.exists = True

        def list(self, limit: int):
            return [env] if self.exists else []

        def get(self, memory_id: str):
            assert memory_id == env.memory_id
            if not self.exists:
                raise FileNotFoundError(memory_id)
            return env, payload_b64

    class RecordingRemote:
        def __init__(self) -> None:
            self.records: dict[str, tuple[dict, str]] = {}
            self.deleted: list[str] = []

        async def upload_memory(self, *, envelope, payload_b64, metadata_hashes=None):
            remote_id = "remote-delete-1"
            self.records[remote_id] = (envelope, payload_b64)
            return remote_id

        async def delete_memory(self, memory_id: str):
            self.deleted.append(memory_id)
            self.records.pop(memory_id, None)
            return True

    class ExplodingEmbedder:
        def embed(self, text: str):
            raise AssertionError("embedder should not run for managed upload in local vector mode")

    local = FakeLocal()
    remote = RecordingRemote()
    engine = SyncEngine(
        local=local,  # type: ignore[arg-type]
        remote=remote,  # type: ignore[arg-type]
        embedder=ExplodingEmbedder(),  # type: ignore[arg-type]
        data_key=data_key,
    )

    first = asyncio.run(engine.push())
    assert first.errors == []
    assert first.pushed == 1
    assert list(remote.records) == ["remote-delete-1"]

    local.exists = False
    second = asyncio.run(engine.push())

    assert second.errors == []
    assert second.pushed == 0
    assert remote.deleted == ["remote-delete-1"]
    assert remote.records == {}
