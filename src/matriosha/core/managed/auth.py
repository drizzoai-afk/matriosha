"""Managed authentication + token/session storage + key bootstrap helpers."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import platformdirs
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from matriosha.core.crypto import decrypt, derive_key, encrypt, generate_salt
from matriosha.core.managed.key_custody import KeyCustodyError, fetch_wrapped_key, upload_wrapped_key
from matriosha.core.vault import DATA_KEY_LEN, MAGIC, NONCE_LEN, TAG_LEN, Vault


class DeviceFlowError(RuntimeError):
    """Structured device-flow failure."""


class EmailOtpFlowError(RuntimeError):
    """Structured email OTP authentication failure."""


class TokenStoreError(RuntimeError):
    """Structured token-store failure."""


@dataclass(frozen=True)
class DeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int
    verification_uri_complete: str | None = None


@dataclass(frozen=True)
class ManagedTokens:
    access_token: str
    refresh_token: str | None
    expires_at: str | None
    token_type: str = "bearer"
    scope: str | None = None
    managed_passphrase: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "token_type": self.token_type,
            "scope": self.scope,
            "managed_passphrase": self.managed_passphrase,
        }


class TokenStore:
    """Profile-scoped encrypted token store."""

    def __init__(self, profile_name: str):
        self.profile_name = profile_name
        data_root = Path(platformdirs.user_data_dir("matriosha")) / profile_name
        cfg_root = Path(platformdirs.user_config_dir("matriosha"))
        self._path = data_root / "managed_tokens.enc"
        self._key_path = cfg_root / "managed_token_store.key"

    def load(self) -> dict[str, Any] | None:
        if not self._path.exists():
            return None

        key = self._master_key()
        raw = self._path.read_bytes()
        if len(raw) < 12 + 16:
            raise TokenStoreError("token store is corrupted")

        nonce, payload = raw[:12], raw[12:]
        try:
            plaintext = AESGCM(key).decrypt(nonce, payload, None)
        except Exception as exc:  # noqa: BLE001
            raise TokenStoreError("token store decryption failed") from exc

        try:
            parsed = json.loads(plaintext.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise TokenStoreError("token store payload is invalid") from exc

        if not isinstance(parsed, dict):
            raise TokenStoreError("token store payload is malformed")
        return parsed

    def save(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        key = self._master_key()
        nonce = os.urandom(12)
        plaintext = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)

        tmp_path = self._path.with_name(f"{self._path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        tmp_path.write_bytes(nonce + ciphertext)
        os.replace(tmp_path, self._path)
        if os.name != "nt":
            os.chmod(self._path, 0o600)

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)

    def _master_key(self) -> bytes:
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._key_path.exists():
            self._key_path.write_bytes(os.urandom(32))
            if os.name != "nt":
                os.chmod(self._key_path, 0o600)

        key = self._key_path.read_bytes()
        if len(key) != 32:
            raise TokenStoreError("token-store master key has invalid size")
        return key


_DEVICE_CODE_TOKEN_PATHS = (
    "/managed/auth/device/poll",
    "/managed/oauth/token",
)

_REFRESH_TOKEN_PATHS = (
    "/managed/auth/refresh",
    "/managed/oauth/token",
)

_REFRESH_CLOCK_SKEW_SECONDS = 60


class TokenRefreshError(RuntimeError):
    """Structured refresh-token failure."""


class LoginRateLimiter:
    WINDOW_SECONDS = 60
    MAX_ATTEMPTS = 5

    def __init__(self, profile_name: str):
        path = Path(platformdirs.user_config_dir("matriosha")) / f"auth_login_attempts.{profile_name}.json"
        self._path = path

    def apply_backoff_if_needed(self) -> None:
        attempts = self._recent_attempts()
        if attempts < self.MAX_ATTEMPTS:
            return
        delay = min(32, 2 ** (attempts - self.MAX_ATTEMPTS))
        time.sleep(delay)

    def record_attempt(self) -> None:
        now = time.time()
        history = [ts for ts in self._load().get("attempts", []) if now - float(ts) <= self.WINDOW_SECONDS]
        history.append(now)
        self._save({"attempts": history})

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)

    def _recent_attempts(self) -> int:
        now = time.time()
        history = [ts for ts in self._load().get("attempts", []) if now - float(ts) <= self.WINDOW_SECONDS]
        self._save({"attempts": history})
        return len(history)

    def _load(self) -> dict[str, list[float]]:
        if not self._path.exists():
            return {"attempts": []}
        try:
            parsed = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {"attempts": []}
        attempts = parsed.get("attempts") if isinstance(parsed, dict) else []
        if not isinstance(attempts, list):
            return {"attempts": []}
        return {"attempts": [float(v) for v in attempts]}

    def _save(self, payload: dict[str, list[float]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        if os.name != "nt":
            os.chmod(self._path, 0o600)


class EmailOtpFlow:
    """Email OTP login helper for terminal-first managed auth."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def start(self, email: str) -> dict[str, Any]:
        payload = {
            "email": email,
            "client_id": "matriosha-cli",
            "scope": "openid profile email offline_access",
            "audience": "matriosha-managed",
        }
        data = await self._post("/managed/auth/otp/start", payload)
        return dict(data)

    async def verify(self, *, email: str, code: str) -> ManagedTokens:
        payload = {
            "email": email,
            "code": code,
            "client_id": "matriosha-cli",
        }
        data = await self._post("/managed/auth/otp/verify", payload)

        access_token = _optional_str(data.get("access_token"))
        if not access_token:
            raise EmailOtpFlowError("OTP verification response is missing access_token")

        return ManagedTokens(
            access_token=access_token,
            refresh_token=_optional_str(data.get("refresh_token")),
            expires_at=_compute_expires_at(data.get("expires_in"), data.get("expires_at")),
            token_type=_optional_str(data.get("token_type")) or "bearer",
            scope=_optional_str(data.get("scope")),
        )

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds) as client:
                response = await client.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise EmailOtpFlowError("could not reach managed auth endpoint") from exc

        data = _safe_json(response)
        if response.status_code >= 400:
            err = data.get("error") if isinstance(data, dict) else None
            message = data.get("message") if isinstance(data, dict) else None
            raise EmailOtpFlowError(str(message or err or f"auth endpoint failed: {response.status_code}"))

        if not isinstance(data, dict):
            raise EmailOtpFlowError("auth endpoint returned non-json payload")
        return data


