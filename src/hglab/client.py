"""Small typed REST client with conservative rate limiting and retries."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class HinterglassError(Exception):
    status_code: int
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class WorldUnreachable(ConnectionError):
    """Hinterglass did not answer (timeouts, refused or dropped connections) after the retries.

    A ``ConnectionError`` (so an ``OSError``): callers that already fall back on network trouble keep
    doing so, and scheduled commands turn it into a warning instead of a failed run (``hglab.outage``).
    """


DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
RETRY_AFTER_CAP = 60.0


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    """Seconds to wait before the next attempt: the world's ``Retry-After`` when it sends one, else a short backoff."""
    header = response.headers.get("Retry-After")
    if header is not None:
        try:
            return min(max(float(header), 1.0), RETRY_AFTER_CAP)
        except ValueError:
            pass
    return float(min(2**attempt, 8))


class TokenBucket:
    def __init__(self, rate_per_minute: int = 30) -> None:
        if rate_per_minute < 1:
            raise ValueError("rate limit must be at least one request per minute")
        self.rate = rate_per_minute / 60
        self.tokens = float(rate_per_minute)
        self.updated = time.monotonic()

    def wait(self) -> None:
        now = time.monotonic()
        self.tokens = min(self.tokens + (now - self.updated) * self.rate, self.rate * 60)
        self.updated = now
        if self.tokens < 1:
            delay = (1 - self.tokens) / self.rate
            time.sleep(delay)
            self.updated = time.monotonic()
            self.tokens = 0
        else:
            self.tokens -= 1


class HinterglassClient:
    def __init__(
        self,
        base_url: str = "https://hinterglass.com",
        api_key: str | None = None,
        *,
        http: httpx.Client | None = None,
        rate_per_minute: int = 30,
        retries: int = 3,
    ) -> None:
        if retries < 0:
            raise ValueError("retries must not be negative")
        self.http = http or httpx.Client(base_url=base_url, timeout=DEFAULT_TIMEOUT)
        self.bucket = TokenBucket(rate_per_minute)
        self.retries = retries
        self.headers = {"Authorization": "Bearer " + api_key} if api_key else {}

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """One request with retries.

        Reads (GET) are retried after a timeout or a dropped connection. An action (POST) is retried only
        when the connection was never made, since after a read timeout it may already have happened in
        the world. A 429 waits for the world's ``Retry-After``; a 5xx backs off. After the last attempt a
        network failure is ``WorldUnreachable``.
        """
        idempotent = method.upper() in {"GET", "HEAD"}
        for attempt in range(self.retries + 1):
            self.bucket.wait()
            try:
                response = self.http.request(method, path, headers=self.headers, **kwargs)
            except httpx.TransportError as exc:
                unsent = isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
                if attempt < self.retries and (idempotent or unsent):
                    time.sleep(min(2 ** (attempt + 1), 20))
                    continue
                raise WorldUnreachable(f"{method} {path}: {type(exc).__name__} after {attempt + 1} attempt(s)") from exc
            if (response.status_code == 429 or response.status_code >= 500) and attempt < self.retries:
                time.sleep(_retry_delay(response, attempt))
                continue
            if not response.is_success:
                try:
                    detail = response.json()
                except ValueError:
                    detail = {}
                raise HinterglassError(
                    response.status_code,
                    str(detail.get("error", "http_error")),
                    str(detail.get("message", "Hinterglass request failed")),
                    detail,
                )
            return response.json()
        raise RuntimeError("unreachable retry state")

    def observe(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/me/observe")

    def act(self, action: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/api/v1/me/act", json=action)

    def verify(self, challenge_id: str, answer: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/api/v1/verify", json={"challenge_id": challenge_id, "answer": answer})

    def public_events(self, **params: Any) -> dict[str, Any]:
        return self.request("GET", "/api/v1/world/events", params=params)

    def public_agents(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/world/agents")

    def public_agent(self, name: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,24}", name):
            raise ValueError("invalid public agent name")
        return self.request("GET", f"/api/v1/world/agents/{name}")

    def public_goals(self, status: str = "open") -> dict[str, Any]:
        return self.request("GET", "/api/v1/world/goals", params={"status": status})

    def public_factions(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/world/factions")

    def rotate_key(self) -> dict[str, Any]:
        return self.request("POST", "/api/v1/me/keys/rotate")
