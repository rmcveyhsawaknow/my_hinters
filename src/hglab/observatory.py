"""Collection helpers for unauthenticated public world endpoints."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class Observatory:
    def __init__(self, client: Any, root: Path) -> None:
        self.client = client
        self.root = root

    def collect_events(self, limit: int = 100) -> Path:
        if not 1 <= limit <= 100:
            raise ValueError("event page size must be between 1 and 100")
        today = datetime.now(UTC).date().isoformat()
        destination = self.root / "data/events" / f"{today}.jsonl"
        destination.parent.mkdir(parents=True, exist_ok=True)
        seen = set()
        if destination.exists():
            for line in destination.read_text(encoding="utf-8").splitlines():
                try:
                    seen.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    continue
        before = None
        cursors = set()
        additions: list[dict[str, Any]] = []
        for _ in range(20):
            params: dict[str, Any] = {"limit": limit}
            if before is not None:
                params["before"] = before
            page = self.client.request("GET", "/api/v1/world/events", params=params)
            events = page.get("events", [])
            if not events:
                break
            overlaps_archive = False
            for event in events:
                event_id = event.get("id")
                if event_id in seen:
                    overlaps_archive = True
                elif event_id is not None:
                    additions.append(event)
                    seen.add(event_id)
            if overlaps_archive:
                break
            next_before = page.get("before") or events[-1].get("id")
            if next_before is None or next_before in cursors:
                break
            cursors.add(next_before)
            before = next_before
            if not page.get("has_more", len(events) == limit):
                break
        with destination.open("a", encoding="utf-8") as output:
            for event in additions:
                output.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return destination

    def collect_all(self) -> list[Path]:
        today = datetime.now(UTC).date().isoformat()
        collected = [self.collect_events()]
        endpoints = {
            "world": "/live/world.json",
            "agents": "/live/agents.json",
            "goals": "/api/v1/world/goals?status=open",
            "factions": "/api/v1/world/factions",
        }
        snapshots = []
        world_tick = None
        for name, endpoint in endpoints.items():
            target, digest = self.snapshot(endpoint, f"{today}-{name}.json")
            snapshots.append((target.name, digest))
            collected.append(target)
            if name == "world":
                world_tick = self.last_snapshot.get("tick")
        directory = self.root / "data/snapshots"
        manifest = directory / f"{today}.sha256"
        with manifest.open("w", encoding="ascii") as output:
            for filename, digest in snapshots:
                output.write(f"{digest}  {filename}\n")
        collected.append(manifest)
        if world_tick is not None:
            clock = self.root / "data/clock.jsonl"
            clock.parent.mkdir(parents=True, exist_ok=True)
            with clock.open("a", encoding="utf-8") as output:
                output.write(
                    json.dumps({"tick": world_tick, "utc": datetime.now(UTC).isoformat()}) + "\n"
                )
            collected.append(clock)
        return collected

    def snapshot(self, endpoint: str, filename: str) -> tuple[Path, str]:
        if endpoint not in {"/live/world.json", "/live/agents.json", "/api/v1/world/goals?status=open", "/api/v1/world/factions"}:
            raise ValueError("unsupported public snapshot endpoint")
        if Path(filename).name != filename or filename in {".", ".."}:
            raise ValueError("snapshot filename must be a simple file name")
        snapshot = self.client.request("GET", endpoint)
        self.last_snapshot = snapshot
        raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()
        digest = hashlib.sha256(raw).hexdigest()
        folder = self.root / "data/snapshots"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / filename
        target.write_bytes(raw)
        manifest = folder / f"{filename}.sha256"
        manifest.write_text(f"{digest}  {filename}\n", encoding="ascii")
        return target, digest
