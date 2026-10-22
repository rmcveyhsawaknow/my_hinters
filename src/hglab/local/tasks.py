"""A2A tasks reach the persona they are for at its next wake, as messages beside the whispers.

``deliver`` reads the submitted and working tasks for an in-world name from the local memory graph
(when there is one) and returns inbox-shaped entries, marking submitted tasks ``working`` on a live
wake; ``settle`` marks the working tasks ``completed`` once the live wake has written its record. A
dry wake reads the tasks and changes nothing. Task text is data like any whisper: redacted from the
records, never a direction to tools.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hglab.local.memory import Graph

GRAPH_PATH = Path("runs/local/memory.sqlite")
TEXT_LIMIT = 400


def graph_path(root: Path) -> Path:
    return root / GRAPH_PATH


def _text(task: dict[str, Any]) -> str:
    parts = [
        p.get("text", "")
        for m in task.get("history") or []
        for p in m.get("parts") or []
        if isinstance(p, dict)
    ]
    return " ".join(str(p) for p in parts if p).strip()


def deliver(agent: str, root: Path, tick: int = 0, dry_run: bool = True) -> list[dict[str, Any]]:
    """The open tasks for ``agent`` as inbox entries ``{"from", "text", "tick", "task"}``."""
    path = graph_path(root)
    if not path.is_file():
        return []
    from hglab.local.a2a import TaskStore

    graph = Graph(path)
    try:
        store = TaskStore(graph)
        out: list[dict[str, Any]] = []
        for task in store.pending_for(agent):
            text = _text(task)
            if not text:
                continue
            if not dry_run and task["status"]["state"] == "submitted":
                store.set_state(task["id"], "working", f"delivered at tick {tick}")
            sender = str((task.get("metadata") or {}).get("sender") or "operator")
            out.append(
                {
                    "from": f"{sender} (operator)",
                    "text": text[:TEXT_LIMIT],
                    "tick": int(tick),
                    "task": task["id"],
                }
            )
        return out
    finally:
        graph.close()


def settle(agent: str, root: Path, run_id: str | None, dry_run: bool = True) -> int:
    """After a live wake: its working tasks are completed. Returns how many."""
    if dry_run:
        return 0
    path = graph_path(root)
    if not path.is_file():
        return 0
    from hglab.local.a2a import TaskStore

    graph = Graph(path)
    try:
        store = TaskStore(graph)
        done = 0
        for task in store.pending_for(agent):
            if task["status"]["state"] == "working":
                store.set_state(
                    task["id"],
                    "completed",
                    f"read by wake {run_id}" if run_id else "read by a wake",
                )
                done += 1
        return done
    finally:
        graph.close()


__all__ = ["GRAPH_PATH", "deliver", "graph_path", "settle"]
