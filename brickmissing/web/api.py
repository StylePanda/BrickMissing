from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def payload(self) -> dict[str, Any]:
        return {"ok": False, "code": self.code, "error": self.message}


class SlidingWindowRateLimiter:
    def __init__(self):
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, seconds: int) -> None:
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - seconds:
                events.popleft()
            if len(events) >= limit:
                raise ApiError(
                    "RATE_LIMITED",
                    "Zu viele Anfragen. Bitte kurz warten.",
                    429,
                )
            events.append(now)


class ServiceContainer:
    """Small dependency container keeping server modules independently testable."""

    def __init__(self):
        self.rate_limiter = SlidingWindowRateLimiter()


class RequestValidator:
    JSON_TYPES = {"application/json", "application/merge-patch+json"}

    @staticmethod
    def content_length(headers: Any, maximum: int) -> int:
        try:
            length = int(str(headers.get("Content-Length", "0")).strip())
        except ValueError as exc:
            raise ApiError("INVALID_LENGTH", "Ungültige Anfragegröße.", 400) from exc
        if length < 0 or length > maximum:
            raise ApiError("PAYLOAD_TOO_LARGE", "Die Anfrage ist zu groß.", 413)
        return length

    @classmethod
    def require_json(cls, headers: Any, has_body: bool) -> None:
        if not has_body:
            return
        content_type = str(headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
        if content_type not in cls.JSON_TYPES:
            raise ApiError("UNSUPPORTED_MEDIA_TYPE", "Es wird JSON erwartet.", 415)
