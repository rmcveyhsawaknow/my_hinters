"""Influence links: teammates shape each other through recomputable signals.

Each signal is one function over public events plus our redacted run records. It is
bounded 0-100, decays with the link's half-life, and comes with a one-sentence
explanation. Receivers store the latest value and its age in ``persona_state`` and
read it on their next wake, so signals arrive asynchronously across schedules.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hglab.measures import HARD_BUILDS, MeasureContext, adopted_from, ideas_by, saturate
from hglab.persona import Persona, Team, chebyshev

DAY_TICKS = 8640  # one real day of ticks (360 ticks per in-world day, 24 in-world days)


@dataclass
class SignalResult:
    name: str
    value: float
    explanation: str
    parts: dict[str, float]


Signal = Callable[[MeasureContext], SignalResult]
SIGNALS: dict[str, Signal] = {}


def signal(name: str) -> Callable[[Signal], Signal]:
    def register(function: Signal) -> Signal:
        SIGNALS[name] = function
        return function

    return register


def _decayed_sum(ctx: MeasureContext, items: list[tuple[int, float]], half_life: float = DAY_TICKS) -> float:
    return sum(points * ctx.decay(tick, half_life) for tick, points in items)


def _data(event: dict[str, Any]) -> dict[str, Any]:
    return event.get("data") if isinstance(event.get("data"), dict) else {}


def _where(event: dict[str, Any]) -> tuple[int, int] | None:
    data = _data(event)
    if event.get("type") == "move" and isinstance(data.get("to"), list) and len(data["to"]) >= 2:
        return int(data["to"][0]), int(data["to"][1])
    if isinstance(event.get("x"), int) and isinstance(event.get("y"), int):
        return int(event["x"]), int(event["y"])
    return None


@signal("hope")
def hope(ctx: MeasureContext) -> SignalResult:
    """Contribution + uplift + resilience, each decayed over a real day."""
    contribution: list[tuple[int, float]] = []
    for event in ctx.by_actor("self"):
        tick = int(event.get("tick", 0))
        data = _data(event)
        if event.get("type") == "build":
            contribution.append((tick, 5))
        elif event.get("type") == "give":
            contribution.append((tick, float(data.get("qty", 0))))
        elif event.get("type") == "take" and data.get("structure_type") == "farm":
            contribution.append((tick, 0.5 * float(data.get("qty", 0))))
    replies = [
        (int(e.get("tick", 0)), 4.0) for e in ctx.by_actor("peers")
        if e.get("type") == "say" and ctx.self_name in str(_data(e).get("text", e.get("text", ""))).casefold()
    ]
    supportive = [
        (int(r.get("tick", ctx.now_tick)), 3.0 * sum(t == "supportive" for t in (r.get("whisper_tags") or [])))
        for r in ctx.runs
    ]
    resilient = [
        (int(r.get("tick", ctx.now_tick)), 4.0) for r in ctx.runs
        if (int(r.get("energy_before", 100)) < ctx.persona.energy_reserve or int(r.get("berries_before", 99)) < 3)
        and r.get("wake_mode") != "rest" and int(r.get("failed_actions", 0)) == 0 and r.get("actions")
    ]
    parts = {
        "contribution": round(_decayed_sum(ctx, contribution), 1),
        "uplift": round(_decayed_sum(ctx, replies) + _decayed_sum(ctx, supportive), 1),
        "resilience": round(_decayed_sum(ctx, resilient), 1),
    }
    value = saturate(sum(parts.values()), 150)
    return SignalResult(
        "hope", value,
        f"Hope {value:.0f}: contribution {parts['contribution']:.0f}, uplift {parts['uplift']:.0f},"
        f" resilience {parts['resilience']:.0f} (decayed over a day).",
        parts,
    )


@signal("bluster")
def bluster(ctx: MeasureContext) -> SignalResult:
    """Credit claims relative to own verifiable work, plus the share of a teammate's work claimed."""
    claims: list[tuple[int, float]] = []
    claimed_refs: set[int] = set()
    for event in ctx.by_actor("self"):
        if event.get("type") != "say":
            continue
        text = str(_data(event).get("text", event.get("text", "")))
        from hglab.measures import EVENT_REF

        refs = [int(r) for r in EVENT_REF.findall(text)]
        if refs or "my idea" in text.casefold() or "my doing" in text.casefold():
            claims.append((int(event.get("tick", 0)), 10.0))
            claimed_refs.update(refs)
    for run in ctx.runs:
        if run.get("approach") == "credit_claim" and not any(a.get("action") == "say" for a in run.get("actions", [])):
            claims.append((int(run.get("tick", ctx.now_tick)), 5.0))
    own_work = [
        (int(e.get("tick", 0)), 5.0 if e.get("type") == "build" else float(_data(e).get("qty", 0)))
        for e in ctx.by_actor("self") if e.get("type") in {"build", "give"}
    ]
    team_work_ids = {
        int(e["id"]) for e in ctx.by_actor("team")
        if not ctx.is_self(e) and e.get("type") in {"build", "give", "farm_produced", "goal_confirmed"} and isinstance(e.get("id"), int)
    }
    share = len(claimed_refs & team_work_ids) / len(team_work_ids) if team_work_ids else 0.0
    claim_points = _decayed_sum(ctx, claims)
    own_points = _decayed_sum(ctx, own_work)
    raw = claim_points / (1 + own_points) + 100 * share
    value = saturate(raw, 80)
    parts = {"claims": round(claim_points, 1), "own_work": round(own_points, 1), "share_of_team_work_claimed": round(share, 2)}
    return SignalResult(
        "bluster", value,
        f"Bluster {value:.0f}: {len(claims)} claim(s) against own work {own_points:.0f},"
        f" {share:.0%} of the team's logged work claimed.",
        parts,
    )


