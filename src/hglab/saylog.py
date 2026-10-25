"""Every public line an agent of this host says, so the three-an-hour rule holds whatever observe shows.

``action_limits`` counts an agent's recent says from the events in its observe and from its notebook's
``_limits`` note. Observe carries at most 50 events, and at a busy place (the factory's works, the
square) an agent's own says fall out of them within minutes, while nothing wrote ``_limits``: ten of
eleven speaking agents went over three lines in an hour on 2026-10-24 (Clarion eight). Under the local
runtime the client records every say the world accepts here (``record``) and merges the last hour of
them into each observe's ``_limits`` (``merge``), so every entry point (wakes, shift lines, the crier's
and the land office's rounds) counts them before it speaks. The log is private bookkeeping on this host,
never published; the notebook copy is redacted from records like the rest of the notebook.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any

LOG_DIR = "runs/local/says"
WINDOW = 360  # ticks: one world day, one real hour
KEEP = 24


def enabled() -> bool:
    return os.environ.get("HGLAB_RUNTIME") == "local"


def log_path(name: str, root: Path | None = None) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", name)[:32] or "agent"
    return (root or Path.cwd()) / LOG_DIR / f"{safe}.json"


def load(name: str, root: Path | None = None) -> list[dict[str, Any]]:
    try:
        rows = json.loads(log_path(name, root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("tick"), int)] if isinstance(rows, list) else []


def record(name: str, tick: int, text: str, root: Path | None = None) -> None:
    """Remember a line the world accepted (the newest ``KEEP``, within two hours of it)."""
    if not name:
        return
    rows = [r for r in load(name, root) if int(tick) - int(r["tick"]) < 2 * WINDOW]
    rows.append({"tick": int(tick), "text": str(text)[:200]})
    path = log_path(name, root)
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(rows[-KEEP:]), encoding="utf-8")
        os.replace(tmp, path)


def merge(observe: dict[str, Any], root: Path | None = None) -> int:
    """Put this agent's lines of the last hour into the observe's ``_limits`` note; returns how many."""
    if not isinstance(observe, dict):
        return 0
    you = observe.get("you") or {}
    name = str(you.get("name") or "")
    tick = int(observe.get("tick", 0) or 0)
    if not name:
        return 0
    recent = [r for r in load(name, root) if 0 <= tick - int(r["tick"]) < WINDOW]
    if not recent:
        return 0
    notebook = observe.get("notebook")
    if not isinstance(notebook, dict):
        notebook = {}
        observe["notebook"] = notebook
    stored = notebook.get("_limits")
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except ValueError:
            stored = {}
    says = list(stored.get("says") or []) if isinstance(stored, dict) else []
    seen = {(int(s.get("tick", -1)), str(s.get("text", ""))) for s in says if isinstance(s, dict) and isinstance(s.get("tick"), int)}
    for r in recent:
        key = (int(r["tick"]), str(r.get("text", "")))
        if key not in seen:
            says.append({"tick": key[0], "text": key[1]})
            seen.add(key)
    notebook["_limits"] = {**(stored if isinstance(stored, dict) else {}), "says": says}
    return len(recent)


__all__ = ["LOG_DIR", "WINDOW", "enabled", "load", "log_path", "merge", "record"]
