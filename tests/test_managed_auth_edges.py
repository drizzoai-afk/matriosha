from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from matriosha.core.managed import auth


class _MockAsyncClient:
    responses: list[httpx.Response | Exception] = []
    requests: list[tuple[str, str, dict[str, Any] | None]] = []

    def __init__(self, *, base_url: str, timeout: float):
        self.base_url = base_url
        self.timeout = timeout

    async def __aenter__(self) -> "_MockAsyncClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def post(self, path: str, json: dict[str, Any] | None = None) -> httpx.Response:
        self.requests.append(("POST", path, json))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def request(self, method: str, path: str, json: dict[str, Any] | None = None) -> httpx.Response:
        self.requests.append((method, path, json))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _json_response(status_code: int, payload: object) -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=httpx.Request("POST", "https://example.test/x"))


@pytest.fixture(autouse=True)
def _reset_mock_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _MockAsyncClient.responses = []
    _MockAsyncClient.requests = []
    monkeypatch.setattr(auth.httpx, "AsyncClient", _MockAsyncClient)


@pytest.fixture
def isolated_token_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(auth.platformdirs, "user_data_dir", lambda app: str(tmp_path / "data"))
    monkeypatch.setattr(auth.platformdirs, "user_config_dir", lambda app: str(tmp_path / "config"))


def test_token_store_roundtrip_uses_encrypted_file_and_0600_permissions(isolated_token_store: None) -> None:
    store = auth.TokenStore("default")
    payload = {"access_token": "access", "refresh_token": "refresh", "nested": {"ok": True}}

    store.save(payload)

    assert store.load() == payload
    assert b"access" not in store._path.read_bytes()
    assert store._path.stat().st_mode & 0o777 == 0o600
    assert store._key_path.stat().st_mode & 0o777 == 0o600


def test_token_store_returns_none_when_missing(isolated_token_store: None) -> None:
    assert auth.TokenStore("missing").load() is None


def test_token_store_rejects_too_short_ciphertext(isolated_token_store: None) -> None:
    store = auth.TokenStore("default")
    store._path.parent.mkdir(parents=True)
    store._path.write_bytes(b"short")

    with pytest.raises(auth.TokenStoreError, match="corrupted"):
        store.load()


def test_token_store_rejects_invalid_master_key_size(isolated_token_store: None) -> None:
    store = auth.TokenStore("default")
    store._key_path.parent.mkdir(parents=True)
    store._key_path.write_bytes(b"bad")

    with pytest.raises(auth.TokenStoreError, match="invalid size"):
        store.save({"access_token": "x"})


def test_token_store_rejects_invalid_json_payload(isolated_token_store: None) -> None:
    store = auth.TokenStore("default")
    key = store._master_key()
    nonce = b"n" * 12
    encrypted = auth.AESGCM(key).encrypt(nonce, b"not-json", None)
    store._path.parent.mkdir(parents=True)
    store._path.write_bytes(nonce + encrypted)

    with pytest.raises(auth.TokenStoreError, match="payload is invalid"):
        store.load()


def test_token_store_rejects_non_dict_json_payload(isolated_token_store: None) -> None:
    store = auth.TokenStore("default")
    key = store._master_key()
    nonce = b"n" * 12
    encrypted = auth.AESGCM(key).encrypt(nonce, json.dumps(["not", "dict"]).encode(), None)
    store._path.parent.mkdir(parents=True)
    store._path.write_bytes(nonce + encrypted)

    with pytest.raises(auth.TokenStoreError, match="payload is malformed"):
        store.load()


