"""Derive conservative anti-spam counters from public events and notebook limits."""

from __future__ import annotations

import json
from typing import Any


def action_limits(observe: dict[str, Any]) -> tuple[int, int, set[str]]:
    """Return recent say count, open-goal count, and text seen in the last 60 ticks."""
    tick = int(observe.get("tick", 0))
    you = observe.get("you") or {}
    identity = you.get("id") or you.get("name")
    notebook = observe.get("notebook") or {}
    stored = notebook.get("_limits", {})
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except json.JSONDecodeError:
            stored = {}
    stored_says = stored.get("says", []) if isinstance(stored, dict) else []
    says = [
        (int(entry["tick"]), str(entry.get("text", "")))
        for entry in stored_says
        if isinstance(entry, dict)
        and entry.get("tick") is not None
        and 0 <= tick - int(entry["tick"]) < 360
    ]
    for event in observe.get("events", []):
        if not isinstance(event, dict):
            continue
        event_type = event.get("type") or event.get("action")
        author = event.get("agent_id") or event.get("author_id") or event.get("agent")
        event_tick = event.get("tick")
        if (
            event_type in {"say", "agent_said"}
            and (identity is None or author == identity)
            and isinstance(event_tick, int)
            and 0 <= tick - event_tick < 360
        ):
            text = event.get("text", "")
            says.append((event_tick, str(text)))
    open_goals = sum(
        goal.get("status") in {"open", "claimed"}
        for goal in observe.get("your_goals") or []
        if isinstance(goal, dict)
    )
    return (
        len(says),
        open_goals,
        {text.casefold() for event_tick, text in says if 0 <= tick - event_tick < 60},
    )
