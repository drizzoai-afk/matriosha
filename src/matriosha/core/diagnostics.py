"""System diagnostics checks for `matriosha status` and `matriosha doctor`."""

from __future__ import annotations

import importlib
import os
import sys
import socket
import ssl
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import certifi
import platformdirs

from matriosha.core.config import MatrioshaConfig, Profile, load_config
from matriosha.core.crypto import decrypt, encrypt
from matriosha.core.managed.client import ManagedClient, ManagedClientError, resolve_managed_endpoint
from matriosha.core.merkle import merkle_root
from matriosha.core.vault import Vault, VaultError
from matriosha.core.vectors import LocalVectorIndex

CheckStatus = Literal["ok", "warn", "fail"]

_REQUIRED_IMPORTS: tuple[tuple[str, str], ...] = (
    ("typer", "typer"),
    ("rich", "rich"),
    ("cryptography", "cryptography"),
    ("argon2", "argon2-cffi"),
    ("nacl", "pynacl"),
    ("requests", "requests"),
    ("httpx", "httpx"),
    ("certifi", "certifi"),
    ("supabase", "supabase"),
    ("pydantic", "pydantic"),
    ("jax", "jax"),
    ("platformdirs", "platformdirs"),
)

_ACTIVE_SUBSCRIPTION = {"active", "trialing"}

_MERKLE_LEAVES = [
    "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb",
    "3e23e8160039594a33894f6564e1b1348bbd7a0088d42c4acb73eeaed59c009d",
    "2e7d2c03a9507ae265ecf5b5356885a53393a2029d241394997265a1a25aefc6",
]
_MERKLE_EXPECTED_ROOT = "d31a37ef6ac14a2db1470c4316beb5592e6afd4465022339adafda76a18ffabe"


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True)
class DiagnosticsResult:
    checks: list[CheckResult]
    profile: Profile


def run_diagnostics(
    *,
    profile_name_override: str | None = None,
    include_passphrase_unlock: bool,
    test_passphrase: str | None = None,
) -> DiagnosticsResult:
    """Run all health checks and return collected results."""

    checks: list[CheckResult] = []

    checks.append(_check_python_version())
    checks.append(_check_dependencies())

    config_check, cfg = _check_config_file()
    checks.append(config_check)

    profile = _resolve_profile(cfg, profile_name_override)

    checks.append(
        _check_vault(
            profile_name=profile.name,
            include_unlock=include_passphrase_unlock,
            test_passphrase=test_passphrase,
        )
    )
    checks.append(_check_local_vector_index(profile_name=profile.name))

    if profile.mode == "managed":
        endpoint = resolve_managed_endpoint(profile.managed_endpoint, os.getenv("MATRIOSHA_MANAGED_ENDPOINT"))
        checks.append(_check_managed_endpoint(endpoint))
        checks.append(_check_managed_auth(endpoint))
        checks.append(_check_managed_subscription(endpoint))
    else:
        checks.append(CheckResult("managed.auth", "ok", "local mode; managed auth check skipped"))
        checks.append(CheckResult("managed.subscription", "ok", "local mode; managed billing check skipped"))
        checks.append(CheckResult("managed.endpoint", "ok", "local mode; managed endpoint check skipped"))

    checks.append(_check_crypto_self_test())
    checks.append(_check_merkle_self_test())
    checks.append(_check_time_drift())

    return DiagnosticsResult(checks=checks, profile=profile)


def _check_python_version() -> CheckResult:
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 11):
        return CheckResult("python.version", "ok", f"python {major}.{minor}")
    return CheckResult("python.version", "fail", f"python {major}.{minor} detected; requires >= 3.11")


def _check_dependencies() -> CheckResult:
    missing: list[str] = []
    for module_name, package_name in _REQUIRED_IMPORTS:
        try:
            importlib.import_module(module_name)
        except Exception:
            missing.append(package_name)

    if missing:
        return CheckResult("dependencies", "fail", f"missing import(s): {', '.join(sorted(missing))}")
    return CheckResult("dependencies", "ok", "all required imports succeeded")


