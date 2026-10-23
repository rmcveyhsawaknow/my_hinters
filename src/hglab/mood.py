"""Mood models and persona state.

Mood lives in the private notebook under ``persona_state`` as compact JSON. Four models:

- ``steady``: one mood, always.
- ``mercurial``: swings between states driven by influence inputs plus a volatility roll.
- ``single_emotion``: exactly one active emotion per wake, chosen from events by precedence.
- ``lazy_bursts``: rests by default, bursts into life only when glory is near.

Every step is deterministic given the wake's random generator, so tests and dry runs replay.
"""

from __future__ import annotations

import json
import random
from typing import Any

from pydantic import BaseModel, Field

from hglab.persona import PERSONA_STATE_KEY, Persona, Team, chebyshev, in_territory

STATE_TEXT_LIMIT = 2000
GLORY_EVENT_TYPES = {"goal_confirmed", "monument", "faction_founded"}
HEADINGS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
HEADING_VECTORS = {
    "N": (0, -1), "NE": (1, -1), "E": (1, 0), "SE": (1, 1),
    "S": (0, 1), "SW": (-1, 1), "W": (-1, 0), "NW": (-1, -1),
}


class SignalInput(BaseModel):
    value: float = 0.0
    tick: int = 0
    explanation: str = ""


class PersonaState(BaseModel):
    mood: str
    since_tick: int = 0
    glow: int = 50
    inputs: dict[str, SignalInput] = Field(default_factory=dict)
    wakes: int = 0
    rests: int = 0
    bursts: int = 0
    distractions: int = 0
    last_wake_tick: int | None = None
    heading: str | None = None
    visited: list[str] = Field(default_factory=list)
    near_misses: int = 0
    claims: int = 0
    flags: dict[str, Any] = Field(default_factory=dict)

    def input_value(self, name: str, now_tick: int, half_life_ticks: int = 8640) -> float:
        """Latest value of an input, decayed by its age (half-life defaults to one real day)."""
        signal = self.inputs.get(name)
        if signal is None:
            return 0.0
        age = max(0, now_tick - signal.tick)
        return round(signal.value * 0.5 ** (age / half_life_ticks), 2)


def load_state(persona: Persona, notebook: dict[str, Any] | None) -> PersonaState:
    raw = (notebook or {}).get(PERSONA_STATE_KEY)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    if isinstance(raw, dict):
        try:
            state = PersonaState.model_validate(raw)
            if state.mood in persona.mood_model["states"]:
                return state
        except ValueError:
            pass
    return PersonaState(mood=persona.mood_model["initial"])


KEEP_LAST_FLAGS = {"house_site", "house", "house_step", "patrol", "site_asked", "faction_invited", "faction_switch", "faction_join_try", "closed_tiles", "full_stores"}  # the small flags a persona's plans hang on: dropped last of all


def dump_state(state: PersonaState) -> str:
    """Serialize within the notebook value limit, trimming the least needed parts first.

    Order: halve the visited history until it is gone, then the influence inputs, then the
    bulkier parts of the feature snapshot, then the world digest, then the snapshot itself
    (the next wake takes a fresh first look), then every flag. Each step removes something,
    so this always ends: a one-entry history used to be halved to itself forever once a
    grown feature snapshot pushed the state past the limit, and the wake hung in silence.
    """
    payload = state.model_dump(exclude_none=True)

    def text() -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    while len(text()) > STATE_TEXT_LIMIT and payload["visited"]:
        half = len(payload["visited"]) // 2
        payload["visited"] = payload["visited"][half:] if half else []
    flags = payload.setdefault("flags", {})
    features = flags.get("features") if isinstance(flags.get("features"), dict) else {}

    def shrink_engaged(keep: int) -> None:
        tables = flags.get("engaged") if isinstance(flags.get("engaged"), dict) else {}
        for kind, table in list(tables.items()):
            if isinstance(table, dict) and len(table) > keep:
                tables[kind] = dict(sorted(table.items(), key=lambda kv: -int(kv[1] or 0))[:keep])

    trims = (
        lambda: payload.__setitem__("inputs", {}),
        lambda: features.pop("agents", None),
        lambda: features.pop("action_row_hashes", None),
        lambda: features.pop("block_pieces", None),
        lambda: features.pop("observe_fields", None),
        lambda: flags.pop("world", None),
        lambda: shrink_engaged(4),
        lambda: shrink_engaged(2),
        lambda: features.pop("event_types", None),
        lambda: features.pop("event_types_seen", None),  # the kinds ever seen go last: without them every old kind is "new" again
        lambda: flags.pop("features", None),
        lambda: flags.pop("engaged", None),
        lambda: flags.pop("full_stores", None),
        lambda: payload.__setitem__("flags", {k: v for k, v in flags.items() if k in KEEP_LAST_FLAGS}),
        lambda: payload.__setitem__("flags", {}),
    )
    for trim in trims:
        if len(text()) <= STATE_TEXT_LIMIT:
            break
        trim()
    return text()


