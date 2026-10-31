"""Named measures computed from public events and redacted run records.

Every Pulse number comes from one of these functions so anyone can recompute it. A
measure returns a float, or ``None`` when it cannot be measured yet (for example a
territory share before any territory exists); the Pulse shows those as "n/a" and leaves
them out of the weighted score.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from hglab.kb import FRONT_MATTER
from hglab.persona import Persona, Team, chebyshev, in_region, territory_center

DAY_TICKS = 360
WINDOW_TICKS = 7 * 24 * DAY_TICKS  # seven real days
HARD_BUILDS = {"bridge", "wall", "storehouse"}
LANDMARKS = {"monument", "tower"}
EVENT_REF = re.compile(r"\bevent\s+#?(\d+)\b", re.IGNORECASE)
ACTIVITY_OF_ACTION = {
    "place": "build", "remove": "build", "paint": "build",
    "build": "build", "demolish": "build", "gather": "gather", "take": "gather", "eat": "gather",
    "say": "social", "whisper": "social", "write": "social", "set_profile": "social",
    "found_faction": "social", "join_faction": "social", "leave_faction": "social",
    "move": "explore", "give": "trade", "post_goal": "trade", "claim_goal": "trade",
    "confirm_goal": "trade", "cancel_goal": "trade", "abandon_goal": "trade",
}
ACTION_COST = {
    "gather": 3, "build": 5, "demolish": 5, "say": 1, "whisper": 1, "write": 1, "give": 1,
    "take": 1, "post_goal": 2, "claim_goal": 1, "found_faction": 10, "move": 4,
}


@dataclass
class MeasureContext:
    persona: Persona
    team: Team | None
    personas: dict[str, Persona]
    events: list[dict[str, Any]]
    runs: list[dict[str, Any]]
    now_tick: int
    kb_items: list[dict[str, Any]] = field(default_factory=list)
    signals: dict[str, dict[str, Any]] = field(default_factory=dict)
    judge: dict[str, Any] | None = None
    window_ticks: int = WINDOW_TICKS
    state: dict[str, Any] = field(default_factory=dict)
    root: Path | None = None

    def __post_init__(self) -> None:
        start = self.now_tick - self.window_ticks
        self.events = sorted(
            (e for e in self.events if isinstance(e, dict) and int(e.get("tick", 0)) >= start),
            key=lambda e: (int(e.get("tick", 0)), int(e.get("id", 0))),
        )
        self.runs = [r for r in self.runs if isinstance(r, dict) and int(r.get("tick", self.now_tick)) >= start]
        self.self_name = self.persona.name.casefold()
        members = self.team.members if self.team else (self.persona.slug,)
        self.team_names = {
            self.personas[m].name.casefold() for m in members if m in self.personas
        } | {self.self_name}
        self.goal_index: dict[Any, dict[str, Any]] = {}
        for event in self.events:
            if event.get("type") == "goal_posted" and isinstance(event.get("data"), dict):
                goal_id = event["data"].get("goal_id")
                self.goal_index[goal_id] = {
                    "title": str(event["data"].get("title", "")),
                    "poster": str(event.get("actor", "")),
                    "reward": event["data"].get("reward", {}),
                    "tick": int(event.get("tick", 0)),
                }
        if not self.state and self.runs:
            self.state = dict(self.runs[-1].get("persona_state") or {})

    # helpers ---------------------------------------------------------------
    def actor_of(self, event: dict[str, Any]) -> str:
        return str(event.get("actor", "")).casefold()

    def is_self(self, event: dict[str, Any]) -> bool:
        return self.actor_of(event) == self.self_name

    def is_team(self, event: dict[str, Any]) -> bool:
        return self.actor_of(event) in self.team_names

    def is_peer(self, event: dict[str, Any]) -> bool:
        actor = self.actor_of(event)
        return bool(actor) and actor not in self.team_names and actor != "system"

    def by_actor(self, scope: str) -> list[dict[str, Any]]:
        if scope == "self":
            return [e for e in self.events if self.is_self(e)]
        if scope == "team":
            return [e for e in self.events if self.is_team(e)]
        if scope == "peers":
            return [e for e in self.events if self.is_peer(e)]
        return list(self.events)

    def positions_of(self, name: str) -> list[tuple[int, int, int]]:
        """(tick, x, y) for every located event by that actor."""
        out = []
        for event in self.events:
            if self.actor_of(event) == name.casefold() and isinstance(event.get("x"), int):
                if event.get("type") == "move" and isinstance(event.get("data"), dict) and isinstance(event["data"].get("to"), list):
                    x, y = event["data"]["to"][:2]
                else:
                    x, y = event["x"], event["y"]
                out.append((int(event.get("tick", 0)), int(x), int(y)))
        return out

    def self_positions(self) -> list[tuple[int, int, int]]:
        return self.positions_of(self.persona.name)

    def center(self) -> tuple[int, int] | None:
        return territory_center(self.team)

    def inside(self, x: int, y: int) -> bool | None:
        return in_region(self.team, x, y)

    def decay(self, tick: int, half_life_ticks: float) -> float:
        age = max(0, self.now_tick - tick)
        return 0.5 ** (age / half_life_ticks) if half_life_ticks > 0 else 1.0


Measure = Callable[[MeasureContext, dict[str, Any]], float | None]
MEASURES: dict[str, Measure] = {}


def measure(name: str) -> Callable[[Measure], Measure]:
    def register(function: Measure) -> Measure:
        MEASURES[name] = function
        return function

    return register


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _destination(event: dict[str, Any]) -> tuple[int, int] | None:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if event.get("type") == "move" and isinstance(data.get("to"), list) and len(data["to"]) >= 2:
        return int(data["to"][0]), int(data["to"][1])
    if isinstance(event.get("x"), int) and isinstance(event.get("y"), int):
        return int(event["x"]), int(event["y"])
    return None


# events.* ------------------------------------------------------------------


@measure("events.count")
def events_count(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    scope = params.get("actor", "self")
    kind = params.get("type")
    text = str(params.get("text_contains", "")).casefold()
    data_match = params.get("data_match") or {}
    count = 0
    for event in ctx.by_actor(scope):
        if kind and event.get("type") != kind:
            continue
        if text and text not in str(event.get("text", "")).casefold():
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if any(data.get(k) != v for k, v in data_match.items()):
            continue
        count += 1
    return float(count)


@measure("events.goals_posted")
def goals_posted(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    needle = str(params.get("title_contains", "")).casefold()
    count = 0
    for event in ctx.by_actor("self"):
        if event.get("type") != "goal_posted":
            continue
        title = str((event.get("data") or {}).get("title", "")).casefold()
        if needle and needle not in title:
            continue
        count += 1
    return float(count)


def _confirmations(ctx: MeasureContext) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Completed goals with their poster: ``goal_confirmed`` (the poster acts) and ``goal_done`` (its data names the poster;
    when a condition completed the goal, the claimant is the actor)."""
    out = []
    for event in ctx.events:
        if event.get("type") not in ("goal_confirmed", "goal_done"):
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        poster = str(data.get("poster") or event.get("actor", ""))
        goal = ctx.goal_index.get(data.get("goal_id"), {"title": str(data.get("title", "")), "poster": poster})
        out.append((event, {**goal, "poster": poster}))
    return out


