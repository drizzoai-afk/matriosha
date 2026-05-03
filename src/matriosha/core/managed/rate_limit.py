"""Small local rate limiter for managed login attempts."""

from __future__ import annotations

import json
import time

from matriosha.core.paths import data_dir


class LoginRateLimiter:
    """Track repeated login attempts and apply a short local backoff."""

    def __init__(self, profile_name: str, *, max_attempts: int = 5, window_seconds: int = 300):
        self.profile_name = profile_name
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        root = data_dir()
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / f"login-rate-{profile_name}.json"

    def apply_backoff_if_needed(self) -> None:
        attempts = self._recent_attempts()
        if len(attempts) < self.max_attempts:
            return
        time.sleep(min(2.0, 0.25 * (len(attempts) - self.max_attempts + 1)))

    def record_attempt(self) -> None:
        attempts = self._recent_attempts()
        attempts.append(time.time())
        self._write_attempts(attempts)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def _recent_attempts(self) -> list[float]:
        cutoff = time.time() - self.window_seconds
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

        if not isinstance(raw, list):
            return []

        attempts: list[float] = []
        for value in raw:
            try:
                timestamp = float(value)
            except (TypeError, ValueError):
                continue
            if timestamp >= cutoff:
                attempts.append(timestamp)
        return attempts

    def _write_attempts(self, attempts: list[float]) -> None:
        try:
            self.path.write_text(json.dumps(attempts[-50:]), encoding="utf-8")
        except OSError:
            return
