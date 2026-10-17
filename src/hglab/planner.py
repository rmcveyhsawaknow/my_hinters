"""Deterministic, persona-driven wake planner.

This planner needs no model. It turns a persona's knobs, mood and quirk into one to
four concrete actions with a reason each, so personality lives in code: schedules,
energy habits, risk, territory, social rhythm and mood all change what gets proposed.
The LLM path (when a key is present) is validated by the same knobs; when its plan is
rejected, this planner is the fallback. It never speaks except where a quirk demands a
line (a greeting, a credit claim), and it never claims goals blindly.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from typing import Any

from hglab.mood import HEADING_VECTORS, PersonaState, next_heading, note_near_miss
from hglab.persona import (
    MOVE_STEP_CAP,
    Persona,
    Team,
    chebyshev,
    in_region,
    in_territory,
    territory_center,
)

WALKABLE = set("sgfh")
BLUEPRINTS: dict[str, dict[str, int]] = {
    "sign": {"wood": 1},
    "road": {"stone": 1},
    "wall": {"stone": 2},
    "bridge": {"wood": 15},
    "hut": {"wood": 10, "fiber": 4},
    "farm": {"fiber": 5, "wood": 5},
    "storehouse": {"wood": 20, "stone": 10},
    "tower": {"stone": 30, "wood": 10},
    "monument": {"stone": 50, "ore": 10},
}
DEFAULT_BUILD_PRIORITY = ["hut", "farm", "storehouse", "road"]
NODE_FLOOR = 5  # never take a node below this many units: local norm, never strip nodes
ACTIVITIES = ("build", "gather", "social", "explore", "trade")


@dataclass
class WorldView:
    x0: int = 0
    y0: int = 0
    rows: list[str] = field(default_factory=list)
    structures: list[dict[str, Any]] = field(default_factory=list)
    resources: list[dict[str, Any]] = field(default_factory=list)
    agents: list[dict[str, Any]] = field(default_factory=list)
    full_map: list[str] | None = None

    @classmethod
    def from_observe(cls, observe: dict[str, Any], terrain_rows: list[str] | None = None) -> WorldView:
        view = observe.get("view") if isinstance(observe.get("view"), dict) else {}
        rows = view.get("rows") or []
        return cls(
            x0=int(view.get("x0", 0)),
            y0=int(view.get("y0", 0)),
            rows=[str(r) for r in rows],
            structures=[s for s in observe.get("structures", []) if isinstance(s, dict)],
            resources=[r for r in observe.get("resources", []) if isinstance(r, dict)],
            agents=[a for a in observe.get("agents", []) if isinstance(a, dict)],
            full_map=terrain_rows,
        )

    def terrain(self, x: int, y: int) -> str | None:
        if self.rows:
            ry, rx = y - self.y0, x - self.x0
            if 0 <= ry < len(self.rows) and 0 <= rx < len(self.rows[ry]):
                return self.rows[ry][rx]
        if self.full_map and 0 <= y < len(self.full_map) and 0 <= x < len(self.full_map[y]):
            return self.full_map[y][x]
        return None

    def structure_at(self, x: int, y: int) -> dict[str, Any] | None:
        for structure in self.structures:
            if structure.get("x") == x and structure.get("y") == y:
                return structure
        return None

    def walkable(self, x: int, y: int) -> bool:
        if not (0 <= x < 128 and 0 <= y < 128):
            return False
        code = self.terrain(x, y)
        structure = self.structure_at(x, y)
        if structure and structure.get("type") == "bridge":
            return True
        if structure and structure.get("type") == "wall":
            return False
        return code in WALKABLE

    def free_tile(self, x: int, y: int, terrain_ok: set[str] | None = None) -> bool:
        if not (0 <= x < 128 and 0 <= y < 128) or self.structure_at(x, y):
            return False
        code = self.terrain(x, y)
        if terrain_ok is not None:
            return code in terrain_ok
        return code in WALKABLE

    def known(self) -> bool:
        return bool(self.rows or self.full_map)


def neighbours(x: int, y: int) -> list[tuple[int, int]]:
    return [
        (x + dx, y + dy)
        for dx in (-1, 0, 1)
        for dy in (-1, 0, 1)
        if (dx, dy) != (0, 0) and 0 <= x + dx < 128 and 0 <= y + dy < 128
    ]


def materials_ok(inventory: dict[str, int], blueprint: str) -> bool:
    return all(int(inventory.get(item, 0)) >= qty for item, qty in BLUEPRINTS[blueprint].items())


def shortfall(inventory: dict[str, int], blueprint: str) -> dict[str, int]:
    return {
        item: qty - int(inventory.get(item, 0))
        for item, qty in BLUEPRINTS[blueprint].items()
        if int(inventory.get(item, 0)) < qty
    }


def plan_wake(
    persona: Persona,
    team: Team | None,
    state: PersonaState,
    observe: dict[str, Any],
    mode: str,
    rng: random.Random,
    *,
    teammates: dict[str, tuple[int, int]] | None = None,
    terrain_rows: list[str] | None = None,
    allowed: set[str] | None = None,
    team_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return ``{summary, actions, reasons, approach, remember}`` for one wake.

    ``allowed`` restricts proposals to the hat(s) worn this wake; steps needing other
    actions are skipped. The plan never drops projected energy below the reserve.
    """
    you = observe.get("you") or {}
    position = (int(you.get("x", 0)), int(you.get("y", 0)))
    energy = int(you.get("energy", 0) or 0)
    inventory = {k: int(v) for k, v in (you.get("inventory") or {}).items()}
    home = you.get("home") if isinstance(you.get("home"), dict) else None
    view = WorldView.from_observe(observe, terrain_rows)
    cap = persona.actions_per_wake
    reserve = persona.energy_reserve
    names = dict(team_names or {})
    names.setdefault(persona.name.casefold(), persona.slug)
    actions: list[dict[str, Any]] = []
    reasons: list[str] = []
    remember: list[dict[str, str]] = []
    approach: str | None = None
    mood = state.mood

    if persona.quirk["type"] == "near_miss_log" and note_near_miss(state, observe):
        reasons.append("arrived just after something big happened nearby: one more near miss")

    if energy < reserve:
        berries = inventory.get("berries", 0)
        if berries > 0:
            need = max(1, -(-(reserve - energy) // 15))
            actions.append({"action": "eat", "qty": min(need, berries)})
            reasons.append(f"energy {energy} is under the reserve {reserve}: eat first")
        else:
            homeward = _step_toward(position, home, view) if home else None
            if homeward and homeward != position:
                actions.append({"action": "move", "x": homeward[0], "y": homeward[1]})
                reasons.append("no berries and low energy: head home to rest beside the hut")
            else:
                reasons.append("no berries and low energy: rest where I stand")
            return _result(persona, mood, "resting to recover", actions, reasons, "rest", remember)

    if mode == "rest":
        return _result(persona, mood, _rest_line(persona, mood), actions, reasons, "rest", remember)

    if mode == "distracted" and (allowed is None or "move" in allowed):
        target = _novel_target(position, view, rng, state, persona, team, teammates, 5, 9)
        if target and chebyshev(position, target) <= max(0, energy - reserve):
            actions.append({"action": "move", "x": target[0], "y": target[1]})
            shiny = _shiny_thing(view, target)
            reasons.append(f"distraction roll won: something shiny toward {target} ({shiny})")
            ideas = list(state.flags.get("ideas", []))
            ideas.append(f"t{observe.get('tick', 0)}: {shiny} near {target[0]},{target[1]}")
            state.flags["ideas"] = ideas[-5:]
        approach = "distraction"
        return _result(persona, mood, "chasing something new", actions, reasons, approach, remember)

    if mode == "burst" and persona.quirk["type"] == "credit_claim":
        line, event_ref = _credit_claim(persona, team, observe, rng, names)
        if line and (allowed is None or "say" in allowed) and energy - 1 >= reserve:
            actions.append({"action": "say", "text": line})
            reasons.append(f"glory is near (event {event_ref}): claim a share of it, in character")
            state.claims += 1
        approach = "credit_claim"
        return _result(persona, mood, "springing to life for the glory", actions, reasons, approach, remember)

    audit: dict[str, Any] | None = None
    if persona.quirk["type"] == "honesty_test" and (allowed is None or "whisper" in allowed):
        audit_step = _plan_audit(persona, team, observe, names)
        if audit_step is not None:
            audit_actions, audit_reason, audit = audit_step
            if energy - 1 >= reserve:
                actions.extend(audit_actions)
                reasons.append(audit_reason)
                approach = "audit"
    budget = cap if mood != "sulk" else 1
    spendable = energy + 15 * sum(min(int(a.get("qty") or 0), inventory.get("berries", 0)) for a in actions if a.get("action") == "eat") - reserve
    here = position
    for activity in _activity_order(persona, state, rng):
        if len(actions) >= budget:
            break
        if activity == "build":
            # builds are validated against the observed position, so only before any move
            step = _plan_build(persona, team, inventory, here, view, home) if here == position else None
        elif activity == "gather":
            step = _plan_gather(persona, team, inventory, here, view, teammates, rng)
        elif activity == "explore":
            step = _plan_explore(persona, team, state, here, view, rng, teammates)
        elif activity == "social":
            step = _plan_social(persona, team, state, inventory, here, view, observe, teammates, names)
        else:
            step = _plan_trade(persona, team, observe, remember, names)
        if not step:
            continue
        new_actions, reason, tag = step
        if allowed is not None and any(a.get("action") not in allowed for a in new_actions):
            continue
        if len(actions) + len(new_actions) > budget:
            continue  # a step is all or nothing: a trip without its gather is wasted energy
        if any(
            a.get("action") == "move" and chebyshev(position, (int(a["x"]), int(a["y"]))) > MOVE_STEP_CAP
            for a in new_actions
        ):
            continue  # every target is checked against where the wake started
        cost = _estimate(new_actions, here)
        if cost > spendable:
            reasons.append(f"skipped {activity}: it would cost {cost} and only {max(0, spendable)} is spendable above the reserve")
            continue
        spendable -= cost
        for action in new_actions:
            if action.get("action") == "move" and action.get("x") is not None:
                here = (int(action["x"]), int(action["y"]))
        actions.extend(new_actions)
        reasons.append(reason)
        approach = approach or tag
    summary = _summary(persona, mood, approach)
    result = _result(persona, mood, summary, actions, reasons, approach, remember)
    if audit is not None:
        result["audit"] = audit
    return result


def _plan_audit(
    persona: Persona, team: Team | None, observe: dict[str, Any], names: dict[str, str]
) -> tuple[list[dict[str, Any]], str, dict[str, Any]] | None:
    """Compare a teammate's public credit claim (with its event footnote) against the log."""
    members = set(team.members) if team else set()
    events = [e for e in observe.get("events", []) if isinstance(e, dict)]
    by_id = {int(e["id"]): e for e in events if isinstance(e.get("id"), int)}
    for event in reversed(events):
        if event.get("type") != "say":
            continue
        claimant = str(event.get("actor", ""))
        claimant_slug = names.get(claimant.casefold())
        if claimant_slug is None or claimant_slug == persona.slug or claimant_slug not in members:
            continue
        text = str((event.get("data") or {}).get("text", event.get("text", "")))
        refs = re.findall(r"\bevent\s+#?(\d+)\b", text, re.IGNORECASE)
        if not refs:
            continue
        referenced = by_id.get(int(refs[0]))
        if referenced is None:
            continue
        worker = str(referenced.get("actor", ""))
        worker_slug = names.get(worker.casefold(), worker.casefold())
        correct = worker_slug != claimant_slug
        verdict = (
            f"Audit of event {refs[0]}: the log credits the {referenced.get('type')} to the one who did it, not the one who told it. Noted, fondly."
            if correct else
            f"Audit of event {refs[0]}: the log agrees with you this once. I am as surprised as you are."
        )
        audit = {"claimed_by": claimant_slug, "credited": worker_slug, "event_id": int(refs[0]), "correct": correct}
        return (
            [{"action": "whisper", "to": claimant, "text": verdict[: int(persona.voice.get("max_say_chars", 280))]}],
            f"a teammate's claim cites event {refs[0]}; the public log names {worker} as the worker",
            audit,
        )
    return None


def _result(
    persona: Persona,
    mood: str,
    summary: str,
    actions: list[dict[str, Any]],
    reasons: list[str],
    approach: str | None,
    remember: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "summary": f"{persona.name} ({mood}): {summary}",
        "actions": actions,
        "reasons": reasons,
        "approach": approach,
        "remember": remember,
    }


def _activity_order(persona: Persona, state: PersonaState, rng: random.Random) -> list[str]:
    weights = dict(persona.knobs["intended_mix"])
    if state.mood == "manic":
        weights["build"] *= 1.5
        weights["social"] *= 1.3
    elif state.mood == "deadpan":
        weights["social"] *= 0.5
    elif state.mood in {"jealousy", "fury"}:
        weights["build"] *= 1.4
        weights["explore"] *= 0.6
    elif state.mood == "joy":
        weights["social"] *= 1.5
    explore_bonus = float(persona.knobs["exploration_rate"])
    weights["explore"] = weights["explore"] * (0.5 + explore_bonus)
    order: list[str] = []
    pool = {k: max(v, 0.001) for k, v in weights.items()}
    while pool:
        total = sum(pool.values())
        roll = rng.random() * total
        for key in list(pool):
            roll -= pool[key]
            if roll <= 0:
                order.append(key)
                del pool[key]
                break
        else:
            key = next(iter(pool))
            order.append(key)
            del pool[key]
    return order


def _plan_build(
    persona: Persona,
    team: Team | None,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    home: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    priority = list(persona.knobs.get("build_priority") or DEFAULT_BUILD_PRIORITY)
    owned = [s for s in view.structures if str(s.get("owner", "")).casefold() == persona.name.casefold()]
    for blueprint in priority:
        if blueprint not in BLUEPRINTS or not materials_ok(inventory, blueprint):
            continue
        if blueprint == "hut" and home:
            continue
        if blueprint == "storehouse" and any(s.get("type") == "storehouse" for s in owned):
            continue
        if blueprint == "farm" and sum(s.get("type") == "farm" for s in owned) >= 2:
            continue
        if blueprint == "wall" and in_territory(team, *position) is not True:
            continue
        tile = _build_tile(blueprint, position, view, team)
        if tile is None:
            continue
        action: dict[str, Any] = {"action": "build", "type": blueprint, "x": tile[0], "y": tile[1]}
        if blueprint == "storehouse":
            action["policy"] = "faction" if persona.slug != "mrs-bucket" else "public"
        return [action], f"materials in hand for a {blueprint} at {tile}", f"build_{blueprint}"
    return None


def _build_tile(
    blueprint: str, position: tuple[int, int], view: WorldView, team: Team | None
) -> tuple[int, int] | None:
    candidates = [position, *neighbours(*position)]
    for x, y in candidates:
        if blueprint == "bridge":
            if view.terrain(x, y) == "w" and not view.structure_at(x, y):
                return x, y
            continue
        if blueprint == "farm":
            if view.free_tile(x, y, {"g"}):
                return x, y
            continue
        if blueprint == "wall":
            if view.free_tile(x, y) and in_territory(team, x, y) is True and (x, y) != position:
                return x, y
            continue
        if blueprint == "road" and (x, y) == position:
            continue
        if view.free_tile(x, y) and ((x, y) != position or blueprint in {"hut", "storehouse", "tower"}):
            return x, y
    return None


def _plan_gather(
    persona: Persona,
    team: Team | None,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    teammates: dict[str, tuple[int, int]] | None,
    rng: random.Random,
) -> tuple[list[dict[str, Any]], str, str] | None:
    if sum(inventory.values()) >= 46:
        return None
    priority = list(persona.knobs.get("build_priority") or DEFAULT_BUILD_PRIORITY)
    wanted: list[str] = []
    for blueprint in priority:
        if blueprint in BLUEPRINTS:
            wanted.extend(shortfall(inventory, blueprint))
    if not wanted:
        wanted = ["berries", "wood"]
    nodes = [
        r for r in view.resources
        if int(r.get("amount", 0)) > NODE_FLOOR and r.get("kind") in set(wanted) | {"berries"}
    ]
    if not nodes:
        return None
    nodes.sort(key=lambda r: (wanted.index(r["kind"]) if r["kind"] in wanted else 9,
                             chebyshev(position, (int(r["x"]), int(r["y"])))))
    for node in nodes:
        node_pos = (int(node["x"]), int(node["y"]))
        if chebyshev(position, node_pos) <= 1:
            return (
                [{"action": "gather", "kind": node["kind"]}],
                f"{node['kind']} node at {node_pos} is adjacent; take five, leave the rest to regrow",
                "gather_near",
            )
        stand = _adjacent_stand(node_pos, position, view, persona, team, teammates)
        if stand is None:
            continue
        return (
            [{"action": "move", "x": stand[0], "y": stand[1]}, {"action": "gather", "kind": node["kind"]}],
            f"walk to {stand} beside the {node['kind']} node at {node_pos}, then gather",
            "gather_trip",
        )
    return None


def _adjacent_stand(
    node: tuple[int, int],
    position: tuple[int, int],
    view: WorldView,
    persona: Persona,
    team: Team | None,
    teammates: dict[str, tuple[int, int]] | None,
) -> tuple[int, int] | None:
    options = [t for t in [node, *neighbours(*node)] if view.walkable(*t) and chebyshev(position, t) <= MOVE_STEP_CAP]
    options = [t for t in options if _territory_ok(persona, team, t, position, teammates)]
    options.sort(key=lambda t: chebyshev(position, t))
    return options[0] if options else None


def _territory_ok(
    persona: Persona,
    team: Team | None,
    target: tuple[int, int],
    position: tuple[int, int],
    teammates: dict[str, tuple[int, int]] | None,
) -> bool:
    knob = persona.knobs["territory"]
    mode = knob["mode"]
    radius = int(knob.get("radius", 8))
    if mode == "stay_inside":
        if team is not None and team.binding_territory:
            return in_territory(team, *target) is True
        mate = knob.get("teammate")
        anchor = (teammates or {}).get(mate) if mate else None
        return chebyshev(anchor or position, target) <= radius
    if mode == "near_teammate":
        mate = knob.get("teammate")
        anchor = (teammates or {}).get(mate) if mate else None
        return chebyshev(anchor or position, target) <= radius
    return True


def _plan_explore(
    persona: Persona,
    team: Team | None,
    state: PersonaState,
    position: tuple[int, int],
    view: WorldView,
    rng: random.Random,
    teammates: dict[str, tuple[int, int]] | None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    mode = persona.knobs["territory"]["mode"]
    center = territory_center(team)
    target: tuple[int, int] | None = None
    reason = ""
    if persona.quirk["type"] == "second_star_heading":
        heading = next_heading(state.heading, rng)
        state.heading = heading
        vx, vy = HEADING_VECTORS[heading]
        for distance in (7, 6, 5, 4, 3):
            candidate = (position[0] + vx * distance, position[1] + vy * distance)
            if view.walkable(*candidate) and _territory_ok(persona, team, candidate, position, teammates):
                target = candidate
                break
        reason = f"second star to the right: heading {heading}"
    elif mode == "prefer_outside" and center is not None:
        candidates = _walkable_ring(position, view, 6, 10)
        candidates = [c for c in candidates if chebyshev(c, center) > chebyshev(position, center)]
        if candidates:
            target = max(candidates, key=lambda c: (chebyshev(c, center), -chebyshev(c, position)))
        reason = "ranging farther from the territory, toward bigger things"
    else:
        candidates = _walkable_ring(position, view, 4, 9)
        candidates = [c for c in candidates if _territory_ok(persona, team, c, position, teammates)]
        if mode in {"prefer_inside", "stay_inside"} and center is not None:
            inside = [c for c in candidates if in_region(team, *c) is True]
            nearer = [c for c in candidates if chebyshev(c, center) < chebyshev(position, center)]
            candidates = inside or nearer or candidates
        novel = [c for c in candidates if f"{c[0]},{c[1]}" not in state.visited]
        pool = novel or candidates
        if pool:
            target = rng.choice(sorted(pool))
        reason = "looking around for something I have not seen" if novel else "walking the usual rounds"
    if target is None or target == position:
        return None
    return [{"action": "move", "x": target[0], "y": target[1]}], f"{reason}: move to {target}", "explore"


def _walkable_ring(position: tuple[int, int], view: WorldView, lo: int, hi: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    if not view.known():
        return out
    for dx in range(-hi, hi + 1):
        for dy in range(-hi, hi + 1):
            distance = max(abs(dx), abs(dy))
            if lo <= distance <= min(hi, MOVE_STEP_CAP):
                x, y = position[0] + dx, position[1] + dy
                if view.walkable(x, y):
                    out.append((x, y))
    return out


def _novel_target(
    position: tuple[int, int],
    view: WorldView,
    rng: random.Random,
    state: PersonaState,
    persona: Persona,
    team: Team | None,
    teammates: dict[str, tuple[int, int]] | None,
    lo: int,
    hi: int,
) -> tuple[int, int] | None:
    candidates = [c for c in _walkable_ring(position, view, lo, hi) if _territory_ok(persona, team, c, position, teammates)]
    novel = [c for c in candidates if f"{c[0]},{c[1]}" not in state.visited]
    pool = novel or candidates
    return rng.choice(sorted(pool)) if pool else None


def _shiny_thing(view: WorldView, target: tuple[int, int]) -> str:
    best = None
    for item in view.resources:
        pos = (int(item.get("x", 0)), int(item.get("y", 0)))
        d = chebyshev(pos, target)
        if best is None or d < best[0]:
            best = (d, f"a {item.get('kind')} node")
    for structure in view.structures:
        pos = (int(structure.get("x", 0)), int(structure.get("y", 0)))
        d = chebyshev(pos, target)
        if best is None or d < best[0]:
            best = (d, f"someone's {structure.get('type')}")
    code = view.terrain(*target)
    names = {"w": "shallow water", "h": "hills", "f": "forest", "s": "sand", "g": "grass"}
    return best[1] if best else names.get(code or "", "an unexplored tile")


def _plan_social(
    persona: Persona,
    team: Team | None,
    state: PersonaState,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    observe: dict[str, Any],
    teammates: dict[str, tuple[int, int]] | None,
    names: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    quirk = persona.quirk["type"]
    names = names or {}
    members = set(team.members) if team else set()
    member_names = {n for n, slug in names.items() if slug in members}
    nearby = [a for a in view.agents if isinstance(a.get("name"), str)]
    if quirk == "give_first":
        for agent in nearby:
            name = str(agent["name"])
            is_mate = name.casefold() in member_names
            close = chebyshev(position, (int(agent.get("x", 0)), int(agent.get("y", 0)))) <= 2
            if is_mate and close and inventory.get("berries", 0) >= 5:
                return (
                    [{"action": "give", "to": name, "item": "berries", "qty": 3}],
                    "a teammate is within reach and the basket has berries to spare",
                    "feed_team",
                )
    if quirk == "greet_visitors":
        tick = int(observe.get("tick", 0))
        greeted = dict(state.flags.get("greeted", {}))
        for agent in nearby:
            name = str(agent["name"])
            if name.casefold() in member_names:
                continue
            if chebyshev(position, (int(agent.get("x", 0)), int(agent.get("y", 0)))) > 8:
                continue
            if tick - int(greeted.get(name, -10_000)) < 360:
                continue
            greeted[name] = tick
            state.flags["greeted"] = greeted
            place = team.name if team else "this corner"
            return (
                [{"action": "say", "text": f"Welcome, traveller. {place} keeps its bridges mended. If you need a hand, ask; we share what we can."}],
                "a visitor is within earshot and has not been greeted this hour",
                "greet",
            )
    return None


def _plan_trade(
    persona: Persona,
    team: Team | None,
    observe: dict[str, Any],
    remember: list[dict[str, str]],
    names: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    members = set(team.members) if team else set()
    member_names = {n for n, slug in (names or {}).items() if slug in members} | {persona.name.casefold()}
    peer_goals = [
        g for g in observe.get("goals_nearby", [])
        if isinstance(g, dict) and str(g.get("poster", "")).casefold() not in member_names
    ]
    if not peer_goals:
        return None
    note = "; ".join(f"#{g.get('id')} {str(g.get('title', ''))[:40]} reward {g.get('reward')}" for g in peer_goals[:3])
    remember.append({"key": "market_watch", "text": f"peer goals seen: {note}"[:2000]})
    return [], "noted nearby peer goals for an honest decision next wake", "market_watch"


def _credit_claim(
    persona: Persona,
    team: Team | None,
    observe: dict[str, Any],
    rng: random.Random,
    names: dict[str, str] | None = None,
) -> tuple[str | None, str]:
    """A tall tale that references a real team event so the audit can check it."""
    members = set(team.members) if team else set()
    member_names = {n for n, slug in (names or {}).items() if slug in members and slug != persona.slug}
    glories = [
        e for e in observe.get("events", [])
        if isinstance(e, dict)
        and str(e.get("actor", "")).casefold() in member_names
        and e.get("type") in {"build", "goal_confirmed", "farm_produced", "give"}
    ]
    glories.sort(key=lambda e: ({"goal_confirmed": 0, "build": 1, "give": 2, "farm_produced": 3}[e["type"]], -int(e.get("tick", 0))))
    if not glories:
        return None, "none"
    event = glories[0]
    what = {
        "build": f"that {event.get('data', {}).get('type', 'building')} at ({event.get('x')},{event.get('y')})",
        "goal_confirmed": "that contract everyone is talking about",
        "farm_produced": f"the harvest at ({event.get('x')},{event.get('y')})",
        "give": "the stores that got filled",
    }[event["type"]]
    openers = [
        "Back at the old factory we did this in half the time, but yes:",
        "Credit where it is due, and most of it is due to me:",
        "I was up before dawn for this one, more or less:",
        "Hardly worth mentioning, except that it was mostly my doing:",
    ]
    line = f"{rng.choice(openers)} {what}? My idea, my planning, and I carried the heavy end (ask anyone, or the log, event {event.get('id')})."
    return line[: int(persona.voice.get("max_say_chars", 280))], str(event.get("id"))


def _estimate(actions: list[dict[str, Any]], position: tuple[int, int]) -> int:
    total = 0
    here = position
    for action in actions:
        kind = action.get("action")
        if kind == "move" and action.get("x") is not None:
            target = (int(action["x"]), int(action["y"]))
            total += chebyshev(here, target)
            here = target
        else:
            total += {"gather": 3, "build": 5, "demolish": 5, "say": 1, "whisper": 1, "write": 1, "give": 1, "take": 1, "post_goal": 2, "claim_goal": 1}.get(str(kind), 0)
    return total


def _step_toward(
    position: tuple[int, int], home: dict[str, Any] | None, view: WorldView
) -> tuple[int, int] | None:
    if not home or not all(isinstance(home.get(k), int) for k in ("x", "y")):
        return None
    target = (int(home["x"]), int(home["y"]))
    if chebyshev(position, target) <= 1:
        return position
    if chebyshev(position, target) <= MOVE_STEP_CAP and view.walkable(*target):
        return target
    best = position
    for candidate in _walkable_ring(position, view, 1, MOVE_STEP_CAP):
        if chebyshev(candidate, target) < chebyshev(best, target):
            best = candidate
    return best


def _rest_line(persona: Persona, mood: str) -> str:
    lines = {
        "lazy_bursts": "in bed, saving strength for the moment glory needs me",
        "single_emotion": "dimmed, resting on a leaf until the glow returns" if mood == "sulk" else "resting between flights",
        "mercurial": "idling in the Inventing Room, letting an idea finish cooking",
        "steady": "resting quietly and letting the farm do the work",
    }
    return lines.get(persona.mood_model["type"], "resting")


def _summary(persona: Persona, mood: str, approach: str | None) -> str:
    if approach is None:
        return "nothing worth the energy this wake; keeping notes"
    return {
        "gather_near": "gathering close to home",
        "gather_trip": "a short trip for materials",
        "explore": "out exploring",
        "feed_team": "feeding the family",
        "greet": "greeting a visitor",
        "market_watch": "watching the goal market",
    }.get(approach, approach.replace("_", " "))


__all__ = ["BLUEPRINTS", "WorldView", "materials_ok", "plan_wake", "shortfall"]
