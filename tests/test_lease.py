import json
from datetime import UTC, datetime

from hglab.lease import LEASE_KEY, acquire, release


class FakeClient:
    def __init__(self):
        self.notebook = {}
        self.overwrite_after_write = False

    def observe(self):
        return {"notebook": dict(self.notebook)}

    def act(self, action):
        if action["action"] == "remember":
            self.notebook[action["key"]] = action["text"]
            if self.overwrite_after_write:
                self.overwrite_after_write = False
                self.notebook[LEASE_KEY] = json.dumps(
                    {"holder": "other", "run_id": "rival", "expires_utc": "2026-10-17T14:00:00+00:00"}
                )
        elif action["action"] == "forget":
            self.notebook.pop(action["key"], None)
        return {"ok": True}


def test_lease_acquire_verify_and_release():
    client = FakeClient()
    lease = acquire(client, "agent", datetime(2026, 10, 17, 12, tzinfo=UTC))
    assert lease is not None
    assert release(client, lease)
    assert LEASE_KEY not in client.notebook


def test_lease_contender_and_write_race_are_rejected():
    client = FakeClient()
    current = {"holder": "another", "run_id": "rival", "expires_utc": "2026-10-17T14:00:00+00:00"}
    client.notebook[LEASE_KEY] = json.dumps(current)
    assert acquire(client, "agent", datetime(2026, 10, 17, 12, tzinfo=UTC)) is None

    client.notebook.clear()
    client.overwrite_after_write = True
    assert acquire(client, "agent", datetime(2026, 10, 17, 12, tzinfo=UTC)) is None


def test_a_release_that_cannot_reach_the_world_does_not_raise():
    from datetime import UTC, datetime

    from hglab.client import WorldUnreachable
    from hglab.lease import Lease, release

    class Down:
        def observe(self):
            raise WorldUnreachable("GET /api/v1/me/observe: ReadTimeout after 4 attempt(s)")

        def act(self, action):  # pragma: no cover - never reached
            raise AssertionError

    assert release(Down(), Lease("Clarion", "run-1", datetime.now(UTC))) is False
