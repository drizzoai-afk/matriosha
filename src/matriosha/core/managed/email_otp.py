"""Email OTP flow client for managed authentication."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import httpx


class EmailOtpFlowError(RuntimeError):
    """Raised when the managed email OTP flow fails."""


@dataclass(frozen=True)
class EmailOtpTokens:
    """Tokens returned by the managed OTP verification endpoint."""

    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None
    token_type: str = "bearer"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class EmailOtpFlow:
    """Small HTTP client for starting and verifying email OTP login."""

    def __init__(self, endpoint: str, *, timeout: float = 20.0):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    async def start(self, email: str) -> None:
        """Request that the backend sends an OTP login code to the email address."""

        payload = {"email": email}
        await self._post("/managed/auth/otp/start", payload)

    async def verify(self, *, email: str, code: str) -> EmailOtpTokens:
        """Verify an OTP login code and return session tokens."""

        payload = {"email": email, "code": code}
        data = await self._post("/managed/auth/otp/verify", payload)

        access_token = data.get("access_token") or data.get("token")
        if not access_token:
            raise EmailOtpFlowError("OTP verification response did not include an access token")

        expires_raw = data.get("expires_in")
        try:
            expires_in = int(expires_raw) if expires_raw is not None else None
        except (TypeError, ValueError):
            expires_in = None

        return EmailOtpTokens(
            access_token=str(access_token),
            refresh_token=str(data.get("refresh_token")) if data.get("refresh_token") else None,
            expires_in=expires_in,
            token_type=str(data.get("token_type") or "bearer"),
        )

    async def _post(self, path: str, payload: dict[str, str]) -> dict[str, Any]:
        url = f"{self.endpoint}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            raise EmailOtpFlowError(f"OTP request failed: {exc}") from exc

        if response.status_code >= 400:
            raise EmailOtpFlowError(self._error_message(response))

        try:
            data = response.json()
        except ValueError as exc:
            raise EmailOtpFlowError("OTP response was not valid JSON") from exc

        if not isinstance(data, dict):
            raise EmailOtpFlowError("OTP response was not a JSON object")
        return data

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text

        detail: Any
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("message") or payload.get("error")
        else:
            detail = payload

        message = str(detail).strip() if detail is not None else ""
        return message or f"OTP request failed with HTTP {response.status_code}"
