"""Routing from the collective's observed patterns in the memory graph (the owner's instruction of 2026-10-27).

Every live wake sits in the graph with what the world accepted (``kinds``), what it refused (``refused``) and
the pack it began with (``pack``). Two readings come from it:

- a persona's recent productivity: of its last ``RECENT`` live wakes, how many changed the world (a build, a
  place, a give, a gather, a take, a word) and how many met a full store or pack;
- the collective's successful patterns: per team and crew role, the share of each approach's wakes over the
  last day that changed the world.

An idle persona (at most ``IDLE_SHARE`` of its recent wakes changed anything) is routed to the approach that
works best for its team and role and is open to it. A crew hand whose team has a blueprint and whose pack is
heavy or whose gives meet full stores is routed to the blueprint while the team's blueprint wakes change the
world: a pack of stone pays for blocks, and the blueprint is where the team's materials are meant to go. The
route goes first in the assignment's ``prefer``, the brief names the evidence, and the planner reads it
(``crew.plan_crew(route=...)``; ``plan_wake(prefer=...)``). Nothing here acts in the world.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from hglab.local.memory import Graph

RECENT = 24  # live wakes a persona's productivity is read over
MIN_WAKES = 12  # fewer than this is not enough to call a persona idle, or an approach proven
IDLE_SHARE = 0.25  # at most this share of recent wakes changed anything: idle
PROVEN_RATE = 0.5  # an approach whose wakes change the world at least this often is a pattern worth following
PATTERN_TICKS = 8640  # one real day of wakes makes the patterns
HEAVY_PACK = 30  # a pack this full holds a step's worth of material
CHANGED = {
    "build", "give", "gather", "take", "place", "remove", "demolish", "repair", "paint", "write",
    "say", "whisper", "post_goal", "claim_goal", "confirm_goal", "invite", "join_faction", "found_faction",
}  # an accepted action of these kinds changed the world or the record; moves and notes alone did not
QUIET = ("keepalive", "announce", "rest")
ROUTABLE = {"deposit", "deposit_trip", "gather_trip", "forage", "harvest", "build", "social", "engage", "reclaim", "draw", "patrol"}
CHARACTER_SHARE = 0.15  # a character is routed only to work its own intended mix gives at least this share: its personality stands
MIX_OF = {"build": "build", "gather": "gather", "explore": "explore", "social": "social", "engage": "social", "trade": "trade"}


def _changed(props: dict[str, Any], goal_kinds: frozenset[str] = frozenset()) -> bool:
    kinds = props.get("kinds") if isinstance(props.get("kinds"), dict) else {}
    return any(int(v or 0) > 0 for k, v in kinds.items() if k in CHANGED or k in goal_kinds)


def _live(props: dict[str, Any]) -> bool:
    return not props.get("dry_run") and str(props.get("mode") or "") not in QUIET and isinstance(props.get("kinds"), dict)


def productivity(graph: Graph, name: str, limit: int = RECENT, goal_kinds: frozenset[str] = frozenset()) -> dict[str, Any]:
    """The persona's last ``limit`` live wakes: how many changed the world (or did what its assignment measures:
    ``goal_kinds``, so an explorer's moves count), how many met a full store or pack, the newest pack, the approaches."""
    rows = graph.db.execute(
        "SELECT tick, props FROM nodes WHERE kind = 'wake' AND json_extract(props, '$.agent') = ? ORDER BY tick DESC LIMIT ?",
        (name, int(limit) * 3),
    ).fetchall()
    wakes = []
    for r in rows:
        props = json.loads(r["props"]) if isinstance(r["props"], str) else dict(r["props"] or {})
        if _live(props):
            wakes.append(props)
        if len(wakes) >= limit:
            break
    productive = sum(1 for p in wakes if _changed(p, goal_kinds))
    full = sum(1 for p in wakes if int((p.get("refused") or {}).get("inventory_full", 0) or 0) > 0)
    pack = next((int(p["pack"]) for p in wakes if isinstance(p.get("pack"), int)), None)
    return {
        "wakes": len(wakes),
        "productive": productive,
        "share": round(productive / len(wakes), 3) if wakes else None,
        "full": full,
        "pack": pack,
        "approaches": Counter(str(p.get("approach") or "none") for p in wakes),
    }


def patterns(graph: Graph, since_tick: int) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    """Per (team, crew role) and per (team, ""): each approach's live wakes since ``since_tick`` and the share that changed the world."""
    agents = {n["id"]: n for n in graph.nodes("agent") if n.get("ours")}
    rows = graph.db.execute("SELECT props FROM nodes WHERE kind = 'wake' AND tick >= ?", (int(since_tick),)).fetchall()
    tally: dict[tuple[str, str], dict[str, list[int]]] = {}
    kinds_by: dict[tuple[str, str], dict[str, Counter[str]]] = {}
    for r in rows:
        props = json.loads(r["props"]) if isinstance(r["props"], str) else dict(r["props"] or {})
        agent = agents.get(str(props.get("agent") or ""))
        approach = props.get("approach")
        if agent is None or not approach or not _live(props):
            continue
        team, role = str(agent.get("team") or ""), str(agent.get("crew_role") or "")
        for key in {(team, role), (team, "")}:
            counts = tally.setdefault(key, {}).setdefault(str(approach), [0, 0])
            counts[0] += 1
            counts[1] += int(_changed(props))
            kinds_by.setdefault(key, {}).setdefault(str(approach), Counter()).update({k: int(v or 0) for k, v in (props.get("kinds") or {}).items()})
    return {
        key: {a: {"wakes": w, "productive": p, "rate": round(p / w, 3), "kinds": dict(kinds_by[key][a])} for a, (w, p) in by.items()}
        for key, by in tally.items()
    }


