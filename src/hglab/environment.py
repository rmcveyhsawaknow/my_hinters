"""Environment digest: the public feed read the way the Hinterglass site shows it.

The site's "happening now" stream filters All activity into Building, Trade & Goals, Talk
and Factions. This module groups the public event log the same way, measures the pace of
change, names who is active (team versus peers), and renders a compact, delimited digest
for the planner prompt. The same digest is stored in ``persona_state`` so an agent can
tell whether the world is quickening or quiet since its last wake, and the weekly retro
can propose adaptations from it. Everything here is public data; no inbox, no notebook.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

HOUR_TICKS = 360  # one in-world day, one real hour
DAY_TICKS = 24 * HOUR_TICKS  # one real day
CATEGORIES: dict[str, set[str]] = {
    "building": {"build", "demolish", "repair", "ruin", "write", "farm_produced", "structure_damaged", "structure_destroyed"},
    "trade_goals": {
        "give", "take", "goal_posted", "goal_claimed", "goal_confirmed", "goal_cancelled", "goal_abandoned",
        "goal_expired", "goal_rejected", "goal_done", "cache",
    },
    "talk": {"say", "profile"},
    "factions": {"faction_founded", "faction_joined", "faction_left", "faction_invited"},
}
CATEGORY_LABELS = {"all": "All activity", "building": "Building", "trade_goals": "Trade & Goals", "talk": "Talk", "factions": "Factions", "movement": "Movement & gathering"}
HEADLINE_TYPES = {"goal_posted", "goal_confirmed", "faction_founded", "faction_joined", "monument"}


def categorise(event: dict[str, Any]) -> str:
    kind = str(event.get("type", ""))
    for name, kinds in CATEGORIES.items():
        if kind in kinds:
            return name
    if kind == "build" or (kind == "build" and (event.get("data") or {}).get("type") == "monument"):
        return "building"
    return "movement"


def _text(event: dict[str, Any], limit: int = 110) -> str:
    text = str(event.get("text", ""))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _said(event: dict[str, Any], limit: int = 90) -> str:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    text = str(data.get("text", event.get("text", "")))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def digest(
    events: list[dict[str, Any]],
    now_tick: int,
    *,
    self_name: str,
    team_names: set[str],
    collective_names: set[str] | None = None,
    open_goals: list[dict[str, Any]] | None = None,
    factions: list[dict[str, Any]] | None = None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Counts by category for the last hour and day, pace, actors, headlines, open goals."""
    rows = [e for e in events if isinstance(e, dict) and isinstance(e.get("tick"), int)]
    last_hour = [e for e in rows if now_tick - e["tick"] < HOUR_TICKS]
    last_day = [e for e in rows if now_tick - e["tick"] < DAY_TICKS]
    earlier_day = [e for e in rows if DAY_TICKS <= now_tick - e["tick"] < 2 * DAY_TICKS]

    def by_category(items: list[dict[str, Any]]) -> dict[str, int]:
        counts = Counter(categorise(e) for e in items)
        return {"all": len(items), **{name: counts.get(name, 0) for name in ("building", "trade_goals", "talk", "factions", "movement")}}

    hour = by_category(last_hour)
    day = by_category(last_day)
    per_hour_now = hour["all"]
    per_hour_day = day["all"] / 24
    per_hour_before = len(earlier_day) / 24 if earlier_day else None
    if per_hour_day == 0 and per_hour_now == 0:
        pace = "quiet"
    elif per_hour_now >= 1.5 * max(per_hour_day, 0.5):
        pace = "quickening"
    elif per_hour_now <= 0.5 * per_hour_day:
        pace = "slowing"
    else:
        pace = "steady"
    lowered_team = {n.casefold() for n in team_names} | {self_name.casefold()}
    lowered_collective = {n.casefold() for n in (collective_names or set())} - lowered_team
    ours = lowered_team | lowered_collective
    actors = Counter(str(e.get("actor", "")) for e in last_day if e.get("actor"))
    team_active = {a: c for a, c in actors.items() if a.casefold() in lowered_team}
    collective_active = {a: c for a, c in actors.items() if a.casefold() in lowered_collective}
    peers_active = {a: c for a, c in actors.items() if a.casefold() not in ours and a.casefold() != "system"}
    headlines = [
        {"tick": e["tick"], "type": e["type"], "actor": e.get("actor"), "text": _text(e)}
        for e in sorted(last_day, key=lambda e: e["tick"], reverse=True)
        if e.get("type") in HEADLINE_TYPES or (e.get("type") == "build" and (e.get("data") or {}).get("type") in {"monument", "tower"})
    ][:8]
    talk = [
        {"tick": e["tick"], "actor": e.get("actor"), "text": _said(e)}
        for e in sorted(last_day, key=lambda e: e["tick"], reverse=True)
        if e.get("type") == "say" and str(e.get("actor", "")).casefold() not in ours
    ][:5]
    goals = [
        {"id": g.get("id"), "title": str(g.get("title", ""))[:60], "poster": g.get("poster"), "reward": g.get("reward")}
        for g in (open_goals or [])
        if isinstance(g, dict) and str(g.get("poster", "")).casefold() not in ours
    ][:6]
    faction_rows = [
        {"name": f.get("name"), "members": f.get("members", f.get("member_count")), "membership": f.get("membership")}
        for f in (factions or []) if isinstance(f, dict)
    ][:6]
    weather = None
    for event in sorted(rows, key=lambda e: e["tick"], reverse=True):
        if event.get("type") == "weather_changed":
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            weather = {"tick": event["tick"], "day": data.get("day"), "season": data.get("season"), "weather": data.get("weather")}
            break
    change = None
    if previous and isinstance(previous.get("day"), dict):
        before = previous["day"].get("all")
        if isinstance(before, (int, float)) and before:
            change = round((day["all"] - before) / before, 2)
    return {
        "tick": now_tick,
        "window_hours": 24,
        "hour": hour,
        "day": day,
        "pace": pace,
        "events_per_hour": {"now": per_hour_now, "day_average": round(per_hour_day, 2), "previous_day_average": None if per_hour_before is None else round(per_hour_before, 2)},
        "change_since_last_wake": change,
        "team_active": dict(sorted(team_active.items(), key=lambda kv: -kv[1])[:7]),
        "collective_active": dict(sorted(collective_active.items(), key=lambda kv: -kv[1])[:7]),
        "peers_active": dict(sorted(peers_active.items(), key=lambda kv: -kv[1])[:6]),
        "headlines": headlines,
        "peer_talk": talk,
        "open_peer_goals": goals,
        "factions": faction_rows,
        "weather": weather,
    }