def test_login_rate_limiter_ignores_corrupt_history_and_clears(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(auth.platformdirs, "user_config_dir", lambda app: str(tmp_path))
    limiter = auth.LoginRateLimiter("default")
    limiter._path.parent.mkdir(parents=True, exist_ok=True)
    limiter._path.write_text("{bad json", encoding="utf-8")

    assert limiter._load() == {"attempts": []}

    limiter.record_attempt()
    assert limiter._recent_attempts() == 1
    assert limiter._path.exists()

    limiter.clear()
    assert not limiter._path.exists()


def test_login_rate_limiter_applies_exponential_backoff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(auth.platformdirs, "user_config_dir", lambda app: str(tmp_path))
    sleeps: list[float] = []
    monkeypatch.setattr(auth.time, "sleep", lambda seconds: sleeps.append(seconds))

    limiter = auth.LoginRateLimiter("default")
    now = auth.time.time()
    limiter._save({"attempts": [now] * limiter.MAX_ATTEMPTS})

    limiter.apply_backoff_if_needed()

    assert sleeps == [1]


def test_email_otp_start_posts_expected_payload() -> None:
    _MockAsyncClient.responses = [_json_response(200, {"challenge": "sent"})]

    result = asyncio.run(auth.EmailOtpFlow("https://api.example/").start("USER@example.com"))

    assert result == {"challenge": "sent"}
    assert _MockAsyncClient.requests[0][1] == "/managed/auth/otp/start"
    assert _MockAsyncClient.requests[0][2]["email"] == "USER@example.com"


def test_email_otp_verify_requires_access_token() -> None:
    _MockAsyncClient.responses = [_json_response(200, {"refresh_token": "refresh"})]

    with pytest.raises(auth.EmailOtpFlowError, match="missing access_token"):
        asyncio.run(auth.EmailOtpFlow("https://api.example").verify(email="u@example.com", code="123456"))


def test_email_otp_verify_maps_token_response() -> None:
    _MockAsyncClient.responses = [
        _json_response(
            200,
            {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 120,
                "token_type": "Bearer",
                "scope": "openid",
            },
        )
    ]

    tokens = asyncio.run(auth.EmailOtpFlow("https://api.example").verify(email="u@example.com", code="123456"))

    assert tokens.access_token == "access"
    assert tokens.refresh_token == "refresh"
    assert tokens.expires_at is not None
    assert tokens.token_type == "Bearer"
    assert tokens.scope == "openid"


def test_email_otp_post_raises_message_for_http_error() -> None:
    _MockAsyncClient.responses = [_json_response(429, {"message": "too many attempts"})]

    with pytest.raises(auth.EmailOtpFlowError, match="too many attempts"):
        asyncio.run(auth.EmailOtpFlow("https://api.example").start("u@example.com"))


def test_device_start_tries_fallback_paths_and_clamps_values() -> None:
    _MockAsyncClient.responses = [
        _json_response(404, {}),
        _json_response(
            200,
            {
                "device_code": "dev",
                "user_code": "USER",
                "verification_uri": "https://verify",
                "interval": 0,
                "expires_in": 1,
                "verification_uri_complete": "https://verify?code=USER",
            },
        ),
    ]

    result = asyncio.run(auth.DeviceCodeFlow("https://api.example/").start())

    assert result.device_code == "dev"
    assert result.interval == 1
    assert result.expires_in == 30
    assert result.verification_uri_complete == "https://verify?code=USER"
    assert [request[1] for request in _MockAsyncClient.requests] == [
        "/oauth/device",
        "/managed/auth/device/start",
    ]


def test_device_start_rejects_malformed_success_payload() -> None:
    _MockAsyncClient.responses = [_json_response(200, {"device_code": "missing required fields"})]

    with pytest.raises(auth.DeviceFlowError, match="malformed"):
        asyncio.run(auth.DeviceCodeFlow("https://api.example").start())


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"error": "authorization_pending"}, "pending"),
        ({"error": "slow_down"}, "slow_down"),
        ({"error": "access_denied"}, "denied"),
    ],
)
def test_device_request_token_maps_oauth_polling_states(payload: dict[str, str], message: str) -> None:
    _MockAsyncClient.responses = [_json_response(400, payload)]

    result = asyncio.run(auth.DeviceCodeFlow("https://api.example")._request_token({"device_code": "dev"}))

    assert result["status"] == message