def _team_bridges(ctx: MeasureContext, builder_slug: str) -> set[tuple[int, int]]:
    builder = ctx.personas.get(builder_slug)
    if builder is None:
        return set()
    name = builder.name.casefold()
    return {
        w for e in ctx.events
        if ctx.actor_of(e) == name and e.get("type") == "build" and _data(e).get("type") == "bridge"
        and (w := _where(e)) is not None
    }


@signal("belief")
def belief(ctx: MeasureContext) -> SignalResult:
    """Arriving where the pathfinder pointed, using her bridges, staying inside."""
    leader = next((s for s in (ctx.team.members if ctx.team else ()) if ctx.personas.get(s) and "navigator" in ctx.personas[s].roles), None)
    bridges = _team_bridges(ctx, leader) if leader else set()
    arrivals: list[tuple[int, float]] = []
    crossings: list[tuple[int, float]] = []
    positions = ctx.self_positions()
    for event in ctx.by_actor("self"):
        if event.get("type") != "move":
            continue
        where = _where(event)
        tick = int(event.get("tick", 0))
        if where and ctx.inside(*where):
            arrivals.append((tick, 5.0))
        if where and any(chebyshev(where, b) <= 1 for b in bridges):
            crossings.append((tick, 4.0))
    staying = 10.0 if positions and ctx.inside(positions[-1][1], positions[-1][2]) else 0.0
    parts = {
        "arrivals": round(_decayed_sum(ctx, arrivals), 1),
        "bridge_crossings": round(_decayed_sum(ctx, crossings), 1),
        "staying": staying,
    }
    value = saturate(sum(parts.values()), 20)
    return SignalResult(
        "belief", value,
        f"Belief {value:.0f}: {len(arrivals)} arrival(s) inside, {len(crossings)} bridge crossing(s),"
        f" {'staying' if staying else 'not currently'} inside.",
        parts,
    )


