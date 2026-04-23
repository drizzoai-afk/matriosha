from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx

from core.managed.client import AuthError, ManagedClient, NetworkError


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
                    embedding=[0.1, 0.2, 0.3],
                )
            finally:
                await client.aclose()

            assert memory_id == "mem_42"
            assert route.called

    asyncio.run(_run())

    payload = json.loads(captured["body"])
    assert set(payload.keys()) == {"embedding", "envelope", "payload_b64"}
    assert captured["headers"]["authorization"] == "Bearer token-abc"


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
