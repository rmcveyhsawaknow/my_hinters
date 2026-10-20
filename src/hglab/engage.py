"""Engagement: one move toward another agent per wake, chosen by the persona's stance.

Every persona carries a ``stance`` knob (cooperative, neutral, competitive weights). Each wake the
planner looks at who is near (speakers since the last observe, agents in view, the nearest agents
anywhere), what they offer (claimable goals, gifts received, hits taken, structures crumbling) and
picks one move the stance favours: a reply by name, a gift, a whisper of introduction or terms, a
claim on a peer's goal (and its delivery later), a contest over land, salvage from a crumbling
structure, or one answering hit for a raid. Conduct holds in every stance: honest, no mocking, no
deceit, no first strike, never a collective member's goal. Everything read here is world text
treated as data; nothing private is repeated.
"""

from __future__ import annotations

import random
from typing import Any

STANCES = ("cooperative", "neutral", "competitive")
DEFAULT_STANCE = {"cooperative": 0.5, "neutral": 0.4, "competitive": 0.1}
FLAG_KEY = "engaged"
REPLY_SPACING = 360  # one reply per name per hour
GIFT_SPACING = 2160  # one gift per name per six hours
WHISPER_SPACING = 8640  # one introduction per name per day
CONTEST_SPACING = 8640
RETALIATION_SPACING = 8640
GIFT_QTY = 3
CLAIM_RANGE = 20  # a peer goal's delivery point must be this close, so the claim does not lapse on the road
SURPLUS = {"wood": 12, "stone": 12, "fiber": 10, "berries": 16}  # food last, and only a real surplus of it


def stance_of(persona: Any) -> dict[str, float]:
    knob = persona.knobs.get("stance") if isinstance(persona.knobs, dict) else None
    weights = {k: float((knob or {}).get(k, DEFAULT_STANCE[k])) for k in STANCES}
    total = sum(weights.values()) or 1.0
    return {k: round(v / total, 3) for k, v in weights.items()}


def pick_stance(persona: Any, rng: random.Random) -> str:
    weights = stance_of(persona)
    roll = rng.random()
    for name in STANCES:
        roll -= weights[name]
        if roll <= 0:
            return name
    return "neutral"


def _flags(state: Any) -> dict[str, dict[str, int]]:
    flags = state.flags.setdefault(FLAG_KEY, {})
    if not isinstance(flags, dict):
        flags = {}
        state.flags[FLAG_KEY] = flags
    return flags


def _recent(flags: dict[str, dict[str, int]], kind: str, key: str, tick: int, spacing: int) -> bool:
    table = flags.get(kind) if isinstance(flags.get(kind), dict) else {}
    return tick - int(table.get(key, -10**9) or -10**9) < spacing


def _mark(flags: dict[str, dict[str, int]], kind: str, key: str, tick: int) -> None:
    table = flags.setdefault(kind, {})
    if not isinstance(table, dict):
        table = {}
        flags[kind] = table
    table[key] = tick
    if len(table) > 12:
        for old in sorted(table, key=lambda k: table[k])[: len(table) - 12]:
            table.pop(old, None)