def test_device_request_token_rejects_expired_token() -> None:
    _MockAsyncClient.responses = [_json_response(400, {"error": "expired_token"})]

    with pytest.raises(auth.DeviceFlowError, match="expired"):
        asyncio.run(auth.DeviceCodeFlow("https://api.example")._request_token({"device_code": "dev"}))


def test_device_poll_rejects_missing_access_token() -> None:
    _MockAsyncClient.responses = [_json_response(200, {"refresh_token": "refresh"})]
    device = auth.DeviceAuthorization("dev", "USER", "https://verify", interval=1, expires_in=30)

    with pytest.raises(auth.DeviceFlowError, match="missing access_token"):
        asyncio.run(auth.DeviceCodeFlow("https://api.example").poll(device))


def test_refresh_managed_tokens_success_uses_first_working_endpoint() -> None:
    _MockAsyncClient.responses = [
        _json_response(404, {}),
        _json_response(200, {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 60}),
    ]

    tokens = asyncio.run(auth.refresh_managed_tokens(base_url="https://api.example/", refresh_token="old-refresh"))

    assert tokens.access_token == "new-access"
    assert tokens.refresh_token == "new-refresh"
    assert [request[1] for request in _MockAsyncClient.requests] == [
        "/managed/auth/refresh",
        "/managed/oauth/token",
    ]


def test_refresh_managed_tokens_rejects_revoked_refresh_token() -> None:
    _MockAsyncClient.responses = [_json_response(401, {"error": "revoked_token"})]

    with pytest.raises(auth.TokenRefreshError, match="invalid or revoked"):
        asyncio.run(auth.refresh_managed_tokens(base_url="https://api.example", refresh_token="bad"))


def test_refresh_profile_tokens_returns_existing_when_not_stale(
    monkeypatch: pytest.MonkeyPatch,
    isolated_token_store: None,
) -> None:
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    payload = {"access_token": "access", "refresh_token": "refresh", "expires_at": future}
    store = auth.TokenStore("default")
    store.save(payload)

    assert auth.refresh_profile_tokens("default") == payload


def test_refresh_profile_tokens_requires_refresh_token_when_stale(isolated_token_store: None) -> None:
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    auth.TokenStore("default").save({"access_token": "access", "expires_at": past})

    with pytest.raises(auth.TokenRefreshError, match="cannot refresh"):
        auth.refresh_profile_tokens("default")


def test_resolve_access_token_prefers_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATRIOSHA_MANAGED_TOKEN", "env-token")

    assert auth.resolve_access_token("default") == "env-token"


def test_resolve_access_token_returns_none_when_store_missing(isolated_token_store: None) -> None:
    assert auth.resolve_access_token("default") is None


def test_resolve_access_token_returns_none_when_stale_refresh_fails(
    monkeypatch: pytest.MonkeyPatch,
    isolated_token_store: None,
) -> None:
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    auth.TokenStore("default").save({"access_token": "old", "refresh_token": "refresh", "expires_at": past})

    def fail_refresh(profile_name: str) -> dict[str, Any]:
        raise auth.TokenRefreshError("boom")

    monkeypatch.setattr(auth, "refresh_profile_tokens", fail_refresh)

    assert auth.resolve_access_token("default") is None


def test_managed_passphrase_helpers(monkeypatch: pytest.MonkeyPatch, isolated_token_store: None) -> None:
    auth.TokenStore("default").save({"managed_passphrase": "stored-passphrase"})

    assert auth.resolve_managed_passphrase("default") == "stored-passphrase"
    assert auth.ensure_process_managed_passphrase("default") == "stored-passphrase"

    monkeypatch.setenv("MATRIOSHA_PASSPHRASE", "env-passphrase")
    assert auth.ensure_process_managed_passphrase("default") == "env-passphrase"


