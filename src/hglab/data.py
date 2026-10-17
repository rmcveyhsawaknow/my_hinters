"""Load public events, run records and history from disk or fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def load_events(paths: list[Path]) -> list[dict[str, Any]]:
    """Public events from JSONL archives or JSON pages, deduplicated by id."""
    seen: dict[Any, dict[str, Any]] = {}
    for path in paths:
        if path.is_dir():
            files = sorted(path.glob("*.jsonl")) + sorted(path.glob("*.json"))
        else:
            files = [path]
        for file in files:
            if not file.is_file():
                continue
            if file.suffix == ".jsonl":
                rows = read_jsonl(file)
            else:
                try:
                    payload = json.loads(file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                rows = payload.get("events", []) if isinstance(payload, dict) else payload
            for row in rows:
                if isinstance(row, dict) and row.get("id") is not None:
                    seen[row["id"]] = row
    return sorted(seen.values(), key=lambda e: (int(e.get("tick", 0)), int(e.get("id", 0))))


def load_runs(
    root: Path, agent_name: str, slug: str, extra: list[Path] | None = None, *, include_local: bool = True
) -> list[dict[str, Any]]:
    """Redacted run records for one identity from runs/, pulled reports, and fixtures.

    ``include_local=False`` reads only ``extra`` (fixture mode stays independent of what
    happens to be in runs/ or reports/ on this machine).
    """
    records: dict[str, dict[str, Any]] = {}
    folders = [root / "runs", root / "reports/agents" / slug / "runs"] if include_local else []
    for folder in folders:
        if not folder.is_dir():
            continue
        for file in sorted(folder.rglob(f"{agent_name}-*.json")):
            try:
                record = json.loads(file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("run_id"):
                records[str(record["run_id"])] = record
    for path in extra or []:
        if path.is_dir():
            files = sorted(path.glob("*.jsonl")) + sorted(path.glob("*.json"))
        else:
            files = [path]
        for file in files:
            rows = read_jsonl(file) if file.suffix == ".jsonl" else [json.loads(file.read_text(encoding="utf-8"))]
            for record in rows:
                if isinstance(record, dict) and record.get("run_id") and (
                    record.get("persona") == slug or str(record.get("agent", "")).casefold() == agent_name.casefold()
                ):
                    records[str(record["run_id"])] = record
    return sorted(records.values(), key=lambda r: int(r.get("tick", 0) or 0))


def load_history(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(path)


def latest_tick(events: list[dict[str, Any]], runs: list[dict[str, Any]], fallback: int = 0) -> int:
    ticks = [int(e.get("tick", 0)) for e in events] + [int(r.get("tick", 0) or 0) for r in runs]
    return max(ticks) if ticks else fallback


__all__ = ["latest_tick", "load_events", "load_history", "load_runs", "read_jsonl"]