class DeviceCodeFlow:
    """OAuth device authorization grant helper."""

    _START_PATHS = (
        "/oauth/device",
        "/managed/auth/device/start",
        "/managed/oauth/device",
    )
    _TOKEN_PATHS = _DEVICE_CODE_TOKEN_PATHS

    def __init__(self, base_url: str, *, timeout_seconds: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def start(self) -> DeviceAuthorization:
        payload = {
            "client_id": "matriosha-cli",
            "scope": "openid profile email offline_access",
            "audience": "matriosha-managed",
        }
        data = await self._request_first_ok("POST", self._START_PATHS, payload)

        try:
            auth = DeviceAuthorization(
                device_code=str(data["device_code"]),
                user_code=str(data["user_code"]),
                verification_uri=str(data["verification_uri"]),
                interval=max(1, int(data.get("interval", 5))),
                expires_in=max(30, int(data.get("expires_in", 600))),
                verification_uri_complete=(
                    str(data.get("verification_uri_complete"))
                    if data.get("verification_uri_complete")
                    else None
                ),
            )
        except Exception as exc:  # noqa: BLE001
            raise DeviceFlowError("device authorization response is malformed") from exc
        return auth

    async def poll(self, auth: DeviceAuthorization) -> ManagedTokens:
        started = time.monotonic()
        interval = max(1, auth.interval)

        while time.monotonic() - started <= auth.expires_in:
            payload = {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": auth.device_code,
                "client_id": "matriosha-cli",
            }
            response = await self._request_token(payload)

            if response.get("status") == "pending":
                await asyncio.sleep(interval)
                continue
            if response.get("status") == "slow_down":
                interval += 2
                await asyncio.sleep(interval)
                continue
            if response.get("status") == "denied":
                raise DeviceFlowError("device authorization was denied")

            access_token = str(response.get("access_token") or "")
            if not access_token:
                raise DeviceFlowError("device flow token response is missing access_token")

            expires_at = _compute_expires_at(response.get("expires_in"), response.get("expires_at"))
            return ManagedTokens(
                access_token=access_token,
                refresh_token=_optional_str(response.get("refresh_token")),
                expires_at=expires_at,
                token_type=_optional_str(response.get("token_type")) or "bearer",
                scope=_optional_str(response.get("scope")),
            )

        raise DeviceFlowError("device authorization timed out")

    async def _request_token(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for path in self._TOKEN_PATHS:
            try:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds) as client:
                    response = await client.post(path, json=payload)
            except httpx.HTTPError as exc:
                last_error = exc
                continue

            body = _safe_json(response)
            if response.status_code == 200:
                return body
            if response.status_code in {400, 401}:
                err = str(body.get("error") or "").lower()
                if err in {"authorization_pending", "pending", "device_authorization_pending"}:
                    return {"status": "pending"}
                if err in {"slow_down"}:
                    return {"status": "slow_down"}
                if err in {"access_denied", "authorization_declined"}:
                    return {"status": "denied"}
                if err in {"expired_token", "authorization_expired"}:
                    raise DeviceFlowError("device authorization expired; run auth login again")
                # unknown oauth-ish 400 means endpoint exists but failed.
                raise DeviceFlowError(f"device token poll failed: {err or 'bad_request'}")

            if response.status_code == 404:
                continue
            raise DeviceFlowError(f"device token endpoint failed: http_status={response.status_code}")

        if last_error is not None:
            raise DeviceFlowError("could not reach managed auth token endpoint") from last_error
        raise DeviceFlowError("managed auth token endpoint not found")

    async def _request_first_ok(self, method: str, paths: tuple[str, ...], payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for path in paths:
            try:
                async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds) as client:
                    response = await client.request(method, path, json=payload)
            except httpx.HTTPError as exc:
                last_error = exc
                continue

            if response.status_code == 404:
                continue
            if response.status_code >= 400:
                body = _safe_json(response)
                err = body.get("error") if isinstance(body, dict) else None
                raise DeviceFlowError(f"device authorization failed: {err or response.status_code}")

            data = _safe_json(response)
            if not isinstance(data, dict):
                raise DeviceFlowError("device authorization returned non-json payload")
            return data

        if last_error is not None:
            raise DeviceFlowError("could not reach managed device authorization endpoint") from last_error
        raise DeviceFlowError("managed device authorization endpoint not found")


async def refresh_managed_tokens(
    *,
    base_url: str,
    refresh_token: str,
    timeout_seconds: float = 15.0,
) -> ManagedTokens:
    """Exchange a refresh token for a new managed access token."""

    last_error: Exception | None = None
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": "matriosha-cli",
    }

    for path in _REFRESH_TOKEN_PATHS:
        try:
            async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_seconds) as client:
                response = await client.post(path, json=payload)
        except httpx.HTTPError as exc:
            last_error = exc
            continue

        data = _safe_json(response)
        if response.status_code == 200:
            access_token = _optional_str(data.get("access_token"))
            if not access_token:
                raise TokenRefreshError("managed token refresh response is missing access_token")
            return ManagedTokens(
                access_token=access_token,
                refresh_token=_optional_str(data.get("refresh_token")),
                expires_at=_compute_expires_at(data.get("expires_in"), data.get("expires_at")),
                token_type=_optional_str(data.get("token_type")) or "bearer",
                scope=_optional_str(data.get("scope")),
            )

        if response.status_code in {400, 401}:
            err = _optional_str(data.get("error")) or "invalid_request"
            if err.lower() in {"invalid_grant", "invalid_token", "revoked_token", "access_denied"}:
                raise TokenRefreshError("refresh token is invalid or revoked; run `matriosha auth login`")
            raise TokenRefreshError(f"managed token refresh failed: {err}")

        if response.status_code == 404:
            continue

        raise TokenRefreshError(f"managed refresh endpoint failed: http_status={response.status_code}")

    if last_error is not None:
        raise TokenRefreshError("could not reach managed auth token endpoint") from last_error
    raise TokenRefreshError("managed auth token endpoint not found")