@signal("escape")
def escape(ctx: MeasureContext) -> SignalResult:
    """Time and distance spent outside the territory."""
    center = ctx.center()
    moves = [e for e in ctx.by_actor("self") if e.get("type") == "move"]
    outside = 0
    farthest = 0
    for event in moves:
        where = _where(event)
        if not where:
            continue
        verdict = ctx.inside(*where)
        if verdict is False:
            outside += 1
        if center is not None:
            farthest = max(farthest, chebyshev(where, center))
    share = outside / len(moves) if moves else 0.0
    value = round(min(100.0, 50 * share + min(50.0, farthest / 2)), 1)
    parts = {"share_outside": round(share, 2), "farthest": float(farthest)}
    return SignalResult(
        "escape", value,
        f"Escape {value:.0f}: {share:.0%} of moves outside, farthest {farthest} tiles from the centre.",
        parts,
    )


@signal("courage")
def courage(ctx: MeasureContext) -> SignalResult:
    """Hard jobs inside the territory, visitors greeted, structures kept standing."""
    hard: list[tuple[int, float]] = []
    for event in ctx.by_actor("self"):
        if event.get("type") == "build" and _data(event).get("type") in HARD_BUILDS:
            where = _where(event)
            if where and ctx.inside(*where) is not False:
                hard.append((int(event.get("tick", 0)), 10.0))
    greetings = [(int(r.get("tick", ctx.now_tick)), 5.0) for r in ctx.runs if r.get("approach") == "greet"]
    built = sum(1 for e in ctx.by_actor("team") if e.get("type") == "build")
    lost = sum(1 for e in ctx.by_actor("peers") if e.get("type") == "demolish" and any(n in str(e.get("text", "")).casefold() for n in ctx.team_names))
    standing = 10.0 * (max(0, built - lost) / built) if built else 0.0
    parts = {"hard_jobs": round(_decayed_sum(ctx, hard), 1), "greetings": round(_decayed_sum(ctx, greetings), 1), "standing": round(standing, 1)}
    value = saturate(sum(parts.values()), 25)
    return SignalResult(
        "courage", value,
        f"Courage {value:.0f}: {len(hard)} hard job(s) inside, {len(greetings)} greeting(s), structures standing {standing / 10:.0%}.",
        parts,
    )


@signal("discoveries")
def discoveries(ctx: MeasureContext) -> SignalResult:
    """New ground, new action types, idea cards filed, and cards others adopted."""
    tiles = len({(x, y) for _, x, y in ctx.self_positions()})
    kinds = len({e.get("type") for e in ctx.by_actor("self")})
    ideas = len(ideas_by(ctx.kb_items, ctx.persona.slug))
    adopted = adopted_from(ctx.kb_items, ctx.persona.slug)
    parts = {"new_tiles": float(tiles), "action_types": float(kinds), "ideas_filed": float(ideas), "adopted": float(adopted)}
    raw = 0.5 * tiles + 3 * kinds + 10 * ideas + 15 * adopted
    value = saturate(raw, 30)
    return SignalResult(
        "discoveries", value,
        f"Discoveries {value:.0f}: {tiles} tiles, {kinds} action types, {ideas} idea card(s), {adopted} adopted.",
        parts,
    )


@signal("audit")
def audit(ctx: MeasureContext) -> SignalResult:
    """Fairness of Fudgewright's credit audits: share that credited the worker the log supports."""
    audits = [r for r in ctx.runs if isinstance(r.get("audit"), dict)]
    if not audits:
        return SignalResult("audit", 50.0, "Fairness 50: no audits recorded yet.", {"audits": 0.0, "correct": 0.0})
    correct = sum(bool(r["audit"].get("correct")) for r in audits)
    value = round(100 * correct / len(audits), 1)
    return SignalResult(
        "audit", value,
        f"Fairness {value:.0f}: {correct} of {len(audits)} audit(s) credited the true worker.",
        {"audits": float(len(audits)), "correct": float(correct)},
    )