def route_for(persona: Any, team: Any | None, prod: dict[str, Any], pats: dict[tuple[str, str], dict[str, dict[str, Any]]], done: bool = False, goal_kinds: frozenset[str] = frozenset()) -> dict[str, Any] | None:
    """Where an idle persona's next wakes should go, with the evidence; None when it is not idle or nothing proven is open to it.

    ``done``: every key result of the persona is met. A crew hand whose stated goals are met goes to the
    team's blueprint even when it is busy: the next chapter is the build (the owner, 2026-10-27).
    A character (no crew knob) is routed only toward what its own goal measures (``goal_kinds``): to the
    approach whose wakes, across its team, produced those actions most often, and only to work its own
    intended mix sets out to do, so its personality stands; with no measured kinds it is left alone.
    """
    if prod.get("wakes", 0) < MIN_WAKES or prod.get("share") is None or (prod["share"] > IDLE_SHARE and not done):
        return None
    team_slug = str(getattr(persona, "team", "") or "")
    crew = persona.knobs.get("crew") if isinstance(persona.knobs.get("crew"), dict) else None
    role = str((crew or {}).get("role") or "")
    mine = f"{prod['productive']} of {prod['wakes']} recent wakes changed anything"
    pipeline = (getattr(team, "extra", None) or {}).get("pipeline") if team is not None else None
    has_blueprint = isinstance(pipeline, dict) and bool(pipeline.get("blueprint"))
    if crew is not None and has_blueprint:
        team_bp = (pats.get((team_slug, "")) or {}).get("blueprint") or {}
        loaded = (prod.get("pack") or 0) >= HEAVY_PACK or prod.get("full", 0) >= 3
        if (loaded or done) and team_bp.get("wakes", 0) >= MIN_WAKES and team_bp.get("rate", 0) >= PROVEN_RATE:
            state = "every key result met" if done else f"pack {prod.get('pack')}, {prod.get('full', 0)} met a full store or pack"
            return {
                "approach": "blueprint",
                "why": (
                    f"routed to the blueprint: {mine} ({state});"
                    f" the team's blueprint wakes changed the world in {int(team_bp['rate'] * 100)}% of {team_bp['wakes']}, so the pack's material goes into blocks"
                ),
            }
    if prod["share"] > IDLE_SHARE:
        return None  # met its goals but busy, and not a hand: it carries on
    if crew is not None:
        return None  # a hand works through its team's pipeline: the blueprint is the one route the graph gives it
    if not goal_kinds:
        return None  # nothing to say what would move this character's goal: it keeps its own way
    from hglab.planner import LABEL_ACTIVITY

    mix = persona.knobs.get("intended_mix") if isinstance(persona.knobs.get("intended_mix"), dict) else {}
    own = prod.get("approaches") or Counter()
    tried = {a for a, n in own.items() if n >= MIN_WAKES // 2}
    candidates = []
    for key in ((team_slug, role), (team_slug, "")):
        for approach, stats in (pats.get(key) or {}).items():
            if approach not in ROUTABLE or stats["wakes"] < MIN_WAKES or stats["rate"] < PROVEN_RATE:
                continue
            category = MIX_OF.get(LABEL_ACTIVITY.get(approach, ""), "")
            if float(mix.get(category, 0) or 0) < CHARACTER_SHARE:
                continue  # not work this character sets out to do: its personality stands
            goal_rate = sum(int(stats.get("kinds", {}).get(k, 0) or 0) for k in goal_kinds) / stats["wakes"]
            if goal_rate < PROVEN_RATE:
                continue  # it changes the world, but not in the way this character's goal counts
            if approach in tried and prod["share"] is not None and stats["rate"] <= prod["share"]:
                continue
            candidates.append((round(goal_rate, 3), stats["wakes"], approach, key))
        if candidates:
            break  # the role's own patterns before the team's
    if not candidates:
        return None
    rate, wakes, approach, key = max(candidates)
    whose = f"{key[1]}s of {key[0]}" if key[1] else key[0]
    return {"approach": approach, "why": f"routed to {approach}: {mine}; for {whose} it produced {rate} of the goal's own actions per wake over {wakes} wakes in the last day"}


__all__ = ["IDLE_SHARE", "PATTERN_TICKS", "patterns", "productivity", "route_for"]
