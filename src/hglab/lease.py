"""Notebook-backed identity leases with read-after-write race detection."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

LEASE_KEY = "_lease"
LEASE_TTL = timedelta(minutes=8)


class NotebookClient(Protocol):
    def observe(self) -> dict[str, Any]: ...

    def act(self, action: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Lease:
    holder: str
    run_id: str
    expires_utc: datetime


def _current_lease(observe: dict[str, Any]) -> dict[str, Any] | None:
    value = (observe.get("notebook") or {}).get(LEASE_KEY)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def acquire(client: NotebookClient, holder: str, now: datetime | None = None) -> Lease | None:
    now = now or datetime.now(UTC)
    existing = _current_lease(client.observe())
    if existing:
        try:
            expiry = datetime.fromisoformat(existing["expires_utc"])
        except (KeyError, ValueError, TypeError):
            expiry = now
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        if expiry > now:
            return None
    lease = Lease(holder, str(uuid.uuid4()), now + LEASE_TTL)
    payload = json.dumps(
        {"holder": lease.holder, "run_id": lease.run_id, "expires_utc": lease.expires_utc.isoformat()}
    )
    result = client.act({"action": "remember", "key": LEASE_KEY, "text": payload})
    if not result.get("ok", True):
        return None
    confirmed = _current_lease(client.observe())
    if not confirmed or confirmed.get("holder") != holder or confirmed.get("run_id") != lease.run_id:
        return None
    return lease


def release(client: NotebookClient, lease: Lease) -> bool:
    """Forget the lease if it is still ours. Never raises: it runs in ``finally`` blocks, and a lease the
    world could not be told about expires by itself after ``LEASE_TTL``."""
    from hglab.client import HinterglassError

    try:
        current = _current_lease(client.observe())
        if not current or current.get("holder") != lease.holder or current.get("run_id") != lease.run_id:
            return False
        result = client.act({"action": "forget", "key": LEASE_KEY})
    except (ConnectionError, HinterglassError):
        return False
    return bool(result.get("ok", True))
