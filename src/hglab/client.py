"""Small typed REST client with conservative rate limiting and retries."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class HinterglassError(Exception):
    status_code: int
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class TokenBucket:
    def __init__(self, rate_per_minute: int = 30) -> None:
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
        self.http = http or httpx.Client(base_url=base_url, timeout=18)
        self.bucket = TokenBucket(rate_per_minute)
        self.retries = retries
        self.headers = {"Authorization": "Bearer " + api_key} if api_key else {}

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        for attempt in range(self.retries + 1):
            self.bucket.wait()
            response = self.http.request(method, path, headers=self.headers, **kwargs)
            if (response.status_code == 429 or response.status_code >= 500) and attempt < self.retries:
                time.sleep(min(2**attempt, 8))
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