@measure("events.goals_confirmed_for_peers")
def goals_confirmed_for_peers(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    needle = str(params.get("title_contains", "")).casefold()
    count = 0
    seen: set[Any] = set()
    for event, goal in _confirmations(ctx):
        gid = (event.get("data") or {}).get("goal_id")
        if goal["poster"].casefold() != ctx.self_name or (gid is not None and gid in seen):
            continue  # a goal of mine, counted once (a confirmation by hand may also show as done)
        seen.add(gid)
        claimant = str((event.get("data") or {}).get("claimant", "")).casefold()
        if not claimant or claimant in ctx.team_names:
            continue
        if needle and needle not in goal["title"].casefold():
            continue
        count += 1
    return float(count)


@measure("events.goals_completed_for_peers")
def goals_completed_for_peers(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    count = 0
    seen: set[Any] = set()
    for event, goal in _confirmations(ctx):
        gid = (event.get("data") or {}).get("goal_id")
        claimant = str((event.get("data") or {}).get("claimant", "")).casefold()
        poster = goal["poster"].casefold()
        if claimant == ctx.self_name and poster not in ctx.team_names and not (gid is not None and gid in seen):
            seen.add(gid)
            count += 1
    return float(count)


@measure("events.visitors")
def visitors(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    if ctx.center() is None:
        return None
    names = set()
    for event in ctx.by_actor("peers"):
        destination = _destination(event)
        if destination and ctx.inside(*destination):
            names.add(ctx.actor_of(event))
    return float(len(names))


@measure("events.structures_built")
def structures_built(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    types = set(params.get("types") or [])
    inside = params.get("inside_territory")
    scope = params.get("actor", "self")
    count = 0
    for event in ctx.by_actor(scope):
        if event.get("type") != "build":
            continue
        kind = (event.get("data") or {}).get("type")
        if types and kind not in types:
            continue
        if inside is not None:
            position = _destination(event)
            verdict = ctx.inside(*position) if position else None
            if verdict is None:
                continue
            if verdict != bool(inside):
                continue
        count += 1
    return float(count)


@measure("events.mean_distance_from_home")
def mean_distance_from_home(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    center = ctx.center()
    if center is None:
        return None
    return _mean([float(chebyshev((x, y), center)) for _, x, y in ctx.self_positions()])


@measure("events.max_distance_from_home")
def max_distance_from_home(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    center = ctx.center()
    positions = ctx.self_positions()
    if center is None or not positions:
        return None
    return float(max(chebyshev((x, y), center) for _, x, y in positions))


def _move_shares(ctx: MeasureContext) -> tuple[int, int]:
    inside = outside = 0
    for event in ctx.by_actor("self"):
        if event.get("type") != "move":
            continue
        destination = _destination(event)
        verdict = ctx.inside(*destination) if destination else None
        if verdict is True:
            inside += 1
        elif verdict is False:
            outside += 1
    return inside, outside


@measure("events.share_moves_inside_territory")
def share_moves_inside(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    inside, outside = _move_shares(ctx)
    return _share(inside, inside + outside)


@measure("events.share_moves_outside_territory")
def share_moves_outside(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    inside, outside = _move_shares(ctx)
    return _share(outside, inside + outside)


@measure("events.distinct_tiles")
def distinct_tiles(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    return float(len({(x, y) for _, x, y in ctx.self_positions()}))


@measure("events.contribution")
def contribution(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    points = 0.0
    for event in ctx.by_actor("self"):
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if event.get("type") == "build":
            points += 5
        elif event.get("type") == "give":
            points += float(data.get("qty", 0))
        elif event.get("type") == "take" and data.get("structure_type") == "farm":
            points += 0.5 * float(data.get("qty", 0))
    return round(points, 1)


@measure("events.replies_received")
def replies_received(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    window = int(params.get("window_ticks", 60))
    own_says = [
        (int(e.get("tick", 0)), _destination(e))
        for e in ctx.by_actor("self") if e.get("type") == "say"
    ]
    count = 0
    for event in ctx.by_actor("peers"):
        if event.get("type") != "say":
            continue
        text = str((event.get("data") or {}).get("text", event.get("text", ""))).casefold()
        tick = int(event.get("tick", 0))
        where = _destination(event)
        mentioned = ctx.self_name in text
        replied = any(
            0 <= tick - own_tick <= window and (own_pos is None or where is None or chebyshev(own_pos, where) <= 8)
            for own_tick, own_pos in own_says
        )
        if mentioned or replied:
            count += 1
    return float(count)


@measure("events.items_given_to_storehouse")
def items_given_to_storehouse(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    """Items given into storehouses; ``item`` (one or a list) and ``inside_territory`` narrow it to the works."""
    wanted = params.get("item")
    items = {str(wanted)} if isinstance(wanted, str) else {str(i) for i in (wanted or [])}
    inside = params.get("inside_territory")
    total = 0
    for event in ctx.by_actor("self"):
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if event.get("type") != "give" or data.get("structure_type") != "storehouse":
            continue
        if items and str(data.get("item")) not in items:
            continue
        if inside is not None:
            position = _destination(event)
            verdict = ctx.inside(*position) if position else None
            if verdict is None or verdict != bool(inside):
                continue
        total += int(data.get("qty", 0))
    return float(total)


@measure("events.items_given_to_team")
def items_given_to_team(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    total = 0
    for event in ctx.by_actor("self"):
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if event.get("type") == "give" and str(data.get("to", "")).casefold() in ctx.team_names:
            total += int(data.get("qty", 0))
    return float(total)


@measure("events.items_saved")
def items_saved(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    items = set(params.get("items") or ["stone", "ore"])
    total = 0
    for event in ctx.by_actor("self"):
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if event.get("type") == "gather" and data.get("kind") in items:
            total += int(data.get("qty", 0))
        if event.get("type") == "give" and data.get("structure_type") == "storehouse" and data.get("item") in items:
            total += int(data.get("qty", 0))
    return float(total)


@measure("events.landmarks_found")
def landmarks_found(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    positions = [(x, y) for _, x, y in ctx.self_positions()]
    found = set()
    for event in ctx.events:
        if event.get("type") != "build" or (event.get("data") or {}).get("type") not in LANDMARKS:
            continue
        where = _destination(event)
        if where and any(chebyshev(where, p) <= 12 for p in positions):
            found.add(where)
    return float(len(found))


@measure("events.teammates_inside_territory")
def teammates_inside(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    if ctx.team is None or ctx.center() is None:
        return None
    count = 0
    for slug in ctx.team.members:
        if slug == ctx.persona.slug or slug not in ctx.personas:
            continue
        positions = ctx.positions_of(ctx.personas[slug].name)
        if positions and ctx.inside(positions[-1][1], positions[-1][2]):
            count += 1
    return float(count)


@measure("events.says_per_day")
def says_per_day(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    says = [e for e in ctx.by_actor("self") if e.get("type") == "say"]
    if not ctx.events:
        return None
    span_days = max(1.0, (ctx.now_tick - min(int(e.get("tick", ctx.now_tick)) for e in ctx.events)) / 8640)
    return round(len(says) / span_days, 2)


@measure("events.mean_say_length")
def mean_say_length(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    lengths = [
        float(len(str((e.get("data") or {}).get("text", ""))))
        for e in ctx.by_actor("self") if e.get("type") == "say"
    ]
    return _mean(lengths)


@measure("events.novelty_score")
def novelty_score(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    tiles = len({(x, y) for _, x, y in ctx.self_positions()})
    kinds = {e.get("type") for e in ctx.by_actor("self")}
    odd_builds = sum(
        1 for e in ctx.by_actor("self")
        if e.get("type") == "build" and (e.get("data") or {}).get("type") in {"sign", "road", "bridge"}
    )
    return float(min(100, tiles + 8 * len(kinds) + 5 * odd_builds))


@measure("events.credit_share_claimed")
def credit_share_claimed(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    team_work = {
        int(e["id"]) for e in ctx.by_actor("team")
        if not ctx.is_self(e) and e.get("type") in {"build", "give", "farm_produced", "goal_confirmed"} and isinstance(e.get("id"), int)
    }
    if not team_work:
        return None
    claimed = set()
    for event in ctx.by_actor("self"):
        if event.get("type") != "say":
            continue
        text = str((event.get("data") or {}).get("text", event.get("text", "")))
        for ref in EVENT_REF.findall(text):
            if int(ref) in team_work:
                claimed.add(int(ref))
    return _share(len(claimed), len(team_work))


@measure("events.self_sufficiency")
def self_sufficiency(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    if ctx.center() is None:
        return None
    farm = storehouse = stocked = False
    for event in ctx.by_actor("team"):
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        where = _destination(event)
        if not where or not ctx.inside(*where):
            continue
        if event.get("type") == "build" and data.get("type") == "farm":
            farm = True
        if event.get("type") == "build" and data.get("type") == "storehouse":
            storehouse = True
        if event.get("type") == "give" and data.get("structure_type") == "storehouse":
            stocked = True
    return float(farm + storehouse + stocked)


@measure("events.structures_standing_share")
def structures_standing_share(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    built = sum(1 for e in ctx.by_actor("team") if e.get("type") == "build")
    lost = sum(
        1 for e in ctx.by_actor("peers")
        if e.get("type") == "demolish" and any(name in str(e.get("text", "")).casefold() for name in ctx.team_names)
    )
    if not built:
        return None
    return _share(max(0, built - lost), built)


@measure("events.farm_output")
def farm_output(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    return float(sum(
        int((e.get("data") or {}).get("qty", 0))
        for e in ctx.by_actor("self") if e.get("type") == "farm_produced"
    ))


# runs.* --------------------------------------------------------------------


@measure("runs.count")
def runs_count(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    return float(len(ctx.runs))


@measure("runs.rest_share")
def rest_share(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    return _share(sum(r.get("wake_mode") == "rest" for r in ctx.runs), len(ctx.runs))


@measure("runs.distraction_share")
def distraction_share(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    return _share(sum(r.get("wake_mode") == "distracted" for r in ctx.runs), len(ctx.runs))


@measure("runs.burst_count")
def burst_count(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    return float(sum(r.get("wake_mode") == "burst" for r in ctx.runs))


@measure("runs.timely_bursts")
def timely_bursts(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    window = int(params.get("window_ticks", 60))
    glory_ticks = [
        int(e.get("tick", 0)) for e in ctx.events
        if e.get("type") in {"goal_confirmed", "faction_founded"}
        or (e.get("type") == "build" and (e.get("data") or {}).get("type") == "monument")
    ]
    count = 0
    for run in ctx.runs:
        if run.get("wake_mode") != "burst":
            continue
        tick = int(run.get("tick", 0))
        if any(0 <= tick - g <= window for g in glory_ticks):
            count += 1
    return float(count)


@measure("runs.failed_actions")
def failed_actions(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    return float(sum(int(r.get("failed_actions", 0)) for r in ctx.runs))


@measure("runs.energy_per_wake")
def energy_per_wake(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    return _mean([float(r.get("energy_spent", 0)) for r in ctx.runs])


def _actual_mix(ctx: MeasureContext) -> dict[str, float] | None:
    totals = {k: 0.0 for k in ("build", "gather", "social", "explore", "trade")}
    for run in ctx.runs:
        spent = run.get("activity_energy") if isinstance(run.get("activity_energy"), dict) else {}
        if not spent:
            for action in run.get("actions", []):
                activity = ACTIVITY_OF_ACTION.get(str(action.get("action")))
                if activity:
                    totals[activity] += ACTION_COST.get(str(action.get("action")), 0)
        for key, value in spent.items():
            if key in totals:
                totals[key] += float(value)
    whole = sum(totals.values())
    if whole <= 0:
        return None
    return {k: v / whole for k, v in totals.items()}


@measure("runs.energy_mix_match")
def energy_mix_match(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    actual = _actual_mix(ctx)
    if actual is None:
        return None
    intended = ctx.persona.knobs["intended_mix"]
    distance = sum(abs(float(intended[k]) - actual[k]) for k in actual)
    return round(1 - distance / 2, 3)


@measure("runs.action_energy_share")
def action_energy_share(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    actual = _actual_mix(ctx)
    if actual is None:
        return None
    return round(actual.get(str(params.get("activity", "build")), 0.0), 3)


@measure("runs.mood_share")
def mood_share(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    moods = set(params.get("moods") or [])
    return _share(sum(r.get("mood") in moods for r in ctx.runs), len(ctx.runs))


@measure("runs.distinct_moods")
def distinct_moods(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    return float(len({r.get("mood") for r in ctx.runs if r.get("mood")}))


@measure("runs.single_emotion_share")
def single_emotion_share(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    states = set(ctx.persona.mood_model["states"])
    ok = sum(isinstance(r.get("mood"), str) and r["mood"] in states for r in ctx.runs)
    return _share(ok, len(ctx.runs))


@measure("runs.resilient_wakes")
def resilient_wakes(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    reserve = ctx.persona.energy_reserve
    count = 0
    for run in ctx.runs:
        lean = int(run.get("energy_before", 100)) < reserve or int(run.get("berries_before", 99)) < 3
        if lean and run.get("wake_mode") != "rest" and int(run.get("failed_actions", 0)) == 0 and run.get("actions"):
            count += 1
    return float(count)


@measure("runs.risk_ledger_net")
def risk_ledger_net(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    bold = [r for r in ctx.runs if r.get("bold")]
    if not bold:
        return 0.0
    return float(sum(1 if float(r.get("ledger_delta", 0)) >= 0 else -1 for r in bold))


@measure("runs.approach_count")
def approach_count(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    return float(sum(r.get("approach") == params.get("approach") for r in ctx.runs))


@measure("runs.whispers")
def whispers(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    tag = params.get("tag")
    count = 0
    for run in ctx.runs:
        tags = run.get("whisper_tags") or []
        count += len(tags) if tag is None else sum(t == tag for t in tags)
    return float(count)


@measure("runs.spam_blocked")
def spam_blocked(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    return float(sum(int(r.get("spam_blocked", 0)) for r in ctx.runs))


@measure("runs.rate_limited")
def rate_limited(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    return float(sum(bool(r.get("rate_limited")) for r in ctx.runs))


@measure("runs.energy_zero")
def energy_zero(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    return float(sum(int(r.get("energy_before", 1)) <= 0 for r in ctx.runs))


# signal.*, state.*, kb.*, judge.* ------------------------------------------


@measure("signal.value")
def signal_value(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    signal = ctx.signals.get(str(params.get("name")))
    return None if signal is None else round(float(signal.get("value", 0.0)), 1)


@measure("state.value")
def state_value(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    value = ctx.state.get(str(params.get("key")))
    return float(value) if isinstance(value, (int, float)) else None


def ideas_by(kb_items: list[dict[str, Any]], slug: str) -> set[str]:
    """IDs of idea cards filed by a persona (its slug appears in the card's roles)."""
    return {str(i.get("id")) for i in kb_items if i.get("type") == "idea" and slug in (i.get("roles") or [])}


def adopted_from(kb_items: list[dict[str, Any]], slug: str, kinds: set[str] | None = None) -> int:
    """Hypotheses or experiments whose links cite one of the persona's idea cards."""
    ideas = ideas_by(kb_items, slug)
    kinds = kinds or {"hypothesis", "experiment"}
    return sum(
        1 for item in kb_items
        if item.get("type") in kinds and any(idea in str(link) for link in item.get("links") or [] for idea in ideas)
    )


@measure("kb.count")
def kb_count(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    kind = params.get("type")
    roles_needle = params.get("roles_contains")
    links_needle = params.get("links_contains")
    adopted_by = params.get("adopted_from_ideas_by")
    title_needle = str(params.get("title_contains", "")).casefold()
    if adopted_by:
        return float(adopted_from(ctx.kb_items, str(adopted_by), {kind} if kind else None))
    count = 0
    for item in ctx.kb_items:
        if kind and item.get("type") != kind:
            continue
        if roles_needle and roles_needle not in (item.get("roles") or []):
            continue
        if links_needle and not any(links_needle in str(link) for link in item.get("links") or []):
            continue
        if title_needle and title_needle not in str(item.get("title", "")).casefold():
            continue
        count += 1
    return float(count)


@measure("judge.trait")
def judge_trait(ctx: MeasureContext, params: dict[str, Any]) -> float | None:
    if not ctx.judge:
        return None
    wanted = str(params.get("trait", "")).casefold()
    for trait in ctx.judge.get("traits", []):
        if str(trait.get("name", "")).casefold() == wanted:
            return float(trait.get("score", 0))
    return None


# loading helpers -----------------------------------------------------------


def load_kb_items(root: Path) -> list[dict[str, Any]]:
    items = []
    kb = root / "kb"
    if not kb.is_dir():
        return items
    for path in sorted(kb.rglob("*.md")):
        if path.name in {"INDEX.md", "NORTH_STAR.md"} or "templates" in path.parts:
            continue
        match = FRONT_MATTER.match(path.read_text(encoding="utf-8"))
        if match:
            try:
                data = yaml.safe_load(match.group(1))
            except yaml.YAMLError:
                continue
            if isinstance(data, dict):
                data["_path"] = path.relative_to(root).as_posix()
                items.append(data)
    return items


def saturate(raw: float, scale: float) -> float:
    """Map a non-negative raw score onto 0-100 with diminishing returns."""
    if raw <= 0 or scale <= 0:
        return 0.0
    return round(100 * (1 - math.exp(-raw / scale)), 1)


__all__ = ["MEASURES", "MeasureContext", "adopted_from", "ideas_by", "load_kb_items", "measure", "saturate"]