def _check_config_file() -> tuple[CheckResult, MatrioshaConfig]:
    config_path = Path(platformdirs.user_config_dir("matriosha")) / "config.toml"

    if not config_path.exists():
        cfg = load_config()
        if not config_path.exists():
            return CheckResult("config.file", "fail", f"missing config at {config_path}"), cfg

    try:
        import tomllib

        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
        cfg = MatrioshaConfig.model_validate(raw)
    except Exception as exc:
        cfg = load_config()
        return CheckResult("config.file", "fail", f"config parse/validation failed: {exc.__class__.__name__}"), cfg

    if os.name != "nt":
        file_mode = config_path.stat().st_mode & 0o777
        if file_mode != 0o600:
            return CheckResult("config.file", "fail", f"permissions are {oct(file_mode)} (expected 0o600)"), cfg

    return CheckResult("config.file", "ok", f"{config_path} is readable with secure permissions"), cfg


def _resolve_profile(cfg: MatrioshaConfig, profile_name_override: str | None) -> Profile:
    profile_name = profile_name_override or cfg.active_profile
    profile = cfg.profiles.get(profile_name)
    if profile is not None:
        return profile

    fallback = cfg.profiles.get("default")
    if fallback is not None:
        return fallback

    return Profile(name="default", mode="local")


def _check_vault(*, profile_name: str, include_unlock: bool, test_passphrase: str | None) -> CheckResult:
    try:
        Vault.validate_material(profile_name)
    except Exception as exc:
        return CheckResult("vault.material", "fail", f"vault missing/corrupt for profile '{profile_name}': {exc}")

    if not include_unlock:
        return CheckResult("vault.material", "ok", "vault files valid; unlock check skipped")

    resolved_passphrase = test_passphrase or os.getenv("MATRIOSHA_TEST_PASSPHRASE") or os.getenv("MATRIOSHA_PASSPHRASE")
    if not resolved_passphrase:
        return CheckResult("vault.material", "warn", "vault exists; unlock skipped (no --test-passphrase or env provided)")

    try:
        Vault.unlock(profile_name, resolved_passphrase)
    except VaultError as exc:
        return CheckResult("vault.material", "fail", f"vault unlock failed: {exc}")

    return CheckResult("vault.material", "ok", "vault exists and unlock succeeded")


def _check_local_vector_index(*, profile_name: str) -> CheckResult:
    try:
        LocalVectorIndex(profile_name)
    except Exception as exc:
        return CheckResult("vector.index", "fail", f"local vector index unreadable: {exc}")
    return CheckResult("vector.index", "ok", "local vector index readable")


def _check_managed_endpoint(endpoint: str | None) -> CheckResult:
    if not endpoint:
        return CheckResult("managed.endpoint", "fail", "managed endpoint missing (profile.managed_endpoint)")

    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        return CheckResult("managed.endpoint", "fail", "managed endpoint must be a valid https URL")

    host = parsed.hostname
    port = parsed.port or 443

    try:
        socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        return CheckResult("managed.endpoint", "fail", f"DNS resolution failed for {host}:{port} ({exc})")

    context = ssl.create_default_context(cafile=certifi.where())
    try:
        with socket.create_connection((host, port), timeout=3.0) as raw_sock:
            with context.wrap_socket(raw_sock, server_hostname=host):
                pass
    except OSError as exc:
        return CheckResult("managed.endpoint", "fail", f"TLS handshake failed for {host}:{port} ({exc})")

    return CheckResult("managed.endpoint", "ok", f"DNS+TLS reachable for {host}:{port}")


def _check_managed_auth(endpoint: str | None) -> CheckResult:
    token = os.getenv("MATRIOSHA_MANAGED_TOKEN", "").strip()
    if not token:
        return CheckResult("managed.auth", "fail", "MATRIOSHA_MANAGED_TOKEN is missing")

    try:
        payload = _run_async(_managed_whoami(token=token, endpoint=endpoint))
    except ManagedClientError as exc:
        return CheckResult("managed.auth", "fail", f"whoami failed: {exc.category}/{exc.code}")
    except Exception as exc:
        return CheckResult("managed.auth", "fail", f"whoami failed: {exc.__class__.__name__}")

    if isinstance(payload, dict):
        user = payload.get("email") or payload.get("user_id") or payload.get("id") or "unknown"
        return CheckResult("managed.auth", "ok", f"whoami succeeded (user={user})")
    return CheckResult("managed.auth", "ok", "whoami succeeded")


