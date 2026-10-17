"""Derive conservative anti-spam counters from public events and notebook limits."""

from __future__ import annotations

import json
from typing import Any


def action_limits(observe: dict[str, Any]) -> tuple[int, int, set[str]]:
    """Return recent say count, open-goal count, and text seen in the last 60 ticks."""
    tick = int(observe.get("tick", 0))
    you = observe.get("you") or {}
    identity = you.get("id")
    name = you.get("name")
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
        actor = event.get("actor")
        event_tick = event.get("tick")
        is_self = (
            (identity is None and name is None)
            or (author is not None and author == identity)
            or (actor is not None and actor == name)
        )
        if (
            event_type in {"say", "agent_said"}
            and is_self
            and isinstance(event_tick, int)
            and 0 <= tick - event_tick < 360
        ):
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            text = data.get("text", event.get("text", ""))
            says.append((event_tick, str(text)))
    open_goals = count_open_goals(observe.get("your_goals"))
    return (
        len(says),
        open_goals,
        {text.casefold() for event_tick, text in says if 0 <= tick - event_tick < 60},
    )


def count_open_goals(your_goals: Any) -> int:
    """Count goals this identity has posted and not yet resolved.

    The live payload is ``{"posted": [...], "claimed": one or null}``; older fixtures
    used a flat list, so both shapes are accepted.
    """
    if isinstance(your_goals, dict):
        posted = your_goals.get("posted") or []
    else:
        posted = your_goals or []
    return sum(
        goal.get("status") in {"open", "claimed"}
        for goal in posted
        if isinstance(goal, dict)
    )