def apply_inputs(state: PersonaState, incoming: dict[str, dict[str, Any]], now_tick: int) -> PersonaState:
    """Record the latest value of each received effect; receivers use value and age."""
    for name, payload in incoming.items():
        state.inputs[name] = SignalInput(
            value=float(payload.get("value", 0.0)),
            tick=int(payload.get("tick", now_tick)),
            explanation=str(payload.get("explanation", ""))[:120],
        )
    return state


def wake_rng(persona: Persona, tick: int) -> random.Random:
    return random.Random(f"{persona.slug}:{tick}")


def team_actor_names(persona: Persona, team: Team | None, member_names: set[str] | None) -> set[str]:
    """Casefolded in-world names that count as 'us' when reading public events.

    Callers that know the personas pass ``member_names``; without them the slugs are used
    with dashes removed, which only matches names that happen to equal their slug.
    """
    names = {persona.name.casefold()}
    if member_names:
        names |= {n.casefold() for n in member_names}
    elif team is not None:
        names |= {m.replace("-", "").casefold() for m in team.members}
    return names


def step_mood(
    persona: Persona,
    state: PersonaState,
    observe: dict[str, Any],
    team: Team | None,
    rng: random.Random,
    *,
    member_names: set[str] | None = None,
) -> PersonaState:
    """Advance the mood for this wake. Exactly one state is active afterwards."""
    model = persona.mood_model
    kind = model["type"]
    states = list(model["states"])
    tick = int(observe.get("tick", 0))
    previous = state.mood
    ours = team_actor_names(persona, team, member_names)
    if kind == "steady":
        state.mood = model["initial"]
    elif kind == "mercurial":
        state.mood = _mercurial(model, state, tick, rng)
    elif kind == "single_emotion":
        state.mood = _single_emotion(persona, model, state, observe, team, tick, ours)
    elif kind == "lazy_bursts":
        state.mood = _lazy_bursts(persona, model, state, observe, team, ours)
    else:
        raise ValueError(f"unknown mood model {kind!r}")
    if state.mood not in states:
        state.mood = model["initial"]
    if state.mood != previous:
        state.since_tick = tick
    return state


def _mercurial(model: dict[str, Any], state: PersonaState, tick: int, rng: random.Random) -> str:
    params = model.get("params", {})
    volatility = float(params.get("volatility", 0.3))
    high = float(params.get("high", 60))
    inspiration = state.input_value("inspiration", tick)
    suspicion = state.input_value("suspicion", tick)
    states = list(model["states"])
    if suspicion >= high and "deadpan" in states:
        return "deadpan"
    if inspiration >= high and "manic" in states:
        return "manic"
    if rng.random() < volatility:
        return rng.choice(states)
    return str(model["initial"])


def _single_emotion(
    persona: Persona,
    model: dict[str, Any],
    state: PersonaState,
    observe: dict[str, Any],
    team: Team | None,
    tick: int,
    team_names: set[str],
) -> str:
    """One feeling at a time, by precedence: fury, jealousy, joy, mischief, sulk, devotion."""
    states = set(model["states"])
    you = observe.get("you") or {}
    name = str(you.get("name", persona.name)).casefold()
    events = [e for e in observe.get("events", []) if isinstance(e, dict)]
    belief = state.input_value("belief", tick)
    courage = state.input_value("courage", tick)
    escape = state.input_value("escape", tick)
    if "glow" in state.inputs:
        state.glow = int(max(0, min(100, round(state.input_value("glow", tick)))))
    else:
        state.glow = int(max(0, min(100, round(50 + 0.4 * belief + 0.3 * courage - 0.4 * escape))))
    damaged = any(
        e.get("type") == "demolish"
        and str(e.get("actor", "")).casefold() not in team_names
        and name in str(e.get("text", "")).casefold()
        for e in events
    )
    if damaged and "fury" in states:
        return "fury"
    if escape >= 50 and "jealousy" in states:
        return "jealousy"
    arrivals = any(
        e.get("type") == "move"
        and str(e.get("actor", "")).casefold() in team_names
        and isinstance(e.get("data"), dict)
        and isinstance(e["data"].get("to"), list)
        and in_territory(team, int(e["data"]["to"][0]), int(e["data"]["to"][1])) is True
        for e in events
    )
    if (belief >= 60 or arrivals) and "joy" in states:
        return "joy"
    visitors = [
        a for a in observe.get("agents", [])
        if isinstance(a, dict) and str(a.get("name", "")).casefold() not in team_names
    ]
    if visitors and state.glow >= 35 and "mischief" in states:
        return "mischief"
    if state.glow < 35 and "sulk" in states:
        return "sulk"
    return "devotion" if "devotion" in states else str(model["initial"])