def test_ensure_managed_passphrase_in_payload_preserves_existing_and_generates_missing() -> None:
    existing = {"managed_passphrase": " already "}
    assert auth.ensure_managed_passphrase_in_payload(existing) is existing

    generated = auth.ensure_managed_passphrase_in_payload({"access_token": "x"})
    assert generated["access_token"] == "x"
    assert isinstance(generated["managed_passphrase"], str)
    assert len(generated["managed_passphrase"]) > 20


def test_compute_and_expiry_helpers_cover_invalid_and_naive_inputs() -> None:
    assert auth._optional_str("  x  ") == "x"
    assert auth._optional_str("   ") is None
    assert auth._compute_expires_at("bad", None) is None
    assert auth._compute_expires_at(None, "explicit") == "explicit"

    future_naive = (datetime.now() + timedelta(hours=1)).isoformat()
    future_aware = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    past_aware = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")

    assert auth._is_expired(future_naive) is False
    assert auth._is_expired(future_aware) is False
    assert auth._is_expired(past_aware) is True
    assert auth.is_token_stale(None) is False
    assert auth.is_token_stale("not-a-date") is False


def test_wrap_unwrap_local_blob_roundtrip_and_rejects_bad_blob(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "derive_key", lambda passphrase, salt: b"k" * 32)
    data_key = b"d" * auth.DATA_KEY_LEN
    salt = b"s" * 16

    blob = auth._wrap_data_key_locally(data_key, "passphrase", salt)

    assert auth._unwrap_local_blob(blob, "passphrase", salt) == data_key

    with pytest.raises(auth.KeyCustodyError, match="invalid size"):
        auth._unwrap_local_blob(b"bad", "passphrase", salt)

    bad_magic = b"BAD!" + blob[len(auth.MAGIC) :]
    with pytest.raises(auth.KeyCustodyError, match="magic mismatch"):
        auth._unwrap_local_blob(bad_magic, "passphrase", salt)


def test_recover_data_key_from_remote_unseals_when_local_unwrap_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "_unwrap_local_blob", lambda blob, passphrase, salt: (_ for _ in ()).throw(auth.KeyCustodyError("bad")))

    class Remote:
        async def _request(self, method: str, path: str, json_payload: dict[str, Any]) -> dict[str, str]:
            return {"plaintext_b64": base64.b64encode(b"local-blob").decode("ascii")}

    calls: list[bytes] = []

    def fake_unwrap(blob: bytes, passphrase: str, salt: bytes) -> bytes:
        calls.append(blob)
        if len(calls) == 1:
            raise auth.KeyCustodyError("bad")
        return b"d" * auth.DATA_KEY_LEN

    monkeypatch.setattr(auth, "_unwrap_local_blob", fake_unwrap)

    result = asyncio.run(
        auth._recover_data_key_from_remote(
            remote_client=Remote(),
            wrapped_blob=b"sealed",
            salt=b"s" * 16,
            managed_passphrase="passphrase",
        )
    )

    assert result == b"d" * auth.DATA_KEY_LEN
    assert calls == [b"sealed", b"local-blob"]


def test_write_local_vault_material_uses_secure_writes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    writes: list[tuple[Path, bytes]] = []

    monkeypatch.setattr(auth, "_wrap_data_key_locally", lambda data_key, passphrase, salt: b"wrapped")
    monkeypatch.setattr(auth.Vault, "_write_secure", lambda path, data: writes.append((path, data)))

    key_file = tmp_path / "vault" / "key.bin"
    salt_file = tmp_path / "vault" / "salt.bin"

    auth._write_local_vault_material(
        key_file=key_file,
        salt_file=salt_file,
        data_key=b"d" * auth.DATA_KEY_LEN,
        passphrase="passphrase",
        salt_override=b"s" * 16,
    )

    assert key_file.parent.exists()
    assert writes == [(salt_file, b"s" * 16), (key_file, b"wrapped")]