def _check_managed_subscription(endpoint: str | None) -> CheckResult:
    token = os.getenv("MATRIOSHA_MANAGED_TOKEN", "").strip()
    if not token:
        return CheckResult("managed.subscription", "fail", "cannot verify subscription without MATRIOSHA_MANAGED_TOKEN")

    try:
        payload = _run_async(_managed_subscription(token=token, endpoint=endpoint))
    except ManagedClientError as exc:
        return CheckResult("managed.subscription", "fail", f"subscription check failed: {exc.category}/{exc.code}")
    except Exception as exc:
        return CheckResult("managed.subscription", "fail", f"subscription check failed: {exc.__class__.__name__}")

    status = str(payload.get("status") or "unknown").lower()
    if status in _ACTIVE_SUBSCRIPTION:
        return CheckResult("managed.subscription", "ok", f"subscription status={status}")
    return CheckResult("managed.subscription", "fail", f"subscription status={status} (expected active/trialing)")


def _check_crypto_self_test() -> CheckResult:
    key = bytes.fromhex("11" * 32)
    plaintext = b"matriosha-crypto-self-test"
    aad = b"diag"

    try:
        nonce, ct = encrypt(plaintext, key, aad)
        recovered = decrypt(nonce, ct, key, aad)
    except Exception as exc:
        return CheckResult("crypto.self_test", "fail", f"AES-GCM self-test failed: {exc}")

    if recovered != plaintext:
        return CheckResult("crypto.self_test", "fail", "AES-GCM self-test mismatch after decrypt")

    return CheckResult("crypto.self_test", "ok", "AES-GCM encrypt/decrypt known vector passed")


def _check_merkle_self_test() -> CheckResult:
    try:
        root = merkle_root(_MERKLE_LEAVES)
    except Exception as exc:
        return CheckResult("merkle.self_test", "fail", f"Merkle root computation failed: {exc}")

    if root != _MERKLE_EXPECTED_ROOT:
        return CheckResult("merkle.self_test", "fail", "Merkle root mismatch for known leaves")

    return CheckResult("merkle.self_test", "ok", "known leaves produced expected Merkle root")


def _check_time_drift() -> CheckResult:
    try:
        ntp_epoch = _fetch_ntp_epoch("time.google.com", timeout=1.5)
    except Exception as exc:
        return CheckResult("time.drift", "warn", f"skipped (NTP unavailable: {exc.__class__.__name__})")

    drift_seconds = abs(time.time() - ntp_epoch)
    if drift_seconds < 30:
        return CheckResult("time.drift", "ok", f"clock drift {drift_seconds:.2f}s (<30s)")
    return CheckResult("time.drift", "fail", f"clock drift {drift_seconds:.2f}s (>=30s)")


def _fetch_ntp_epoch(host: str, *, timeout: float) -> float:
    packet = bytearray(48)
    packet[0] = 0x1B

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(packet, (host, 123))
        data, _ = sock.recvfrom(48)

    if len(data) < 48:
        raise ValueError("short NTP response")

    ntp_seconds, ntp_fraction = struct.unpack("!II", data[40:48])
    epoch_seconds = ntp_seconds - 2_208_988_800
    fraction_seconds = ntp_fraction / 2**32
    return epoch_seconds + fraction_seconds


async def _managed_whoami(*, token: str, endpoint: str | None) -> dict[str, object]:
    async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
        return await client.whoami()


async def _managed_subscription(*, token: str, endpoint: str | None) -> dict[str, object]:
    async with ManagedClient(token=token, base_url=endpoint, managed_mode=False) as client:
        return await client.get_subscription()


def _run_async(coro):
    import asyncio

    return asyncio.run(coro)