def _lazy_bursts(
    persona: Persona,
    model: dict[str, Any],
    state: PersonaState,
    observe: dict[str, Any],
    team: Team | None,
    team_names: set[str],
) -> str:
    states = list(model["states"])
    burst_state = next((s for s in states if s != model["initial"]), model["initial"])
    for event in observe.get("events", []):
        if not isinstance(event, dict):
            continue
        actor = str(event.get("actor", "")).casefold()
        glory = event.get("type") in GLORY_EVENT_TYPES or (
            event.get("type") == "build"
            and isinstance(event.get("data"), dict)
            and event["data"].get("type") == "monument"
        )
        if glory and (actor in team_names or _mentions_team(event, team_names)):
            return burst_state
    return str(model["initial"])


def _mentions_team(event: dict[str, Any], team_names: set[str]) -> bool:
    text = str(event.get("text", "")).casefold()
    return any(name in text for name in team_names)


def decide_wake_mode(
    persona: Persona, state: PersonaState, observe: dict[str, Any], rng: random.Random
) -> str:
    """rest | act | burst | distracted, from mood, rest probability and the quirk."""
    model = persona.mood_model
    quirk = persona.quirk
    if model["type"] == "lazy_bursts" and state.mood != model["initial"]:
        return "burst"
    if quirk["type"] == "distraction_roll":
        probability = float(quirk.get("params", {}).get("probability", 0.4))
        if rng.random() < probability:
            return "distracted"
    if rng.random() < float(persona.knobs["rest_probability"]):
        return "rest"
    return "act"


def next_heading(current: str | None, rng: random.Random, rule: str = "second_star") -> str:
    """Tinkerglow's rule: from the last heading, take the second turn to the right."""
    if current not in HEADINGS:
        return rng.choice(HEADINGS)
    index = HEADINGS.index(current)
    if rule == "second_star":
        return HEADINGS[(index + 2) % len(HEADINGS)]
    return HEADINGS[(index + 1) % len(HEADINGS)]


def record_wake(state: PersonaState, mode: str, tick: int, position: tuple[int, int] | None) -> None:
    state.wakes += 1
    state.last_wake_tick = tick
    if mode == "rest":
        state.rests += 1
    elif mode == "burst":
        state.bursts += 1
    elif mode == "distracted":
        state.distractions += 1
    if position is not None:
        key = f"{position[0]},{position[1]}"
        if key not in state.visited:
            state.visited.append(key)
        if len(state.visited) > 120:
            state.visited = state.visited[-120:]


def note_near_miss(state: PersonaState, observe: dict[str, Any], window_ticks: int = 60) -> bool:
    """Lagalong arrives just after something big happened within view."""
    tick = int(observe.get("tick", 0))
    you = observe.get("you") or {}
    position = (you.get("x"), you.get("y"))
    for event in observe.get("events", []):
        if not isinstance(event, dict):
            continue
        big = event.get("type") in GLORY_EVENT_TYPES or (
            event.get("type") == "build"
            and isinstance(event.get("data"), dict)
            and event["data"].get("type") in {"monument", "tower"}
        )
        if not big or not isinstance(event.get("tick"), int):
            continue
        recent = 0 < tick - event["tick"] <= window_ticks and all(isinstance(v, int) for v in position)
        if recent and chebyshev(
            (int(position[0]), int(position[1])), (int(event.get("x", 0)), int(event.get("y", 0)))
        ) <= 12:
            state.near_misses += 1
            return True
    return False


__all__ = [
    "HEADINGS",
    "HEADING_VECTORS",
    "PERSONA_STATE_KEY",
    "PersonaState",
    "SignalInput",
    "apply_inputs",
    "decide_wake_mode",
    "dump_state",
    "load_state",
    "next_heading",
    "note_near_miss",
    "record_wake",
    "step_mood",
    "team_actor_names",
    "wake_rng",
]
