"""Local measurement: the public events archive this host keeps, and the Pulse computed from it.

GitHub Actions used to pull the reports branch and recompute the Pulse from freshly fetched public
events; with Actions off, nothing refreshed the archive, so the Pulse read zero for work the public
record plainly showed. ``refresh_archive`` appends the newest public pages (no key) to
``data/events/public.jsonl``, deduplicated by event id and pruned to two weeks; ``refresh_pulse`` runs
the same Pulse computation as the ``pulse`` job, from the archive and the local run records, into
``reports/`` (ignored by git), where the adaptive goals read each key result's progress. The
supervisor does both in its adapt cycle; ``hglab local pulse`` does them on demand.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

KEEP_TICKS = 14 * 8640  # two weeks of events, as the reports branch keeps two weeks of runs
PAGES = 20  # public pages of 100 events per refresh: about five hours of the world at today's pace


def archive_path(root: Path) -> Path:
    return root / "data" / "events" / "public.jsonl"


def refresh_archive(
    root: Path, client: Any | None = None, pages: int = PAGES, keep_ticks: int = KEEP_TICKS
) -> dict[str, Any]:
    """Merge the newest public event pages into the archive; returns what changed."""
    from hglab.cli_personas import fetch_public_events
    from hglab.client import HinterglassClient
    from hglab.data import read_jsonl

    path = archive_path(root)
    existing = [e for e in read_jsonl(path) if isinstance(e, dict)] if path.is_file() else []
    fetched = fetch_public_events(client or HinterglassClient(), pages)
    by_id: dict[Any, dict[str, Any]] = {
        e["id"]: e for e in existing if e.get("id") is not None
    }
    added = 0
    for event in fetched:
        if not isinstance(event, dict) or event.get("id") is None:
            continue
        if event["id"] not in by_id:
            added += 1
        by_id[event["id"]] = event
    rows = sorted(
        by_id.values(), key=lambda e: (int(e.get("tick", 0) or 0), int(e.get("id", 0) or 0))
    )
    newest = max((int(e.get("tick", 0) or 0) for e in rows), default=0)
    rows = [e for e in rows if int(e.get("tick", 0) or 0) >= newest - keep_ticks]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in rows),
        encoding="utf-8",
        newline="\n",
    )
    return {
        "added": added,
        "fetched": len(fetched),
        "total": len(rows),
        "newest_tick": newest,
        "path": str(path),
    }


def refresh_pulse(root: Path, slugs: list[str] | None = None) -> dict[str, Any]:
    """Recompute the Pulse for ``slugs`` (every persona by default) from the archive and local runs into reports/."""
    from hglab.cli_personas import run_pulse
    from hglab.persona import load_personas

    wanted = list(slugs or load_personas(root))
    pulses = run_pulse(
        root,
        wanted,
        fixtures=False,
        events_paths=[],
        runs_paths=[],
        fetch_public=False,
        judge=False,
        out=root / "reports",
        tick=None,
        today=None,
    )
    return {"agents": sorted(pulses), "utc": datetime.now(UTC).isoformat()}


def refresh(root: Path, client: Any | None = None, fetch: bool = True) -> dict[str, Any]:
    """Archive then Pulse, as the supervisor and the CLI run them."""
    out: dict[str, Any] = {}
    if fetch:
        out["archive"] = refresh_archive(root, client)
    out["pulse"] = refresh_pulse(root)
    return out


__all__ = ["KEEP_TICKS", "archive_path", "refresh", "refresh_archive", "refresh_pulse"]