def render(d: dict[str, Any]) -> str:
    """Compact text for the prompt (a few hundred tokens)."""
    lines = [
        f"tick {d['tick']} · pace {d['pace']} · events/hour now {d['events_per_hour']['now']}, day average {d['events_per_hour']['day_average']}"
        + (f", previous day {d['events_per_hour']['previous_day_average']}" if d['events_per_hour'].get('previous_day_average') is not None else "")
        + (f" · change since your last wake {d['change_since_last_wake']:+.0%}" if d.get("change_since_last_wake") is not None else ""),
        "last hour: " + ", ".join(f"{CATEGORY_LABELS[k]} {v}" for k, v in d["hour"].items()),
        "last day:  " + ", ".join(f"{CATEGORY_LABELS[k]} {v}" for k, v in d["day"].items()),
        "team active (events today): " + (", ".join(f"{a} {c}" for a, c in d["team_active"].items()) or "none"),
        "other collective members active (never claim their goals; give directly): " + (", ".join(f"{a} {c}" for a, c in d.get("collective_active", {}).items()) or "none"),
        "peers active (other operators' agents, events today): " + (", ".join(f"{a} {c}" for a, c in d["peers_active"].items()) or "none"),
    ]
    if d["headlines"]:
        lines.append("headlines: " + " | ".join(f"[{h['tick']}] {h['text']}" for h in d["headlines"]))
    if d["peer_talk"]:
        lines.append("peers said: " + " | ".join(f"[{t['tick']}] {t['text']}" for t in d["peer_talk"]))
    if d["open_peer_goals"]:
        lines.append("open peer goals: " + " | ".join(f"#{g['id']} {g['title']} ({g['poster']}, reward {json.dumps(g['reward'])})" for g in d["open_peer_goals"]))
    if d["factions"]:
        lines.append("factions: " + ", ".join(f"{f['name']} ({f.get('membership') or 'open'}, {f.get('members')})" for f in d["factions"]))
    if d.get("weather"):
        w = d["weather"]
        lines.append(
            f"weather: day {w.get('day')}, {w.get('season')}, {w.get('weather')} (storm: every move tile costs 1 more; rain: fiber and"
            " berries regrow faster and farms yield 4; drought: berries regrow at half speed; winter: wild berries do not regrow)"
        )
    return "\n".join(lines)


def compact_for_state(d: dict[str, Any]) -> dict[str, Any]:
    """What a persona keeps in its notebook: enough to feel the pace next wake."""
    return {"tick": d["tick"], "pace": d["pace"], "day": d["day"], "hour": {"all": d["hour"]["all"]}, "peers": len(d["peers_active"])}


__all__ = ["CATEGORIES", "CATEGORY_LABELS", "categorise", "compact_for_state", "digest", "render"]