def compute_team(
    team: Team,
    personas: dict[str, Persona],
    events: list[dict[str, Any]],
    runs_by_slug: dict[str, list[dict[str, Any]]],
    now_tick: int,
    *,
    kb_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute every link of a team. Returns signals per member and links with values."""
    contexts = {
        slug: MeasureContext(
            persona=personas[slug], team=team, personas=personas, events=events,
            runs=runs_by_slug.get(slug, []), now_tick=now_tick, kb_items=kb_items or [],
        )
        for slug in team.members if slug in personas
    }
    signals: dict[str, dict[str, Any]] = {slug: {} for slug in contexts}
    for slug, ctx in contexts.items():
        for name in personas[slug].signals_emitted:
            if name in SIGNALS:
                result = SIGNALS[name](ctx)
                signals[slug][name] = {
                    "value": result.value, "explanation": result.explanation,
                    "parts": result.parts, "tick": now_tick,
                }
    links = []
    for link in team.links:
        source = signals.get(link["from"], {}).get(link["signal"])
        if source is None:
            continue
        half_life = float(link.get("half_life_hours", 24)) * 360
        age_ticks = now_tick - int(source["tick"])
        decayed = round(source["value"] * 0.5 ** (max(0, age_ticks) / half_life), 1)
        links.append({
            **{k: link[k] for k in ("from", "signal", "to", "effect", "plain_english")},
            "weight": float(link.get("weight", 1.0)),
            "half_life_hours": float(link.get("half_life_hours", 24)),
            "value": source["value"],
            "decayed_value": decayed,
            "age_ticks": age_ticks,
            "explanation": source["explanation"],
        })
    return {"team": team.slug, "tick": now_tick, "signals": signals, "links": links}


def incoming_effects(team_result: dict[str, Any], slug: str) -> dict[str, dict[str, Any]]:
    """Fold a team computation into the effects one receiver stores in persona_state.

    Effects sum weighted decayed values; ``glow`` starts from a neutral 50 so negative
    weights can dim it. Raw signal names are kept too so mood models can read them.
    """
    sums: dict[str, float] = {}
    notes: dict[str, list[str]] = {}
    raw: dict[str, dict[str, Any]] = {}
    for link in team_result.get("links", []):
        if link["to"] != slug:
            continue
        sums[link["effect"]] = sums.get(link["effect"], 0.0) + link["weight"] * link["decayed_value"]
        notes.setdefault(link["effect"], []).append(f"{link['signal']} from {link['from']} {link['decayed_value']:.0f}")
        raw[link["signal"]] = {"value": link["decayed_value"], "tick": team_result["tick"], "explanation": link["explanation"]}
    effects: dict[str, dict[str, Any]] = {}
    for effect, total in sums.items():
        base = 50.0 if effect == "glow" else 0.0
        value = max(0.0, min(100.0, base + total))
        effects[effect] = {"value": round(value, 1), "tick": team_result["tick"], "explanation": "; ".join(notes[effect])}
    for name, payload in raw.items():
        effects.setdefault(name, payload)
    return effects


__all__ = ["SIGNALS", "SignalResult", "compute_team", "incoming_effects", "signal"]


@signal("architectures")
def architectures(ctx: MeasureContext) -> SignalResult:
    """Blueprint types raised, workshop notes said in public, signs written, idea cards filed: the research output."""
    mine = ctx.by_actor("self")
    kinds = {str((e.get("data") or {}).get("type") or "") for e in mine if e.get("type") == "build"}
    kinds.discard("")
    notes = sum(1 for e in mine if e.get("type") == "say" and "workshop note" in str(e.get("text") or "").casefold())
    signs = sum(1 for e in mine if e.get("type") == "build" and (e.get("data") or {}).get("type") == "sign")
    ideas = len(ideas_by(ctx.kb_items, ctx.persona.slug))
    parts = {"blueprint_types": float(len(kinds)), "notes": float(notes), "signs": float(signs), "ideas_filed": float(ideas)}
    raw = 4 * len(kinds) + 3 * notes + 2 * signs + 10 * ideas
    value = saturate(raw, 30)
    return SignalResult(
        "architectures", value,
        f"Architectures {value:.0f}: {len(kinds)} blueprint type(s), {notes} note(s), {signs} sign(s), {ideas} idea card(s).",
        parts,
    )