def refresh_profile_tokens(
    profile_name: str,
    *,
    force: bool = False,
    endpoint: str | None = None,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Refresh and persist profile-scoped managed tokens when needed."""

    store = TokenStore(profile_name)
    payload = store.load()
    if not payload:
        raise TokenRefreshError("managed session token missing; run `matriosha auth login`")

    existing_access_token = _optional_str(payload.get("access_token"))
    expires_at = _optional_str(payload.get("expires_at"))
    is_stale = is_token_stale(expires_at)
    if not force and existing_access_token and not is_stale:
        return payload

    refresh_token = _optional_str(payload.get("refresh_token"))
    if not refresh_token:
        raise TokenRefreshError("managed session expired and cannot refresh; run `matriosha auth login`")

    resolved_endpoint = (
        _optional_str(endpoint)
        or _optional_str(payload.get("endpoint"))
        or _optional_str(os.getenv("MATRIOSHA_MANAGED_ENDPOINT"))
    )
    if not resolved_endpoint:
        raise TokenRefreshError("managed endpoint missing for refresh; run `matriosha auth login`")

    refreshed = asyncio.run(
        refresh_managed_tokens(base_url=resolved_endpoint, refresh_token=refresh_token, timeout_seconds=timeout_seconds)
    )

    persisted = dict(payload)
    persisted["access_token"] = refreshed.access_token
    persisted["refresh_token"] = refreshed.refresh_token or refresh_token
    persisted["expires_at"] = refreshed.expires_at
    if refreshed.token_type:
        persisted["token_type"] = refreshed.token_type
    if refreshed.scope:
        persisted["scope"] = refreshed.scope
    persisted["endpoint"] = _optional_str(payload.get("endpoint")) or resolved_endpoint
    persisted["profile"] = _optional_str(payload.get("profile")) or profile_name
    persisted["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    store.save(persisted)
    return persisted


async def ensure_managed_key_bootstrap(remote_client: Any, *, profile_name: str, managed_passphrase: str) -> dict[str, Any]:
    """Ensure managed key custody + local vault files are present and usable."""

    # Fast-path: local vault already unlocks.
    try:
        Vault.unlock(profile_name, managed_passphrase)
        return {"status": "existing", "source": "local"}
    except Exception:  # noqa: BLE001
        pass

    key_file, salt_file = Vault._paths(profile_name)

    # Try remote recovery path.
    try:
        salt, wrapped_blob = await fetch_wrapped_key(remote_client)
        data_key = await _recover_data_key_from_remote(
            remote_client=remote_client,
            wrapped_blob=wrapped_blob,
            salt=salt,
            managed_passphrase=managed_passphrase,
        )
        _write_local_vault_material(
            key_file=key_file,
            salt_file=salt_file,
            data_key=data_key,
            passphrase=managed_passphrase,
            salt_override=salt,
        )
        return {"status": "existing", "source": "remote"}
    except Exception:  # noqa: BLE001
        pass

    # First-time bootstrap: generate key, upload custody, write local files.
    data_key = os.urandom(DATA_KEY_LEN)
    salt = generate_salt(16)
    wrapped_local = _wrap_data_key_locally(data_key, managed_passphrase, salt)

    wrapped_for_upload = wrapped_local
    algo = "aes-gcm"

    # Prefer server-side sealing if edge function exposes it.
    try:
        resp = await remote_client._request(
            "POST",
            "/functions/v1/vault-custody",
            json_payload={
                "action": "seal",
                "plaintext_b64": base64.b64encode(wrapped_local).decode("ascii"),
            },
        )
        sealed_b64 = resp.get("sealed_b64") if isinstance(resp, dict) else None
        if isinstance(sealed_b64, str) and sealed_b64:
            wrapped_for_upload = base64.b64decode(sealed_b64)
            algo = "sealedbox+aead-aes-gcm"
    except Exception:  # noqa: BLE001
        pass

    await upload_wrapped_key(remote_client, salt, wrapped_for_upload)
    _write_local_vault_material(
        key_file=key_file,
        salt_file=salt_file,
        data_key=data_key,
        passphrase=managed_passphrase,
        salt_override=salt,
    )
    return {"status": "created", "source": "generated", "algo": algo}


def resolve_access_token(profile_name: str) -> str | None:
    env_token = os.getenv("MATRIOSHA_MANAGED_TOKEN")
    if env_token:
        return env_token

    store = TokenStore(profile_name)
    payload = store.load()
    if not payload:
        return None

    token = _optional_str(payload.get("access_token"))
    if not token:
        return None

    expires_at = _optional_str(payload.get("expires_at"))
    if is_token_stale(expires_at):
        try:
            refreshed = refresh_profile_tokens(profile_name)
            refreshed_token = _optional_str(refreshed.get("access_token"))
            return refreshed_token
        except (TokenRefreshError, TokenStoreError, RuntimeError):
            return None
    return token


def resolve_managed_passphrase(profile_name: str) -> str | None:
    store = TokenStore(profile_name)
    payload = store.load()
    if not payload:
        return None
    return _optional_str(payload.get("managed_passphrase"))


def ensure_process_managed_passphrase(profile_name: str) -> str | None:
    existing = os.getenv("MATRIOSHA_PASSPHRASE")
    if existing:
        return existing
    managed = resolve_managed_passphrase(profile_name)
    if managed:
        os.environ["MATRIOSHA_PASSPHRASE"] = managed
    return managed


def ensure_managed_passphrase_in_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if _optional_str(payload.get("managed_passphrase")):
        return payload
    payload = dict(payload)
    payload["managed_passphrase"] = secrets.token_urlsafe(48)
    return payload


async def _recover_data_key_from_remote(
    *, remote_client: Any, wrapped_blob: bytes, salt: bytes, managed_passphrase: str
) -> bytes:
    # Case 1: blob already local-wrap shape.
    try:
        return _unwrap_local_blob(wrapped_blob, managed_passphrase, salt)
    except Exception:  # noqa: BLE001
        pass

    # Case 2: sealed-box wrapper stored; ask edge function to unseal.
    try:
        response = await remote_client._request(
            "POST",
            "/functions/v1/vault-custody",
            json_payload={
                "action": "unseal",
                "sealed_b64": base64.b64encode(wrapped_blob).decode("ascii"),
            },
        )
        plaintext_b64 = response.get("plaintext_b64") if isinstance(response, dict) else None
        if not isinstance(plaintext_b64, str) or not plaintext_b64:
            raise KeyCustodyError("unseal response missing plaintext")
        local_blob = base64.b64decode(plaintext_b64)
        return _unwrap_local_blob(local_blob, managed_passphrase, salt)
    except Exception as exc:  # noqa: BLE001
        raise KeyCustodyError("unable to recover managed wrapped key") from exc


def _wrap_data_key_locally(data_key: bytes, passphrase: str, salt: bytes) -> bytes:
    kek = derive_key(passphrase, salt)
    nonce, ciphertext = encrypt(data_key, kek)
    return MAGIC + nonce + ciphertext


def _unwrap_local_blob(blob: bytes, passphrase: str, salt: bytes) -> bytes:
    if len(blob) != len(MAGIC) + NONCE_LEN + DATA_KEY_LEN + TAG_LEN:
        raise KeyCustodyError("wrapped key blob has invalid size")
    if not blob.startswith(MAGIC):
        raise KeyCustodyError("wrapped key blob magic mismatch")

    nonce = blob[len(MAGIC) : len(MAGIC) + NONCE_LEN]
    ciphertext = blob[len(MAGIC) + NONCE_LEN :]
    kek = derive_key(passphrase, salt)
    data_key = decrypt(nonce, ciphertext, kek)
    if len(data_key) != DATA_KEY_LEN:
        raise KeyCustodyError("decrypted data key has invalid size")
    return data_key


def _write_local_vault_material(
    *, key_file: Path, salt_file: Path, data_key: bytes, passphrase: str, salt_override: bytes | None = None
) -> None:
    salt = salt_override if salt_override is not None else generate_salt(16)
    wrapped = _wrap_data_key_locally(data_key, passphrase, salt)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    Vault._write_secure(salt_file, salt)
    Vault._write_secure(key_file, wrapped)


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _compute_expires_at(expires_in: Any, expires_at: Any) -> str | None:
    if expires_at:
        return str(expires_at)
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    dt = datetime.now(timezone.utc).timestamp() + max(1, seconds)
    return datetime.fromtimestamp(dt, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def is_token_stale(expires_at: str | None, *, clock_skew_seconds: int = _REFRESH_CLOCK_SKEW_SECONDS) -> bool:
    if not expires_at:
        return False
    return _is_expired(expires_at, clock_skew_seconds=clock_skew_seconds)


def _is_expired(iso_ts: str, *, clock_skew_seconds: int = 0) -> bool:
    try:
        parsed = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    threshold = datetime.now(timezone.utc).timestamp() + max(0, int(clock_skew_seconds))
    return parsed.timestamp() <= threshold