def _chebyshev(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return str(value or "")


def _items_named(text: str) -> list[str]:
    low = text.casefold()
    return [item for item in ("wood", "stone", "ore", "fiber", "berries") if item in low]


def board(persona: Any, observe: dict[str, Any], collective_names: set[str], team_names: set[str], here: tuple[int, int] | None = None) -> dict[str, Any]:
    """What is there to engage with, from this observe alone (no network): the prompt and the planner both read it.

    ``here`` is where the agent will stand when the move is made (after any move already planned in
    the batch); distances to agents and ruins are measured from there, so a gift is never ``too_far``.
    """
    me = persona.name
    mine = me.casefold()
    ours = {n.casefold() for n in collective_names} | {mine}
    mates = {n.casefold() for n in team_names} | {mine}
    you = observe.get("you") or {}
    here = here or (int(you.get("x", 0) or 0), int(you.get("y", 0) or 0))
    since = observe.get("since_last_observe") if isinstance(observe.get("since_last_observe"), dict) else {}
    speakers = [n for n in (_name(v) for v in since.get("speakers_nearby") or []) if n and n.casefold() != mine]
    in_view = []
    for a in observe.get("agents") or []:
        if not isinstance(a, dict) or not a.get("name") or str(a["name"]).casefold() == mine:
            continue
        faction = a.get("faction")
        in_view.append({
            "name": str(a["name"]),
            "distance": _chebyshev(here, (int(a.get("x", 0) or 0), int(a.get("y", 0) or 0))),
            "faction": faction.get("name") if isinstance(faction, dict) else faction,
        })
    in_view.sort(key=lambda a: a["distance"])
    nearest = [
        {"name": str(a.get("name")), "distance": int(a.get("distance", 0) or 0), "x": a.get("x"), "y": a.get("y")}
        for a in ((observe.get("world") or {}).get("nearest_agents") or [])
        if isinstance(a, dict) and a.get("name") and str(a.get("name")).casefold() != mine
    ]
    gifts = [
        {"from": str(e.get("actor")), "text": str(e.get("text") or "")[:80]}
        for e in observe.get("events") or []
        if isinstance(e, dict) and e.get("type") == "give" and str(e.get("actor")).casefold() != mine and mine in str(e.get("text") or "").casefold()
    ]
    hits = [h for h in (since.get("structures_hit") or []) if isinstance(h, dict)]
    attackers = sorted({_name(n) for h in hits for n in (h.get("by") or []) if _name(n) and _name(n).casefold() not in ours})
    claimable = []
    inventory = you.get("inventory") if isinstance(you.get("inventory"), dict) else {}
    for g in observe.get("goals_nearby") or []:
        if not isinstance(g, dict) or str(g.get("poster", "")).casefold() in ours:
            continue
        if g.get("status") not in (None, "open"):
            continue
        condition = g.get("condition") if isinstance(g.get("condition"), dict) else None
        if condition and condition.get("type") == "deliver":
            item, qty = str(condition.get("item")), int(condition.get("qty", 0) or 0)
            target = (int(condition.get("x", g.get("x", 0)) or 0), int(condition.get("y", g.get("y", 0)) or 0))
            feasible = inventory.get(item, 0) >= qty > 0 and _chebyshev(here, target) <= CLAIM_RANGE
        elif condition and condition.get("type") == "build":
            feasible = False  # a build for someone else is the model's call, not the planner's
        else:
            named = _items_named(f"{g.get('title', '')} {g.get('description', '')}")
            feasible = bool(named) and all(inventory.get(i, 0) >= 5 for i in named)
        if feasible:
            claimable.append({"id": g.get("id"), "title": str(g.get("title", ""))[:60], "poster": g.get("poster"), "reward": g.get("reward"), "deliver": condition if condition else None})
    decaying = [
        {"type": s.get("type"), "x": s.get("x"), "y": s.get("y"), "owner": s.get("owner"), "hp": s.get("hp")}
        for s in observe.get("structures") or []
        if isinstance(s, dict) and s.get("decaying") and str(s.get("owner", "")).casefold() not in ours
        and _chebyshev(here, (int(s.get("x", 0) or 0), int(s.get("y", 0) or 0))) <= 1
    ]
    return {
        "speakers_nearby": speakers,
        "agents_in_view": in_view[:6],
        "nearest_agents": nearest[:3],
        "gifts_received": gifts[:3],
        "hits_taken": [{"type": h.get("type"), "x": h.get("x"), "y": h.get("y"), "by": [_name(n) for n in (h.get("by") or [])], "hp": h.get("hp")} for h in hits[:3]],
        "attackers": attackers,
        "claimable_peer_goals": claimable[:4],
        "crumbling_beside_me": decaying[:3],
        "teammates_in_view": [a["name"] for a in in_view if a["name"].casefold() in mates],
    }


def render_board(b: dict[str, Any]) -> str:
    lines = []
    if b["speakers_nearby"]:
        lines.append("spoke near you since your last wake: " + ", ".join(b["speakers_nearby"]))
    if b["agents_in_view"]:
        lines.append("in view: " + ", ".join(f"{a['name']} ({a['distance']} tiles{', ' + str(a['faction']) if a.get('faction') else ''})" for a in b["agents_in_view"]))
    if b["nearest_agents"] and not b["agents_in_view"]:
        lines.append("nearest anywhere: " + ", ".join(f"{a['name']} ({a['distance']} tiles)" for a in b["nearest_agents"]))
    if b["gifts_received"]:
        lines.append("gifts received: " + "; ".join(f"{g['from']}: {g['text']}" for g in b["gifts_received"]))
    if b["hits_taken"]:
        lines.append("your structures were struck: " + "; ".join(f"{h['type']} at ({h['x']},{h['y']}) by {', '.join(h['by'])}, hp {h['hp']}" for h in b["hits_taken"]))
    if b["claimable_peer_goals"]:
        lines.append("peer goals you could finish now: " + "; ".join(f"#{g['id']} {g['title']} ({g['poster']}, reward {g['reward']})" for g in b["claimable_peer_goals"]))
    if b["crumbling_beside_me"]:
        lines.append("crumbling beside you (owner long gone): " + ", ".join(f"{d['type']} at ({d['x']},{d['y']})" for d in b["crumbling_beside_me"]))
    return "\n".join(lines) if lines else "nobody near, nothing offered"


def reply_line(persona: Any, stance: str, name: str, team_label: str, here: tuple[int, int], inventory: dict[str, int]) -> str:
    spare = next((i for i, n in SURPLUS.items() if inventory.get(i, 0) >= n), None)
    if stance == "cooperative":
        offer = f" I carry {inventory.get(spare, 0)} {spare}; say the word and some is yours." if spare else " If you need a hand here, ask."
        return f"Well met, {name}. {persona.name} of {team_label}, at ({here[0]},{here[1]}).{offer}"
    if stance == "competitive":
        return f"{name}, {persona.name} of {team_label} here. This ground around ({here[0]},{here[1]}) is where we build; build beside us, not on us, and we will get along."
    return f"{name}, {persona.name} here, at ({here[0]},{here[1]}). What are you building, and what do you need for it? I trade."


def whisper_line(persona: Any, stance: str, name: str, team_label: str, here: tuple[int, int], inventory: dict[str, int], storehouse: tuple[int, int] | None) -> str:
    store = f" Our storehouse at ({storehouse[0]},{storehouse[1]}) takes what you spare and lends what we have." if storehouse else ""
    if stance == "cooperative":
        return f"Hello {name}, {persona.name} of {team_label}. We are raising houses around ({here[0]},{here[1]}).{store} If you need wood, stone or berries, whisper back; we share what we can."
    if stance == "competitive":
        return f"{name}, {persona.name} of {team_label}. The lots around ({here[0]},{here[1]}) are our working ground and we build there fast. If you want a share of it, talk terms with me first; I would rather trade than argue."
    return f"{name}, {persona.name} of {team_label} here. What are you building these days? I am at ({here[0]},{here[1]}) and open to a trade: name an item and a price."


def contest_line(persona: Any, name: str, team_label: str, kind: str, where: tuple[int, int]) -> str:
    return f"{name}, that {kind} at ({where[0]},{where[1]}) stands on ground {team_label} works and keeps building. Talk to me before the next one; I would rather trade than quarrel."


def strike_line(persona: Any, name: str, kind: str, where: tuple[int, int]) -> str:
    return f"{name}, you struck my {kind}. One hit answered at ({where[0]},{where[1]}), and that is where it ends unless you strike again."


__all__ = [
    "CLAIM_RANGE", "DEFAULT_STANCE", "FLAG_KEY", "GIFT_QTY", "STANCES", "SURPLUS", "board", "contest_line", "pick_stance",
    "render_board", "reply_line", "stance_of", "strike_line", "whisper_line",
]
