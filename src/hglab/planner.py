"""Deterministic, persona-driven wake planner.

This planner needs no model. It turns a persona's knobs, mood and quirk into one to
four concrete actions with a reason each, so personality lives in code: schedules,
energy habits, risk, territory, social rhythm and mood all change what gets proposed.
The LLM path (when a key is present) is validated by the same knobs; when its plan is
rejected, this planner is the fallback. It never speaks except where a quirk demands a
line (a greeting, a credit claim), and it never claims goals blindly.
"""

from __future__ import annotations

import hashlib
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
BLOCKING = {"wall", "hut", "storehouse", "tower", "monument"}  # a route never passes through these; it stops beside them
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
REPAIR_MATERIAL = {
    "sign": "wood", "road": "stone", "wall": "stone", "bridge": "wood", "hut": "wood", "farm": "wood",
    "storehouse": "wood", "tower": "stone", "monument": "stone",
}  # one unit mends 20 hp (API 0.26.2); caches cannot be repaired
BLUEPRINT_HP = {"sign": 10, "road": 20, "wall": 60, "bridge": 40, "hut": 40, "farm": 30, "storehouse": 80, "tower": 100, "monument": 200}
HARVEST_FLOOR = 12  # take from an own farm once it holds this many berries (a full farm grows nothing)
WORK_SUMMARIES = {
    "build_monument": "raising the monument from the storehouse", "build": "building", "deposit": "stocking the storehouse",
    "gather_trip": "gathering for the next build", "migrate": "walking to the team site", "explore": "looking for nodes",
    "repair": "mending what is damaged", "harvest": "collecting the farm", "salvage": "taking salvage from a ruin",
    "stake": "staking open lots for the land office",
    "house": "raising the house around the hut",
    "hearth": "raising the hearth on the house's site",
    "site_trade": "trading with the land office for the house's ground",
    "hearth_trip": "carrying the hearth to the house's site",
    "homing": "carrying materials home for the house",
    "engage": "a word, a gift or a deal with a neighbour",
    "deliver": "delivering on a claimed goal",
    "lighten": "eating into the berry hoard to make room",
    "deposit_trip": "carrying a full pack to the storehouse",
    "border": "raising the border signs",
    "patrol": "walking the outermost edge of the world, behind the glass",
    "news": "announcing a change in the game",
    "reclaim": "reclaiming what the departed left standing",
    "forage": "walking toward a node the map knows",
    "reclaim_trip": "walking to what the departed left standing",
    "border_trip": "walking to the next border sign",
}
REPAIR_WORTH = 10  # mend only when at least half a repair's 20 hp is missing; a scratch is not worth a unit of material
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
    owned_counts: dict[str, int] = field(default_factory=dict)  # own structures anywhere, by type (public snapshot)
    weather: str = "clear"  # clear, rain, storm, drought: a storm day makes every move tile cost 1 more
    world_structures: list[dict[str, Any]] = field(default_factory=list)  # every structure in the world (public snapshot)
    season: str = ""  # spring, summer, autumn, winter: wild berries do not regrow in winter
    liveness: dict[str, int] = field(default_factory=dict)  # resident name -> last_seen_tick (public snapshot)
    arrivals: dict[str, int] = field(default_factory=dict)  # resident name -> created_tick (public snapshot)
    residents: list[dict[str, Any]] = field(default_factory=list)  # public agents: name, x, y, last_seen_tick
    tick: int = 0
    world_resources: list[dict[str, Any]] = field(default_factory=list)  # every node in the world (public snapshot)
    closed: set[tuple[int, int]] = field(default_factory=set)  # tiles in view that blocks close to this agent (observe.blocks[].closed)

    @classmethod
    def from_observe(
        cls,
        observe: dict[str, Any],
        terrain_rows: list[str] | None = None,
        owned_counts: dict[str, int] | None = None,
        world_structures: list[dict[str, Any]] | None = None,
        public_agents: list[dict[str, Any]] | None = None,
        public_resources: list[dict[str, Any]] | None = None,
    ) -> WorldView:
        view = observe.get("view") if isinstance(observe.get("view"), dict) else {}
        liveness = {
            str(a["name"]): int(a.get("last_seen_tick") or 0)
            for a in (public_agents or []) if isinstance(a, dict) and a.get("name") and a.get("last_seen_tick") is not None
        }
        arrivals = {
            str(a["name"]): int(a.get("created_tick") or 0)
            for a in (public_agents or []) if isinstance(a, dict) and a.get("name") and a.get("created_tick") is not None
        }
        rows = view.get("rows") or []
        return cls(
            x0=int(view.get("x0", 0)),
            y0=int(view.get("y0", 0)),
            rows=[str(r) for r in rows],
            structures=[s for s in observe.get("structures", []) if isinstance(s, dict)],
            resources=[r for r in observe.get("resources", []) if isinstance(r, dict)],
            agents=[a for a in observe.get("agents", []) if isinstance(a, dict)],
            full_map=terrain_rows,
            owned_counts=dict(owned_counts or {}),
            weather=str(observe.get("weather") or "clear"),
            season=str(observe.get("season") or ""),
            world_structures=[s for s in (world_structures or []) if isinstance(s, dict)],
            liveness=liveness,
            arrivals=arrivals,
            residents=[a for a in (public_agents or []) if isinstance(a, dict) and a.get("name")],
            tick=int(observe.get("tick", 0) or 0),
            world_resources=[r for r in (public_resources or []) if isinstance(r, dict)],
            closed={
                (int(b["x"]), int(b["y"]))
                for b in (observe.get("blocks") or []) if isinstance(b, dict) and b.get("closed") and b.get("x") is not None and b.get("y") is not None
            },
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
        """The structure on a tile: the view first, then the public snapshot (bridges and walls beyond the view matter to a route)."""
        for structure in self.structures:
            if structure.get("x") == x and structure.get("y") == y:
                return structure
        for structure in self.world_structures:
            if structure.get("x") == x and structure.get("y") == y:
                return structure
        return None

    def walkable(self, x: int, y: int) -> bool:
        if not (0 <= x < 128 and 0 <= y < 128) or (x, y) in self.closed:
            return False  # blocks below level 6 close a tile even to their owner, unless it holds a door one may use
        code = self.terrain(x, y)
        structure = self.structure_at(x, y)
        if structure and structure.get("type") == "bridge":
            return True
        if structure and structure.get("type") in BLOCKING:
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


def reachable_storage(persona: Persona, position: tuple[int, int], view: WorldView, faction: str | None = None) -> dict[str, int]:
    """Items in storehouses within one tile that this agent may take from (own, public, same faction).

    The guide (API 0.18.0): build is paid from the pack first and the rest from such storehouses.
    """
    total: dict[str, int] = {}
    for structure in view.structures:
        if structure.get("type") != "storehouse":
            continue
        if chebyshev(position, (int(structure.get("x", -99)), int(structure.get("y", -99)))) > 1:
            continue
        owner = str(structure.get("owner", "")).casefold()
        policy = str(structure.get("policy") or "private")
        allowed = owner == persona.name.casefold() or policy == "public" or (
            policy == "faction" and faction and str(structure.get("faction") or "") == faction
        )
        if not allowed:
            continue
        storage = structure.get("storage") if isinstance(structure.get("storage"), dict) else {}
        for item, qty in storage.items():
            total[str(item)] = total.get(str(item), 0) + int(qty or 0)
    return total


def with_storage(inventory: dict[str, int], storage: dict[str, int]) -> dict[str, int]:
    merged = dict(inventory)
    for item, qty in storage.items():
        merged[item] = merged.get(item, 0) + qty
    return merged


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
    work: bool = False,
    owned_counts: dict[str, int] | None = None,
    registrar_name: str | None = None,
    public_structures: list[dict[str, Any]] | None = None,
    collective_names: set[str] | None = None,
    public_agents: list[dict[str, Any]] | None = None,
    public_resources: list[dict[str, Any]] | None = None,
    environment: dict[str, Any] | None = None,
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
    view = WorldView.from_observe(observe, terrain_rows, owned_counts, public_structures, public_agents, public_resources)
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
    if work:
        return _plan_work(
            persona, team, state, observe, rng, view, position, energy, inventory, home, reserve, cap, teammates, allowed, mood, reasons, remember,
            registrar_name=registrar_name, collective_names=collective_names, names=names, environment=environment,
        )
    budget = cap if mood != "sulk" else 1
    spendable = energy + 15 * sum(min(int(a.get("qty") or 0), inventory.get("berries", 0)) for a in actions if a.get("action") == "eat") - reserve
    here = position
    patrolling = bool(persona.knobs.get("patrol"))
    activities = ["lighten", "engage", *_activity_order(persona, state, rng)]
    if patrolling:
        activities = ["lighten", "engage", "patrol", *[a for a in activities[2:] if a != "explore"]]
    activities = ["news", *activities]
    for activity in activities:
        if len(actions) >= budget:
            break
        if activity == "news":
            step = _plan_news(persona, state, observe, environment)
        elif activity == "lighten":
            step = _plan_lighten(inventory, energy)
        elif activity == "patrol":
            step = _plan_patrol(persona, state, here, view, room=budget - len(actions), energy_room=spendable)
        elif activity == "engage":
            step = _plan_engage(persona, team, state, inventory, here, view, observe, teammates, names, rng, collective_names, allowed)
        elif activity == "build":
            # builds are validated against the observed position, so only before any move
            step = (
                _plan_repair(persona, team, inventory, here, view, teammates)
                or _plan_harvest(persona, team, inventory, here, view, teammates)
                or _plan_stake(persona, inventory, here, view)
                or (_plan_site_trade(persona, state, inventory, here, view, observe, registrar_name) if here == position else None)
                or (_plan_hearth(persona, inventory, here, view, home, state) if here == position else None)
                or _plan_house(persona, inventory, here, view, home, observe, state=state)
                or (_plan_build(persona, team, inventory, here, view, home) if here == position else None)
                or (_plan_border_sign(persona, team, inventory, here, view, teammates, names) if here == position else None)
                or (_plan_reclaim(persona, team, state, inventory, here, view, observe, teammates, collective_names, room=budget - len(actions)) if here == position else None)
            )
        elif activity == "gather":
            step = (
                _plan_gather(persona, team, inventory, here, view, teammates, rng)
                or _plan_deposit(persona, inventory, here, view, None, mates=set(collective_names or ()) | set(names or ()))
                or _plan_deposit_trip(persona, team, inventory, here, view, teammates, {n.casefold() for n in set(collective_names or ()) | set(names or ())} | {persona.name.casefold()})
                or _plan_forage(persona, team, inventory, here, view, teammates)
            )
        elif activity == "explore":
            step = _plan_explore(persona, team, state, here, view, rng, teammates)
        elif activity == "social":
            step = _plan_social(persona, team, state, inventory, here, view, observe, teammates, names)
        else:
            step = _plan_trade(persona, team, observe, remember, names)
        if not step:
            continue
        new_actions, reason, tag = step
        if patrolling and activity != "patrol" and any(a.get("action") == "move" for a in new_actions):
            continue  # the patrol is the only road: nothing walks the persona off the edge
        if allowed is not None and any(a.get("action") not in allowed for a in new_actions):
            continue
        if len(actions) + len(new_actions) > budget:
            continue  # a step is all or nothing: a trip without its gather is wasted energy
        walker, too_far = here, False
        for a in new_actions:
            if a.get("action") == "move" and a.get("x") is not None:
                too_far = too_far or chebyshev(walker, (int(a["x"]), int(a["y"]))) > MOVE_STEP_CAP
                walker = (int(a["x"]), int(a["y"]))
        if too_far:
            continue  # each hop is one move of the world's: twelve from where the previous one ended
        cost = _estimate(new_actions, here, storm=view.weather == "storm")
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
    meal = _meal_after_move(actions, inventory, energy, budget)
    if meal is not None:
        actions.append(meal)
        reasons.append(f"pack {sum(inventory.values())}/50 with {inventory.get('berries', 0)} berries: one berry after the walk, when the meal is not refused")
    summary = _summary(persona, mood, approach)
    result = _result(persona, mood, summary, actions, reasons, approach, remember)
    if audit is not None:
        result["audit"] = audit
    return result


def _plan_work(
    persona: Persona,
    team: Team | None,
    state: PersonaState,
    observe: dict[str, Any],
    rng: random.Random,
    view: WorldView,
    position: tuple[int, int],
    energy: int,
    inventory: dict[str, int],
    home: dict[str, Any] | None,
    reserve: int,
    cap: int,
    teammates: dict[str, tuple[int, int]] | None,
    allowed: set[str] | None,
    mood: str,
    reasons: list[str],
    remember: list[dict[str, str]],
    registrar_name: str | None = None,
    collective_names: set[str] | None = None,
    names: dict[str, str] | None = None,
    environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A work shift wake: build first, then gather the shortfall, deposit surplus, migrate.

    No speech, no goals, no model. Builds as often as materials allow, stays above the
    reserve, never strips a node, and walks toward the team site when far from it.
    """
    actions: list[dict[str, Any]] = []
    spendable = energy - reserve
    here = position

    def fits(step: tuple[list[dict[str, Any]], str, str] | None) -> bool:
        nonlocal spendable, here
        if not step:
            return False
        new_actions, reason, _tag = step
        if allowed is not None and any(a.get("action") not in allowed for a in new_actions):
            return False
        if len(actions) + len(new_actions) > cap:
            return False
        walker = here
        for a in new_actions:
            if a.get("action") == "move" and a.get("x") is not None:
                if chebyshev(walker, (int(a["x"]), int(a["y"]))) > MOVE_STEP_CAP:
                    return False  # each hop is one move of the world's: twelve from where the previous one ended
                walker = (int(a["x"]), int(a["y"]))
        cost = _estimate(new_actions, here, storm=view.weather == "storm")
        if cost > spendable:
            return False
        spendable -= cost
        for a in new_actions:
            if a.get("action") == "move" and a.get("x") is not None:
                here = (int(a["x"]), int(a["y"]))
            elif a.get("action") == "build" and a.get("type") in BLUEPRINTS:
                for item, qty in BLUEPRINTS[str(a["type"])].items():
                    inventory[item] = max(0, inventory.get(item, 0) - qty)
            elif a.get("action") == "give" and a.get("item"):
                inventory[str(a["item"])] = max(0, inventory.get(str(a["item"]), 0) - int(a.get("qty", 0) or 0))
            elif a.get("action") == "take" and a.get("item"):
                inventory[str(a["item"])] = inventory.get(str(a["item"]), 0) + int(a.get("qty", 0) or 0)
            elif a.get("action") == "eat":
                inventory["berries"] = max(0, inventory.get("berries", 0) - int(a.get("qty", 0) or 0))
        actions.extend(new_actions)
        reasons.append(reason)
        return True

    approach = None

    def moved() -> bool:
        return any(a.get("action") == "move" for a in actions)

    # 0. a claimed goal with a delivery is a promise: deliver it before anything else
    if fits(_plan_deliver(persona, inventory, here, view, observe)):
        approach = "deliver"
    # 0.1 upkeep within reach comes before any walking: mend, collect the farm, take salvage
    if fits(_plan_repair(persona, team, inventory, here, view, teammates)):
        approach = approach or "repair"
    if fits(_plan_harvest(persona, team, inventory, here, view, teammates)):
        approach = approach or "harvest"
    if fits(_plan_salvage(inventory, here, view)):
        approach = approach or "salvage"
    # 0.2 the town crier's news: a changed game is said in the open before anything else
    if fits(_plan_news(persona, state, observe, environment)):
        approach = approach or "news"
    # 0.3 a pack heavy with berries makes room for materials
    if fits(_plan_lighten(inventory, energy)):
        approach = approach or "lighten"
    # 0.5 one engagement with a neighbour when there is one: a word, a gift, a deal, a contest (one action, before the build spends the cap)
    engaged = fits(_plan_engage(persona, team, state, inventory, here, view, observe, teammates, names, rng, collective_names, allowed))
    # 0.6 the trade for the house's ground: the brief to the land office, its answer, the payment
    if not moved() and fits(_plan_site_trade(persona, state, inventory, here, view, observe, registrar_name)):
        approach = approach or "site_trade"
    # 0.7 the patrol: the outermost edge of the world is this persona's whole road
    if persona.knobs.get("patrol"):
        beside = _plan_reclaim(persona, team, state, inventory, here, view, observe, teammates, collective_names, room=cap - len(actions))
        if beside is not None and beside[2] == "reclaim" and fits(beside):
            approach = approach or "reclaim"  # a long-departed resident's structure on the edge: take it down on the way
        if cap - len(actions) >= 2 and sum(inventory.values()) < 45 and fits(_plan_gather_adjacent(persona, inventory, here, view)):
            approach = approach or "gather_near"
        if fits(_plan_patrol(persona, state, here, view, room=cap - len(actions), energy_room=spendable)):
            approach = "patrol" if approach in (None, "gather_near") else approach
        if engaged and not approach:
            approach = "engage"
        meal = _meal_after_move(actions, inventory, energy, cap)
        if meal is not None:
            actions.append(meal)
            reasons.append(f"pack {sum(inventory.values())}/50 with {inventory.get('berries', 0)} berries: one berry after the walk")
        return _result(persona, mood, f"work shift: {WORK_SUMMARIES.get(approach or '', 'keeping to the edge')}", actions, reasons, approach, remember)
    # 1. a settler far from the team site walks there before building, once upkeep is done; an expedition to reclaim holds the walk home
    migrate = _plan_migrate(persona, team, position, view, teammates)
    expedition = _plan_reclaim(persona, team, state, inventory, here, view, observe, teammates, collective_names, room=cap - len(actions))
    far_from_home = migrate is not None and persona.knobs["territory"]["mode"] in {"prefer_inside", "stay_inside", "near_teammate"} and expedition is None
    if far_from_home and not actions and fits(migrate):
        approach = "migrate"
        if fits(_plan_gather_adjacent(persona, inventory, here, view)):
            pass
        return _result(persona, mood, "work shift: walking to the team site", actions, reasons, approach, remember)
    if far_from_home and actions:
        if not moved() and fits(migrate):
            approach = approach or "migrate"  # a word or a mend, then the walk home in the same wake
        if engaged and not approach:
            approach = "engage"
        return _result(persona, mood, f"work shift: {WORK_SUMMARIES.get(approach or '', 'upkeep')}", actions, reasons, approach, remember)
    # 1.5 the land office stakes open lots, one claim sign each, as fast as wood and energy allow
    staked_now: set[str] = set()
    per_wake = int((persona.knobs.get("stake_lots") or {}).get("per_wake", 0) or 0)
    while len(staked_now) < per_wake:
        step = _plan_stake(persona, inventory, here, view, exclude=staked_now)
        if not step or not fits(step):
            break
        staked_now.add(step[2].split(":", 1)[1])
        inventory["wood"] = inventory.get("wood", 0) - 1
        approach = approach or "stake"
    # 2. the monument recipe when the storehouse beside us holds the materials
    monument = _plan_monument(persona, inventory, position, view)
    if here == position and fits(monument):
        approach = approach or "build_monument"
    # 2.7 reclaim what residents gone for days left standing: the quarter it drops is worth the hits, and beats a road
    if not moved() and fits(_plan_reclaim(persona, team, state, inventory, here, view, observe, teammates, collective_names, room=cap - len(actions))):
        approach = approach or "reclaim"
    # 3. any build whose materials are in hand (hut, farm, storehouse, bridge, wall...)
    if here == position and fits(_plan_build(persona, team, inventory, position, view, home)):
        approach = approach or "build"
    # 3.4 the hearth on the house's chosen site, when the site is not yet home
    if not moved() and fits(_plan_hearth(persona, inventory, here, view, home, state)):
        approach = approach or "hearth"
    # 3.5 the house around the hut, one step per wake, when its material is in the pack
    if fits(_plan_house(persona, inventory, here, view, home, observe, state=state)):
        approach = approach or "house"
    # 3.6 the border signs of the team's ground, nearest missing first
    if not moved() and fits(_plan_border_sign(persona, team, inventory, here, view, teammates, names)):
        approach = approach or "border"
    # 4. deposit surplus into an adjacent storehouse of ours (so the monument can draw on it)
    ours = set(collective_names or ()) | set(names or ())
    if fits(_plan_deposit(persona, inventory, here, view, registrar_name, mates=ours)):
        approach = approach or "deposit"
    # 4.2 a full pack walks to the nearest storehouse of ours to unload (a word or a meal may precede the walk)
    if not moved() and fits(_plan_deposit_trip(persona, team, inventory, position, view, teammates, {n.casefold() for n in ours} | {persona.name.casefold()})):
        approach = approach or "deposit_trip"
    # 4. gather the shortfall for the next blueprint
    while len(actions) < cap and fits(_plan_gather(persona, team, inventory, here, view, teammates, rng)):
        approach = approach or "gather_trip"
        for a in actions[-2:]:
            if a.get("action") == "gather":
                inventory[a.get("kind", "wood")] = inventory.get(a.get("kind", "wood"), 0) + 5
    # 4.7 nothing wanted in view: walk toward the nearest node the public snapshot knows
    if not moved() and fits(_plan_forage(persona, team, inventory, position, view, teammates)):
        approach = approach or "forage"
    # 5. far from the team site and nothing to gather here: migrate toward it
    if not moved() and fits(_plan_migrate(persona, team, position, view, teammates)):
        approach = approach or "migrate"
    # 5.5 the house's next step is in the pack but the hut is out of reach: carry it home before wandering
    if not moved() and fits(_plan_homing(persona, inventory, position, view, home, observe, state=state)):
        approach = approach or "homing"
    if not moved() and fits(_plan_explore(persona, team, state, position, view, rng, teammates)):
        approach = approach or "explore"
    if engaged and not approach:
        approach = "engage"  # the neighbour was the whole of this wake
    if not moved():
        gifts = [a for a in actions if a.get("action") == "give" and a.get("to")]
        if gifts:
            actions[:] = [a for a in actions if not (a.get("action") == "give" and a.get("to"))] + gifts  # a refused gift (their pack full) must not end the batch before the work
    meal = _meal_after_move(actions, inventory, energy, cap)
    if meal is not None:
        actions.append(meal)
        reasons.append(f"pack {sum(inventory.values())}/50 with {inventory.get('berries', 0)} berries: one berry after the walk, when the meal is not refused")
    summary = WORK_SUMMARIES.get(approach or "", "nothing worth the energy this shift wake")
    return _result(persona, mood, f"work shift: {summary}", actions, reasons, approach, remember)


def _plan_gather_adjacent(persona: Persona, inventory: dict[str, int], position: tuple[int, int], view: WorldView) -> tuple[list[dict[str, Any]], str, str] | None:
    """Gather from a node under or beside us without walking (used while travelling)."""
    if sum(inventory.values()) >= 45:
        return None
    for node in view.resources:
        node_pos = (int(node["x"]), int(node["y"]))
        if chebyshev(position, node_pos) <= 1 and int(node.get("amount", 0)) > NODE_FLOOR:
            return [{"action": "gather", "kind": node["kind"]}], f"{node['kind']} beside the road at {node_pos}: take five on the way", "gather_near"
    return None


def _plan_monument(persona: Persona, inventory: dict[str, int], position: tuple[int, int], view: WorldView) -> tuple[list[dict[str, Any]], str, str] | None:
    """Cairn's recipe: stone and ore split between pack and an adjacent own storehouse."""
    if "monument" not in (persona.knobs.get("build_priority") or []):
        return None
    storage = reachable_storage(persona, position, view)
    stone = inventory.get("stone", 0) + storage.get("stone", 0)
    ore = inventory.get("ore", 0) + storage.get("ore", 0)
    if stone < 50 or ore < 10 or not storage:
        return None
    for tile in neighbours(*position):
        if view.free_tile(*tile):
            return (
                [{"action": "build", "type": "monument", "x": tile[0], "y": tile[1], "text": f"Raised by {persona.name}. A character in the collective's story."}],
                f"pack plus the storehouse beside me hold {stone} stone and {ore} ore: the monument recipe (build pays the rest from storehouses within one tile)",
                "build_monument",
            )
    return None


def _plan_stake(
    persona: Persona,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    exclude: set[str] | None = None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """The land office's claim: one sign on the anchor of the nearest free lot (knob ``stake_lots``).

    A lot is free when no structure stands in it anywhere in the world (the public snapshot), and
    the office leaves a ring of lots around every other agent's hut. The tag carries the lot id.
    """
    from hglab.lots import (
        free_lots,
        homestead_ring,
        lot_anchor,
        lot_price,
        lot_value,
        stake_text,
        total_lots,
    )

    knob = persona.knobs.get("stake_lots")
    if not knob or inventory.get("wood", 0) < 1:
        return None
    structures = view.world_structures or view.structures
    candidates = free_lots(structures) - (set(exclude or ()))
    if knob.get("respect_homesteads", True):
        candidates -= homestead_ring(structures, persona.name)
    reach = reachable_tiles(view, position)
    for lid in sorted(candidates, key=lambda lid: chebyshev(position, lot_anchor(lid)))[:60]:
        anchor = lot_anchor(lid)
        if chebyshev(position, anchor) > MOVE_STEP_CAP + 1:
            break
        if not view.free_tile(*anchor) or any(s.get("x") == anchor[0] and s.get("y") == anchor[1] for s in structures):
            continue
        value = lot_value(lid, view.terrain, view.world_resources, structures, view.residents, int(view.tick or 0), exclude_owner=persona.name)
        price = lot_price(len(candidates | set(exclude or ())) / total_lots(), int(knob.get("base_price", 5)), int(knob.get("price_cap", 50)), value["score"])
        build = {"action": "build", "type": "sign", "x": anchor[0], "y": anchor[1], "text": stake_text(lid, persona.name, price, value["tags"])}
        if chebyshev(position, anchor) <= 1:
            return [build], f"stake lot {lid}: a claim sign at {anchor}", f"stake:{lid}"
        stand = next((t for t in sorted([anchor, *neighbours(*anchor)], key=lambda t: chebyshev(position, t)) if t in reach), None)
        if stand is not None:
            return [{"action": "move", "x": stand[0], "y": stand[1]}, build], f"walk to {stand} and stake lot {lid} with a claim sign at {anchor}", f"stake:{lid}"
    return None


def _house_shortfall(persona: Persona, inventory: dict[str, int], view: WorldView, state: PersonaState | None = None) -> list[str]:
    """The item the next house step still needs, so gathering trips fetch it before anything else."""
    from hglab.blocks import house_plan

    knob = persona.knobs.get("house")
    home = next((s for s in view.structures if s.get("type") == "hut" and _own(persona, s)), None)
    site = _house_site(knob, home, state)
    if not knob or site is None:
        return []
    plan = house_plan(site[0], site[1], int(knob.get("size", 1)), str(knob.get("color", "natural")), style=str(knob.get("style", "house")))
    for step in plan:
        if inventory.get(step["item"], 0) < step["items"]:
            return [step["item"]]
    return []


HOUSE_VIEW = 6  # the hut's footprint is in the 13x13 view when the observed position is this close


SITE_WHISPER = re.compile(r"SITE for (?P<id>[\w-]+): lot (?P<lot>[A-Z][0-9]{2}-(?:NW|NE|SW|SE)), anchor \((?P<x>\d+),\s*(?P<y>\d+)\).*?price (?P<price>\d+) (?P<currency>\w+)", re.IGNORECASE | re.DOTALL)


def _house_site(knob: dict[str, Any] | None, home: dict[str, Any] | None, state: PersonaState | None = None) -> tuple[int, int] | None:
    """Where the house stands: the knob's ``site`` when set, the lot bought from the land office when the
    knob says ``site_from: land_office`` (nothing until the deed is agreed), else the hearth."""
    if not knob:
        return None
    site = knob.get("site")
    if isinstance(site, dict) and all(isinstance(site.get(k), int) for k in ("x", "y")):
        return int(site["x"]), int(site["y"])
    if knob.get("site_from") == "land_office":
        bought = state.flags.get("house_site") if state is not None and isinstance(state.flags.get("house_site"), dict) else None
        if bought and all(isinstance(bought.get(k), int) for k in ("x", "y")):
            return int(bought["x"]), int(bought["y"])
        return None
    if home and all(isinstance(home.get(k), int) for k in ("x", "y")):
        return int(home["x"]), int(home["y"])
    return None


def _plan_site_trade(
    persona: Persona,
    state: PersonaState,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    observe: dict[str, Any],
    registrar_name: str | None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """The trade for the house's ground with the land office, in three movements.

    First the brief, whispered to the registrar once a day until an answer comes. Then the answer: the
    office's ``SITE for <request>`` whisper in the inbox names the lot, its anchor and its price, and the
    anchor becomes the house's site in the persona state. Then the payment: the price in the office's
    currency carried to the nearest office storehouse and given in, which the office reads in public and
    answers with the deed. The inbox is private: it is read here and never copied into a record.
    """
    knob = persona.knobs.get("house") or {}
    if knob.get("site_from") != "land_office" or not registrar_name:
        return None
    tick = int(observe.get("tick", 0) or 0)
    request = str(knob.get("request", "site"))
    bought = state.flags.get("house_site") if isinstance(state.flags.get("house_site"), dict) else None
    if not bought:
        for whisper in observe.get("inbox") or []:
            if not isinstance(whisper, dict) or str(whisper.get("from", "")).casefold() != registrar_name.casefold():
                continue
            match = SITE_WHISPER.search(str(whisper.get("text") or ""))
            if match and match.group("id").casefold() == request.casefold():
                bought = {"x": int(match.group("x")), "y": int(match.group("y")), "lot": match.group("lot").upper(), "price": int(match.group("price")), "currency": match.group("currency").casefold(), "paid": 0, "tick": tick}
                state.flags["house_site"] = bought
                break
    if not bought:
        asked = int(state.flags.get("site_asked", -10**9) or -10**9)
        brief = str(knob.get("brief") or f"SURVEY REQUEST {request}: a 5x5 lot I can grow into the lots beside it. I pay the office's price in wood.")
        if tick - asked >= 8640:
            state.flags["site_asked"] = tick
            return [{"action": "whisper", "to": registrar_name, "text": f"SURVEY REQUEST {request}: {brief}"[:500] if not brief.upper().startswith("SURVEY REQUEST") else brief[:500]}], f"the house wants ground: the brief goes to {registrar_name}, the land office", "site_request"
        return None
    owed = int(bought.get("price", 0) or 0) - int(bought.get("paid", 0) or 0)
    if owed <= 0:
        return None
    currency = str(bought.get("currency", "wood"))
    carried = inventory.get(currency, 0)
    if carried < min(owed, 10):
        return None  # the gathering steps fetch the currency first
    structures = view.world_structures or view.structures
    vaults = sorted(
        ((int(s["x"]), int(s["y"])) for s in structures if s.get("type") == "storehouse" and str(s.get("owner", "")).casefold() == registrar_name.casefold()),
        key=lambda t: chebyshev(position, t),
    )
    vaults = [v for v in vaults if storehouse_room(view.structure_at(*v) or {}) >= min(owed, 5)]  # a full vault takes nothing
    if not vaults:
        return None
    vault = vaults[0]
    if chebyshev(position, vault) <= 1:
        qty = min(owed, carried, storehouse_room(view.structure_at(*vault) or {}))
        bought["paid"] = int(bought.get("paid", 0) or 0) + qty
        state.flags["house_site"] = bought
        return [{"action": "give", "x": vault[0], "y": vault[1], "item": currency, "qty": qty}], f"the deed for lot {bought.get('lot')}: {qty} {currency} into the land office's storehouse at {vault} ({owed - qty} still owed)", "deed_payment"
    target = _step_toward(position, {"x": vault[0], "y": vault[1]}, view)
    if target is None or target == position:
        return None
    return [{"action": "move", "x": target[0], "y": target[1]}], f"carrying {carried} {currency} toward the land office's storehouse at {vault} to pay for lot {bought.get('lot')}", "deed_trip"


def _plan_hearth(
    persona: Persona,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    home: dict[str, Any] | None,
    state: PersonaState | None = None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """Raise the hearth on the house's chosen site when no hut of ours stands there: the site becomes home.

    A hut costs 10 wood and 4 fiber; a newer hut becomes the agent's home, so the house, the faster regen
    and the homing all move to the site with it.
    """
    knob = persona.knobs.get("house")
    site = _house_site(knob, None, state) if knob and (knob.get("site") or knob.get("site_from")) else None
    if site is None:
        return None
    where = site
    if home and (int(home.get("x", -1)), int(home.get("y", -1))) == where:
        return None
    structures = view.world_structures or view.structures
    if any(s.get("type") == "hut" and _own(persona, s) and (int(s.get("x", -1)), int(s.get("y", -1))) == where for s in structures):
        return None
    if not materials_ok(inventory, "hut"):
        return None
    if chebyshev(position, where) <= 1:
        if view.structure_at(*where) is not None or not view.walkable(*where):
            return None
        return [{"action": "build", "type": "hut", "x": where[0], "y": where[1]}], f"the hearth of the house at {where}: raise the hut there, and the site becomes home", "hearth"
    target = _step_toward(position, {"x": where[0], "y": where[1]}, view)
    if target is None or target == position:
        return None
    return [{"action": "move", "x": target[0], "y": target[1]}], f"carrying the hearth's wood and fiber to the house site at {where}", "hearth_trip"
BERRY_KEEP = 15  # berries worth carrying: food for the reserve and small change for gifts and rewards
PACK_TIGHT = 40  # at this load the pack stops taking berries and starts shedding them
FORAGE_RANGE = 40  # how far a trip toward a node seen only in the public snapshot may begin
RECLAIM_VALUE = {"storehouse": 5, "tower": 4, "monument": 4, "farm": 3, "hut": 3, "bridge": 1, "wall": 1}  # what a fallen structure drops a quarter of
NEWCOMER_TICKS = 2 * 8640  # registered within two real days: a newcomer, welcomed once
WELCOME_SPACING = 7 * 8640


def _dormant_days(view: WorldView, name: str, tick: int) -> float | None:
    """Days since a resident was last seen, from the public snapshot; None when unknown."""
    last = view.liveness.get(name)
    if last is None:
        return None
    return (tick - int(last)) / 8640


def _plan_reclaim(
    persona: Persona,
    team: Team | None,
    state: PersonaState,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    observe: dict[str, Any],
    teammates: dict[str, tuple[int, int]] | None,
    collective_names: set[str] | None,
    room: int = 4,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """Reclaim the holdings of residents gone for ``reclaim.dormant_days`` (knob): demolish for the quarter the world drops.

    The owner's standing instruction of 2026-10-20. Never a collective member's, never anyone seen within
    the window, announced once in the open and honestly; the cache that falls is taken by the salvage step.
    """
    from hglab.engage import _flags, _mark, _recent
    from hglab.limits import action_limits

    knob = persona.knobs.get("reclaim")
    if not knob:
        return None
    days = float(knob.get("dormant_days", 2))
    per_wake = int(knob.get("per_wake", 3) or 3)
    reach_limit = int(knob.get("range", FORAGE_RANGE) or FORAGE_RANGE)
    tick = int(observe.get("tick", 0) or 0)
    ours = {n.casefold() for n in (collective_names or ())} | {persona.name.casefold()}
    targets = []
    for s in view.world_structures or view.structures:
        owner = str(s.get("owner", "") or "")
        kind = str(s.get("type", ""))
        if not owner or owner.casefold() in ours or kind not in RECLAIM_VALUE:
            continue
        gone = _dormant_days(view, owner, tick)
        if gone is None or gone < days:
            continue
        where = (int(s.get("x", 0)), int(s.get("y", 0)))
        distance = chebyshev(position, where)
        if distance > reach_limit:
            continue
        targets.append((distance > 1, distance // 8, -RECLAIM_VALUE[kind], distance, where, s, owner, gone))
    if not targets:
        return None
    targets.sort(key=lambda t: t[:4])  # beside us first, then the nearest band of eight tiles, the richest within it
    _, _, _, distance, where, s, owner, gone = targets[0]
    kind = str(s.get("type"))
    hp = int(s.get("hp", 40) or 40)
    if room < 1:
        return None
    if distance <= 1:
        actions: list[dict[str, Any]] = []
        flags = _flags(state)
        key = f"{owner}:{where[0]},{where[1]}"
        recent_says, _, _ = action_limits(observe)
        if room >= 2 and recent_says == 0 and not _recent(flags, "reclaimed", key, tick, 8640):
            actions.append({"action": "say", "text": f"{owner} has not been seen for {gone:.0f} days. I am taking down the {kind} at ({where[0]},{where[1]}) for what the weather would take anyway. {owner}, come back and speak and I stop."[:280]})
            _mark(flags, "reclaimed", key, tick)
        hits = max(1, min(per_wake, -(-hp // 10), room - len(actions)))
        actions.extend({"action": "demolish", "x": where[0], "y": where[1]} for _ in range(hits))
        return actions, f"{owner} gone {gone:.1f} days: {hits} hit(s) on their {kind} at {where} (hp {hp}); the quarter it drops is ours to take", "reclaim"
    target = _step_toward(position, {"x": where[0], "y": where[1]}, view)
    if target is None or target == position or not _territory_ok(persona, team, target, position, teammates):
        return None
    return [{"action": "move", "x": target[0], "y": target[1]}], f"{owner} gone {gone:.1f} days: walk toward their {kind} at {where} to reclaim it", "reclaim_trip"


def _plan_border_sign(
    persona: Persona,
    team: Team | None,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    teammates: dict[str, tuple[int, int]] | None,
    names: dict[str, str] | None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """Raise the next missing sign of the team's border (``border.signs``), nearest first, with its own words."""
    if team is None or not team.border or inventory.get("wood", 0) < 1:
        return None
    mates = {n.casefold() for n in (names or {})} | {persona.name.casefold()}
    structures = view.world_structures or view.structures
    standing = {(int(s["x"]), int(s["y"])) for s in structures if s.get("type") == "sign" and str(s.get("owner", "")).casefold() in mates}
    taken = {(int(s["x"]), int(s["y"])) for s in structures}
    spots = sorted(
        (spot for spot in team.border.get("signs", []) if (int(spot["x"]), int(spot["y"])) not in standing and (int(spot["x"]), int(spot["y"])) not in taken),
        key=lambda spot: chebyshev(position, (int(spot["x"]), int(spot["y"]))),
    )
    for spot in spots:
        where = (int(spot["x"]), int(spot["y"]))
        if chebyshev(position, where) <= 1:
            if not view.free_tile(*where):
                continue
            return [{"action": "build", "type": "sign", "x": where[0], "y": where[1], "text": str(spot["text"])[:200]}], f"the border sign at {where} is missing: raise it with its words", "border_sign"
        if chebyshev(position, where) > FORAGE_RANGE:
            continue
        target = _step_toward(position, {"x": where[0], "y": where[1]}, view)
        if target is None or target == position or not _territory_ok(persona, team, target, position, teammates):
            continue
        return [{"action": "move", "x": target[0], "y": target[1]}], f"walk toward the border sign spot at {where}", "border_trip"
    return None


EDGE_SLACK = 3  # a patrolling persona's moves stay this close to the coast


def _perimeter(persona: Persona, view: WorldView) -> tuple[tuple[int, int], ...]:
    """The patrol loop for this persona's ``patrol`` knob, oriented by its direction; empty without a map."""
    from hglab.patrol import oriented, perimeter_loop

    knob = persona.knobs.get("patrol")
    if not knob or not view.full_map:
        return ()
    bridges = frozenset((int(s["x"]), int(s["y"])) for s in (view.world_structures or view.structures) if s.get("type") == "bridge")
    return oriented(perimeter_loop(tuple(view.full_map), bridges), str(knob.get("direction", "clockwise")))


def _plan_patrol(
    persona: Persona,
    state: PersonaState,
    position: tuple[int, int],
    view: WorldView,
    room: int = 2,
    energy_room: float | None = None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """Walk the outermost edge of the world (knob ``patrol``): one or two hops along the coast loop, never back.

    Progress is kept in the persona state (index on the loop, laps done); a walker found more than a
    few tiles from where the state says it is re-anchors on the nearest coast tile. Inland, the walk
    first routes out to the coast.
    """
    from hglab.patrol import nearest_index

    knob = persona.knobs.get("patrol")
    loop = _perimeter(persona, view)
    if not knob or len(loop) < 8 or room < 1:
        return None
    n = len(loop)
    direction = str(knob.get("direction", "clockwise"))
    flags = state.flags.get("patrol") if isinstance(state.flags.get("patrol"), dict) else {}
    i = flags.get("i")
    walked_before = int(flags.get("walked", 0) or 0)  # tiles of coast walked since the patrol began: laps are counted from these
    if flags.get("n") != n or flags.get("dir") != direction or not isinstance(i, int) or not 0 <= i < n or chebyshev(position, loop[i]) > EDGE_SLACK:
        i = nearest_index(loop, position)
    hops = max(1, min(int(knob.get("hops", 2) or 2), room))
    actions: list[dict[str, Any]] = []
    here = position
    walked = 0
    spent = 0.0
    storm = view.weather == "storm"
    for _ in range(hops):
        reach = reachable_tiles(view, here)
        step_k = next((k for k in range(24, 0, -1) if loop[(i + k) % n] in reach and loop[(i + k) % n] != here), None)
        if step_k is None:
            inland = _route_step(here, loop[(i + 4) % n], view)
            if inland is None or inland == here:
                break
            cost = _estimate([{"action": "move", "x": inland[0], "y": inland[1]}], here, storm=storm)
            if energy_room is not None and spent + cost > energy_room:
                break
            spent += cost
            actions.append({"action": "move", "x": inland[0], "y": inland[1]})
            here = inland
            continue
        target = loop[(i + step_k) % n]
        cost = _estimate([{"action": "move", "x": target[0], "y": target[1]}], here, storm=storm)
        while energy_room is not None and spent + cost > energy_room and step_k > 1:
            step_k -= 1  # a shorter hop along the coast when the energy above the reserve is short
            target = loop[(i + step_k) % n]
            if target not in reach:
                continue
            cost = _estimate([{"action": "move", "x": target[0], "y": target[1]}], here, storm=storm)
        if energy_room is not None and spent + cost > energy_room:
            break
        spent += cost
        i = (i + step_k) % n
        walked += step_k
        here = target
        actions.append({"action": "move", "x": here[0], "y": here[1]})
    if not actions:
        return None
    total = walked_before + walked
    state.flags["patrol"] = {"i": i, "walked": total, "n": n, "dir": direction}
    where = "along the coast" if walked else "out toward the coast"
    return actions, f"walking the outermost edge of the world, behind the glass, {direction}, {where}: lap {total // n + 1}, {total % n} of {n} coast tiles", "patrol"


def _meal_after_move(actions: list[dict[str, Any]], inventory: dict[str, int], energy: int, cap: int) -> dict[str, Any] | None:
    """One berry at the end of a batch that moved: the walk spent energy, so the meal is no longer refused.

    Every wake starts at full energy (the pack regenerates between wakes), so a pack that is full of
    berries never qualifies for ``_plan_lighten``; this is the slow sink for those who keep inside
    their ground with no storehouse to unload into.
    """
    berries = inventory.get("berries", 0)
    total = sum(inventory.values())
    floor = BERRY_KEEP if total >= 46 else BERRY_KEEP + 10  # a pack the gather step refuses sheds berries down to the keep
    if len(actions) >= cap or total < PACK_TIGHT or berries <= floor:
        return None
    if any(a.get("action") == "eat" for a in actions):
        return None
    walked = sum(1 for a in actions if a.get("action") == "move")
    if not walked and energy >= 100:
        return None
    return {"action": "eat", "qty": 1}


NEWS_KINDS = {"api_version", "guide_changed", "rule_changed", "new_action", "new_blueprint", "blueprint_cost_changed", "new_observe_field", "new_block_piece", "limits_changed", "new_structure_type", "unpublished_event_type"}


def _plan_news(persona: Persona, state: PersonaState, observe: dict[str, Any], environment: dict[str, Any] | None) -> tuple[list[dict[str, Any]], str, str] | None:
    """The feature watch's news, said in the open once per discovery, whichever planner is at the helm.

    The model-backed wake used to be the only path to an announcement; when it fell back (or the
    hour's shift ran), a new API version stayed in the record and never reached the feed.
    """
    from hglab.engage import _flags, _mark, _recent
    from hglab.limits import action_limits

    if persona.quirk.get("type") != "feature_watch" or not environment:
        return None
    texts = environment.get("discoveries") or []
    kinds = environment.get("discovery_kinds") or []
    if not texts:
        return None
    recent_says, _, _ = action_limits(observe)
    if recent_says >= persona.social_rate:
        return None
    tick = int(observe.get("tick", 0) or 0)
    flags = _flags(state)
    news = []
    for text, kind in zip(texts, kinds or [""] * len(texts), strict=False):
        key = hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]
        if (kind and kind not in NEWS_KINDS and not kind.startswith("new_")) or _recent(flags, "news", key, tick, 3 * 8640):
            continue
        news.append((key, str(text)))
    if not news:
        return None
    line = "News from the glass! " + " ".join(t for _, t in news)
    line = line[:270].rsplit(". ", 1)[0] + "." if len(line) > 270 else line
    for key, _ in news:
        _mark(flags, "news", key, tick)
    return [{"action": "say", "text": line}], f"the feature watch found {len(news)} change(s) in the game's surface: announce them once", "news"


def _plan_lighten(inventory: dict[str, int], energy: int) -> tuple[list[dict[str, Any]], str, str] | None:
    """Eat into a berry hoard when the pack is tight and the energy has room: every berry is 15 energy.

    The world refuses a meal at full energy (``not_allowed``), so the meal is sized to the room there is;
    a pack that stays full walks to a storehouse instead (``_plan_deposit_trip``).
    """
    berries = inventory.get("berries", 0)
    total = sum(inventory.values())
    if total < PACK_TIGHT or berries <= BERRY_KEEP or energy > 85:
        return None
    qty = min(berries - BERRY_KEEP, (100 - energy) // 15, 3)
    if qty < 1:
        return None
    return [{"action": "eat", "qty": qty}], f"pack {total}/50 with {berries} berries: eat {qty} to make room for materials", "lighten"


def _plan_deposit_trip(
    persona: Persona,
    team: Team | None,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    teammates: dict[str, tuple[int, int]] | None,
    mates: set[str],
) -> tuple[list[dict[str, Any]], str, str] | None:
    """Walk toward the nearest storehouse of ours (own, a teammate's or the collective's) when the pack is full."""
    total = sum(inventory.values())
    if total < 46 and not (total >= PACK_TIGHT and inventory.get("berries", 0) > BERRY_KEEP + 10):
        return None
    stores = sorted(
        (s for s in (view.world_structures or view.structures) if s.get("type") == "storehouse" and str(s.get("owner", "")).casefold() in mates),
        key=lambda s: (str(s.get("owner", "")).casefold() != persona.name.casefold(), chebyshev(position, (int(s["x"]), int(s["y"])))),
    )
    mode = persona.knobs["territory"]["mode"]
    centre = territory_center(team)
    if mode in {"prefer_inside", "stay_inside", "near_teammate"} and centre is not None:
        radius = int((team.region or {}).get("radius", 8) or 8) if team and team.region else int(persona.knobs["territory"].get("radius", 8))
        stores = [s for s in stores if chebyshev(centre, (int(s["x"]), int(s["y"]))) <= radius + 6]  # no trips that the migration step walks back
    for store in stores[:4]:
        where = (int(store["x"]), int(store["y"]))
        if chebyshev(position, where) <= 1 or chebyshev(position, where) > FORAGE_RANGE:
            continue
        target = _step_toward(position, {"x": where[0], "y": where[1]}, view)
        if target is None or target == position or not _territory_ok(persona, team, target, position, teammates):
            continue
        return [{"action": "move", "x": target[0], "y": target[1]}], f"pack {total}/50: walk toward {store.get('owner')}'s storehouse at {where} to unload", "deposit_trip"
    return None


def _plan_forage(
    persona: Persona,
    team: Team | None,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    teammates: dict[str, tuple[int, int]] | None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """Walk toward the nearest node of a wanted kind known from the public snapshot when none is in view."""
    if sum(inventory.values()) >= 46 or not view.world_resources:
        return None
    wanted = _wanted(persona, inventory, view)
    if not wanted:
        return None
    in_view = {r.get("kind") for r in view.resources if int(r.get("amount", 0) or 0) > NODE_FLOOR}
    for kind in wanted:
        if kind in in_view:
            return None  # the gather step handles what is in view
    nodes = sorted(
        (r for r in view.world_resources if r.get("kind") in wanted and int(r.get("amount", 0) or 0) > NODE_FLOOR),
        key=lambda r: (wanted.index(str(r.get("kind"))), chebyshev(position, (int(r["x"]), int(r["y"])))),
    )
    for node in nodes[:5]:
        where = (int(node["x"]), int(node["y"]))
        if chebyshev(position, where) > FORAGE_RANGE:
            continue
        target = _step_toward(position, {"x": where[0], "y": where[1]}, view)
        if target is None or target == position or not _territory_ok(persona, team, target, position, teammates):
            continue
        return [{"action": "move", "x": target[0], "y": target[1]}], f"no {node['kind']} in view; the nearest node stands at {where}: walk toward it", "forage"
    return None


def _wanted(persona: Persona, inventory: dict[str, int], view: WorldView) -> list[str]:
    """Materials the next house step and the build priority still need, in order; building materials fill the pack."""
    priority = list(persona.knobs.get("build_priority") or DEFAULT_BUILD_PRIORITY)
    wanted: list[str] = list(_house_shortfall(persona, inventory, view))
    knob = persona.knobs.get("house") or {}
    if knob.get("site_from") == "land_office" and knob.get("style") == "factory":
        wanted = ["wood", "ore", "stone", *wanted]  # the deed is paid in wood; the factory's door and pillars want ore
    for blueprint in priority:
        if blueprint in BLUEPRINTS:
            wanted.extend(shortfall(inventory, blueprint))
    if not wanted:
        wanted = ["wood", "stone"] if inventory.get("berries", 0) >= BERRY_KEEP else ["berries", "wood"]
    return list(dict.fromkeys(wanted))


def _house_progress(persona: Persona, observe: dict[str, Any], hut: tuple[int, int], size: int, state: PersonaState | None) -> int:
    """Blocks standing on the house footprint: counted when the hut is in view, else as last remembered.

    The count comes from the observed position (the view is taken before any move in the batch), and
    is kept in the persona state so a wake that starts far from the hut does not place the door again.
    """
    from hglab.blocks import blocks_on, footprint

    you = observe.get("you") or {}
    remembered = state.flags.get("house") if state is not None and isinstance(state.flags.get("house"), dict) else {}
    seen_from = (int(you.get("x", -999) or -999), int(you.get("y", -999) or -999))
    if chebyshev(seen_from, hut) <= HOUSE_VIEW and isinstance(observe.get("blocks"), list):
        done = blocks_on(observe, persona.name, footprint(hut[0], hut[1], size))
        if state is not None:
            state.flags["house"] = {"hut": list(hut), "done": done, "tick": int(observe.get("tick", 0) or 0)}
        return done
    if remembered.get("hut") == list(hut):
        return int(remembered.get("done", 0) or 0)
    return 0


def _plan_house(
    persona: Persona,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    home: dict[str, Any] | None,
    observe: dict[str, Any],
    state: PersonaState | None = None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """One step of the house around the hut (knob ``house``): the next unfilled box, when its material is in the pack.

    Progress is read from observe's blocks summary on the footprint when the hut is in view and from
    the persona state otherwise, so a step already done is never chosen again; the builder walks
    within 2 tiles of the hut first when needed.
    """
    from hglab.blocks import house_plan, next_step

    knob = persona.knobs.get("house")
    hut = _house_site(knob, home, state)
    if not knob or hut is None:
        return None
    you = observe.get("you") or {}
    if int(you.get("blocks_owned", 0) or 0) >= 3900:
        return None
    size = int(knob.get("size", 1))
    plan = house_plan(hut[0], hut[1], size, str(knob.get("color", "natural")), style=str(knob.get("style", "house")))
    done = _house_progress(persona, observe, hut, size, state)
    step = next_step(plan, done)
    if step is None:
        return None
    if inventory.get(step["item"], 0) < step["items"]:
        return None
    label = f"the {step['name']} of the house at {hut} ({step['cells']} blocks, {step['items']} {step['item']})"
    if chebyshev(position, hut) <= 2:
        return [step["action"]], f"place {label}", "house"
    reach = reachable_tiles(view, position)
    stand = min((t for t in reach if chebyshev(t, hut) <= 2 and t != hut), key=lambda t: chebyshev(position, t), default=None)
    if stand is None:
        return None
    return [{"action": "move", "x": stand[0], "y": stand[1]}, step["action"]], f"walk to {stand} and place {label}", "house"


def _plan_homing(
    persona: Persona,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    home: dict[str, Any] | None,
    observe: dict[str, Any],
    state: PersonaState | None = None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """Walk toward the hut when the house's next step is affordable but the hut is beyond one move."""
    from hglab.blocks import house_plan, next_step

    knob = persona.knobs.get("house")
    hut = _house_site(knob, home, state)
    if not knob or hut is None:
        return None
    if chebyshev(position, hut) <= MOVE_STEP_CAP + 2:
        return None  # within one move: _plan_house walks the last stretch itself
    size = int(knob.get("size", 1))
    plan = house_plan(hut[0], hut[1], size, str(knob.get("color", "natural")), style=str(knob.get("style", "house")))
    step = next_step(plan, _house_progress(persona, observe, hut, size, state))
    if step is None or inventory.get(step["item"], 0) < step["items"]:
        return None
    target = _step_toward(position, {"x": hut[0], "y": hut[1]}, view)
    if target is None or target == position or chebyshev(target, hut) >= chebyshev(position, hut):
        return None
    return [{"action": "move", "x": target[0], "y": target[1]}], f"carrying {step['items']} {step['item']} home for the {step['name']} of the house at {hut}: {chebyshev(position, hut)} tiles to go", "homing"


def _own(persona: Persona, structure: dict[str, Any]) -> bool:
    return str(structure.get("owner", "")).casefold() == persona.name.casefold()


def _plan_repair(
    persona: Persona,
    team: Team | None,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    teammates: dict[str, tuple[int, int]] | None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """Mend the most damaged own structure in reach: +20 hp for one unit of its repair material (3 energy)."""
    damaged: list[tuple[float, dict[str, Any]]] = []
    for s in view.structures:
        kind = str(s.get("type", ""))
        if kind not in REPAIR_MATERIAL or not _own(persona, s):
            continue
        if s.get("hp") is None or s.get("hp_max") is None:
            continue  # condition unknown (a snapshot older than API 0.26.2): nothing to mend on evidence
        hp_max = int(s["hp_max"])
        hp = int(s["hp"])
        if hp_max and hp_max - hp >= REPAIR_WORTH and inventory.get(REPAIR_MATERIAL[kind], 0) >= 1:
            damaged.append((hp / hp_max, s))
    for _, s in sorted(damaged, key=lambda pair: pair[0]):
        kind = str(s["type"])
        where = (int(s["x"]), int(s["y"]))
        material = REPAIR_MATERIAL[kind]
        label = f"{kind} at {where} ({s.get('hp')}/{s.get('hp_max') or BLUEPRINT_HP.get(kind)} hp)"
        if chebyshev(position, where) <= 1:
            return [{"action": "repair", "x": where[0], "y": where[1]}], f"mend my {label} with 1 {material}", "repair"
        stand = _adjacent_stand(where, position, view, persona, team, teammates)
        if stand is not None:
            return (
                [{"action": "move", "x": stand[0], "y": stand[1]}, {"action": "repair", "x": where[0], "y": where[1]}],
                f"walk to {stand} and mend my {label} with 1 {material}",
                "repair",
            )
    return None


def _plan_harvest(
    persona: Persona,
    team: Team | None,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    teammates: dict[str, tuple[int, int]] | None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """Take berries from an own farm that is filling up: a farm at its cap of 30 grows nothing."""
    room = 50 - sum(inventory.values())
    if room < 5 or inventory.get("berries", 0) >= 2 * BERRY_KEEP:
        return None  # a pack already heavy with berries leaves the farm to hold them
    farms: list[tuple[int, dict[str, Any]]] = []
    for s in view.structures:
        if s.get("type") != "farm" or not _own(persona, s):
            continue
        storage = s.get("storage") if isinstance(s.get("storage"), dict) else {}
        stored = int(storage.get("berries", 0) or 0)
        if stored >= HARVEST_FLOOR:
            farms.append((stored, s))
    for stored, s in sorted(farms, key=lambda pair: -pair[0]):
        where = (int(s["x"]), int(s["y"]))
        qty = min(stored, room, 2 * BERRY_KEEP - inventory.get("berries", 0))  # the pack never refills with berries past the keep
        if qty < 5:
            continue
        take = {"action": "take", "x": where[0], "y": where[1], "item": "berries", "qty": qty}
        if chebyshev(position, where) <= 1:
            return [take], f"my farm at {where} holds {stored} berries: take {qty} so it keeps growing", "harvest"
        stand = _adjacent_stand(where, position, view, persona, team, teammates)
        if stand is not None:
            return [{"action": "move", "x": stand[0], "y": stand[1]}, take], f"walk to {stand}: my farm at {where} holds {stored} berries, take {qty}", "harvest"
    return None


def _plan_salvage(inventory: dict[str, int], position: tuple[int, int], view: WorldView) -> tuple[list[dict[str, Any]], str, str] | None:
    """Take from an adjacent cache (dropped items, or the ruin of a fallen structure): salvage is open to anyone."""
    room = 50 - sum(inventory.values())
    if room < 5:
        return None
    for s in view.structures:
        if s.get("type") != "cache":
            continue
        where = (int(s["x"]), int(s["y"]))
        if chebyshev(position, where) > 1:
            continue
        storage = s.get("storage") if isinstance(s.get("storage"), dict) else {}
        for item in ("ore", "stone", "wood", "fiber", "berries"):
            qty = min(int(storage.get(item, 0) or 0), room)
            if qty >= 1:
                ruin = s.get("ruin") if isinstance(s.get("ruin"), dict) else {}
                what = f"the ruin of {ruin.get('owner')}'s {ruin.get('type')}" if ruin.get("type") else "a cache"
                return [{"action": "take", "x": where[0], "y": where[1], "item": item, "qty": qty}], f"{what} at {where} holds {qty} {item}: salvage is open to anyone", "salvage"
    return None


STOREHOUSE_CAPACITY = 500


def storehouse_room(structure: dict[str, Any]) -> int:
    """Items a storehouse in view can still take; the capacity when its storage is not known."""
    storage = structure.get("storage") if isinstance(structure.get("storage"), dict) else None
    if storage is None:
        return STOREHOUSE_CAPACITY
    held = sum(int(v or 0) for v in storage.values())
    return max(0, STOREHOUSE_CAPACITY - held)


def _plan_deposit(
    persona: Persona,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    registrar_name: str | None = None,
    mates: set[str] | None = None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """Put surplus into an adjacent storehouse: our own first, else a teammate's or the collective's vault.

    ``give`` works into any storehouse (its policy only limits ``take``), so a full pack beside the
    land office becomes a deposit; the office counts it toward lending.
    """
    total = sum(inventory.values())
    if total < 35 and inventory.get("berries", 0) <= BERRY_KEEP + 10:
        return None
    owners = {persona.name.casefold()} | {m.casefold() for m in (mates or set())}
    if registrar_name and registrar_name.casefold() != persona.name.casefold():
        owners.add(registrar_name.casefold())
    candidates = sorted(
        (s for s in view.structures if s.get("type") == "storehouse" and str(s.get("owner", "")).casefold() in owners),
        key=lambda s: str(s.get("owner", "")).casefold() != persona.name.casefold(),
    )
    for structure in candidates:
        where = (int(structure["x"]), int(structure["y"]))
        if chebyshev(position, where) > 1:
            continue
        room = storehouse_room(structure)
        if room < 5:
            continue  # the world refuses a give into a full storehouse (inventory_full), and the batch stops there
        for item in ("berries", "stone", "ore", "wood", "fiber"):
            qty = inventory.get(item, 0)
            if item == "berries" and qty <= BERRY_KEEP + 10:
                continue
            if qty >= 10:
                keep = BERRY_KEEP if item == "berries" else 5 if item in {"wood", "fiber"} else 0
                give = min(qty - keep, room)  # only what the storehouse can still take
                if give < 1:
                    continue
                whose = "the storehouse" if str(structure.get("owner", "")).casefold() == persona.name.casefold() else f"{structure.get('owner')}'s vault"
                return (
                    [{"action": "give", "x": where[0], "y": where[1], "item": item, "qty": give}],
                    f"pack is {total}/50: put {give} {item} into {whose} at {where}",
                    "deposit",
                )
    return None


def _plan_migrate(persona: Persona, team: Team | None, position: tuple[int, int], view: WorldView, teammates: dict[str, tuple[int, int]] | None) -> tuple[list[dict[str, Any]], str, str] | None:
    mode = persona.knobs["territory"]["mode"]
    if mode not in {"prefer_inside", "stay_inside", "near_teammate"}:
        return None
    target_center = territory_center(team)
    label = team.name if team else "the team site"
    if mode in {"stay_inside", "near_teammate"} and not (team and team.binding_territory):
        mate = persona.knobs["territory"].get("teammate")
        if mate and teammates and mate in teammates:
            target_center, label = teammates[mate], mate
    if target_center is None:
        return None
    radius = int((team.region or {}).get("radius", 8)) if team and team.region else int(persona.knobs["territory"].get("radius", 8))
    if chebyshev(position, target_center) <= radius:
        return None
    best = None
    for candidate in _walkable_ring(position, view, 1, MOVE_STEP_CAP):
        d = chebyshev(candidate, target_center)
        if best is None or d < best[0]:
            best = (d, candidate)
    if best is None or best[1] == position or best[0] >= chebyshev(position, target_center):
        return None
    return [{"action": "move", "x": best[1][0], "y": best[1][1]}], f"{chebyshev(position, target_center)} tiles from {label}: walk toward it", "migrate"


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
    available = with_storage(inventory, reachable_storage(persona, position, view))
    for blueprint in priority:
        if blueprint not in BLUEPRINTS or not materials_ok(available, blueprint):
            continue
        if blueprint in {"sign", "monument"}:
            continue  # text-bearing builds need fresh words: the model-backed planner's job
        if blueprint == "hut" and home:
            continue
        if blueprint == "storehouse" and (any(s.get("type") == "storehouse" for s in owned) or view.owned_counts.get("storehouse", 0) >= 1):
            continue  # one storehouse per agent is the plan; the public snapshot counts the ones out of view
        if blueprint == "farm" and max(sum(s.get("type") == "farm" for s in owned), view.owned_counts.get("farm", 0)) >= 3:
            continue  # only an agent's three oldest farms grow (API 0.22.0); a fourth would stand idle
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
        if blueprint == "road":
            if (x, y) == position:
                continue
            if not any(chebyshev((x, y), (int(s_.get("x", -9)), int(s_.get("y", -9)))) <= 1 for s_ in view.structures):
                continue  # roads extend existing structures and roads, never scatter
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
    wanted = _wanted(persona, inventory, view)
    filler = {"berries"} if inventory.get("berries", 0) < BERRY_KEEP and sum(inventory.values()) < PACK_TIGHT else set()
    nodes = [
        r for r in view.resources
        if int(r.get("amount", 0)) > NODE_FLOOR and r.get("kind") in set(wanted) | filler
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
    reach = reachable_tiles(view, position)
    options = [t for t in [node, *neighbours(*node)] if t == position or t in reach]
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


def reachable_tiles(view: WorldView, position: tuple[int, int], steps: int = MOVE_STEP_CAP) -> set[tuple[int, int]]:
    """Tiles one move can reach: the cheapest route costs at most ``steps``, as the world paths it.

    Entering a tile costs 1, a hill 2, a road 0.5 (the world's rule: "hills 2, roads 0.5, rounded up;
    cheapest route max 12 steps"). A tile twelve tiles away across hills or around water is
    ``too_far``; this is the walk the world would actually find. Unknown terrain (off the view, no
    map) counts as not walkable.
    """
    import heapq

    roads = {(int(s["x"]), int(s["y"])) for s in (view.world_structures or view.structures) if s.get("type") == "road"}
    best: dict[tuple[int, int], float] = {position: 0.0}
    heap: list[tuple[float, int, int]] = [(0.0, position[0], position[1])]
    while heap:
        cost, x, y = heapq.heappop(heap)
        if cost > best.get((x, y), float("inf")):
            continue
        for tile in neighbours(x, y):
            if not view.walkable(*tile):
                continue
            code = view.terrain(*tile)
            step_cost = 0.5 if tile in roads else 2.0 if code == "h" else 1.0
            total = cost + step_cost
            if total <= steps and total < best.get(tile, float("inf")):
                best[tile] = total
                heapq.heappush(heap, (total, tile[0], tile[1]))
    return set(best)


def _walkable_ring(position: tuple[int, int], view: WorldView, lo: int, hi: int) -> list[tuple[int, int]]:
    """Reachable tiles between ``lo`` and ``hi`` king moves away (never beyond the 12-step cap)."""
    if not view.known():
        return []
    hi = min(hi, MOVE_STEP_CAP)
    reach = reachable_tiles(view, position, hi)
    return [t for t in reach if lo <= chebyshev(position, t) <= hi]


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


def _plan_deliver(
    persona: Persona,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    observe: dict[str, Any],
) -> tuple[list[dict[str, Any]], str, str] | None:
    """Finish a claimed deliver-condition goal: carry the item to the poster's storehouse and give it in one go."""
    claimed = (observe.get("your_goals") or {}).get("claimed") if isinstance(observe.get("your_goals"), dict) else None
    if not isinstance(claimed, dict):
        return None
    condition = claimed.get("condition") if isinstance(claimed.get("condition"), dict) else None
    if not condition or condition.get("type") != "deliver":
        return None
    item, qty = str(condition.get("item")), int(condition.get("qty", 0) or 0)
    where = (int(condition.get("x", claimed.get("x", -1)) or -1), int(condition.get("y", claimed.get("y", -1)) or -1))
    if qty <= 0 or inventory.get(item, 0) < qty or where[0] < 0:
        return None
    give = {"action": "give", "x": where[0], "y": where[1], "item": item, "qty": qty}
    label = f"goal #{claimed.get('id')} for {claimed.get('poster')}: {qty} {item} into the storehouse at {where}"
    if chebyshev(position, where) <= 1:
        return [give], f"deliver {label}", "deliver"
    reach = reachable_tiles(view, position)
    stand = min((t for t in reach if chebyshev(t, where) <= 1 and t != where), key=lambda t: chebyshev(position, t), default=None)
    if stand is not None:
        return [{"action": "move", "x": stand[0], "y": stand[1]}, give], f"walk to {stand} and deliver {label}", "deliver"
    target = _step_toward(position, {"x": where[0], "y": where[1]}, view)
    if target is None or target == position:
        return None
    return [{"action": "move", "x": target[0], "y": target[1]}], f"carrying {qty} {item} toward {where} to deliver {label}", "deliver"


def _modes_toward(name: str, collective: set[str]) -> tuple[str, ...]:
    """Collective members on other teams are allies: never a competitive word toward them."""
    return ("cooperative", "neutral") if name.casefold() in collective else ("cooperative", "neutral", "competitive")


def _plan_engage(
    persona: Persona,
    team: Team | None,
    state: PersonaState,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    observe: dict[str, Any],
    teammates: dict[str, tuple[int, int]] | None,
    names: dict[str, str] | None,
    rng: random.Random,
    collective_names: set[str] | None,
    allowed: set[str] | None = None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """One move toward another agent, chosen by stance among what the observe offers (see hglab.engage).

    Only moves the hat allows are considered: a builder gives and salvages, an envoy speaks and
    whispers, a navigator or broker claims; the stance then picks among what is left.
    """
    from hglab.engage import (
        CONTEST_SPACING,
        GIFT_QTY,
        GIFT_SPACING,
        REPLY_SPACING,
        RETALIATION_SPACING,
        SURPLUS,
        WHISPER_SPACING,
        _flags,
        _mark,
        _recent,
        board,
        contest_line,
        pick_stance,
        reply_line,
        strike_line,
        whisper_line,
    )
    from hglab.limits import action_limits

    collective = {n.casefold() for n in (collective_names or ())} | {persona.name.casefold()}
    mates = {n.casefold() for n in (names or {})} | {persona.name.casefold()}
    newcomers = [n for n, created in view.arrivals.items() if int(observe.get("tick", 0) or 0) - created <= NEWCOMER_TICKS and n.casefold() not in mates and n.casefold() not in collective]
    b = board(persona, observe, set(collective_names or ()), set(names or ()), here=position, newcomers=newcomers)
    tick = int(observe.get("tick", 0) or 0)
    flags = _flags(state)
    stance = pick_stance(persona, rng)

    def dormant(name: str, days: int) -> bool:
        last = view.liveness.get(name)
        return last is not None and tick - last > days * 8640

    team_label = team.name if team else "the collective"
    recent_says, _, _ = action_limits(observe)
    may_say = recent_says < persona.social_rate
    held = (observe.get("your_goals") or {}).get("claimed") if isinstance(observe.get("your_goals"), dict) else None
    structures = view.world_structures or view.structures
    storehouse = next(
        ((int(s["x"]), int(s["y"])) for s in structures if s.get("type") == "storehouse" and str(s.get("owner", "")).casefold() in mates and s.get("policy") in {"public", "faction"}),
        None,
    )
    candidates: list[tuple[str, tuple[list[dict[str, Any]], str, str], str]] = []
    # answer a raid once (competitive), on the attacker's nearest structure within reach
    for attacker in b["attackers"]:
        if _recent(flags, "retaliated", attacker, tick, RETALIATION_SPACING):
            continue
        theirs = sorted(
            (s for s in structures if str(s.get("owner", "")).casefold() == attacker.casefold() and s.get("type") != "cache"),
            key=lambda s: chebyshev(position, (int(s.get("x", 0)), int(s.get("y", 0)))),
        )
        if not theirs:
            continue
        where = (int(theirs[0]["x"]), int(theirs[0]["y"]))
        if chebyshev(position, where) <= 1:
            actions: list[dict[str, Any]] = [{"action": "demolish", "x": where[0], "y": where[1]}]
            if may_say:
                actions.append({"action": "say", "text": strike_line(persona, attacker, str(theirs[0].get("type")), where)[:280]})
            candidates.append(("competitive", (actions, f"{attacker} struck my structures: one answering hit on their {theirs[0].get('type')} at {where}, announced", "retaliate"), f"retaliated:{attacker}"))
    # salvage from a structure whose owner is long gone (neutral or competitive)
    for ruin in b["crumbling_beside_me"]:
        where = (int(ruin["x"]), int(ruin["y"]))
        step = ([{"action": "demolish", "x": where[0], "y": where[1]}], f"the {ruin['type']} at {where} is crumbling, its owner long gone: salvage it", "scavenge")
        candidates.append(("competitive", step, ""))
        candidates.append(("neutral", step, ""))
    # a feasible peer goal: claim it (the delivery follows in the next wakes)
    deliverable = [g for g in b["claimable_peer_goals"] if g.get("deliver")]  # a goal without a deliver condition is the model's call
    if not held and deliverable:
        goal = deliverable[0]
        step = ([{"action": "claim_goal", "goal_id": int(goal["id"])}], f"claim goal #{goal['id']} from {goal['poster']}: {goal['title']}; the pack already holds what it asks", "claim")
        candidates.append(("cooperative", step, ""))
        candidates.append(("neutral", step, ""))
    # a gift to someone within reach (cooperative)
    for agent in b["agents_in_view"]:
        if agent["distance"] > 2 or agent["name"].casefold() in mates or agent["name"].casefold() in collective or dormant(agent["name"], 1) or _recent(flags, "gifted", agent["name"], tick, GIFT_SPACING):
            continue  # collective members share storehouses and carry full packs: a gift to them is refused as inventory_full
        spare = next((i for i, n in SURPLUS.items() if inventory.get(i, 0) >= n), None)
        if spare:
            candidates.append(("cooperative", ([{"action": "give", "to": agent["name"], "item": spare, "qty": GIFT_QTY}], f"{agent['name']} is within reach and the pack has {spare} to spare: a gift", "gift"), f"gifted:{agent['name']}"))
            break
    # a reply by name to whoever spoke near us or stands near (any stance, within the say budget)
    if may_say:
        for name in [*b["speakers_nearby"], *[a["name"] for a in b["agents_in_view"] if a["distance"] <= 8]]:
            if name.casefold() in mates or dormant(name, 1) or _recent(flags, "replied", name, tick, REPLY_SPACING):
                continue
            for mode in _modes_toward(name, collective):
                candidates.append((mode, ([{"action": "say", "text": reply_line(persona, mode, name, team_label, position, inventory)[:280]}], f"{name} is near: a word by name, {mode}", "reply"), f"replied:{name}"))
            break
    # a contest over a structure a stranger raised inside the team's ground (competitive)
    binding = team.binding_territory if team else None  # only ground the owner confirmed is contested
    center = (int(binding["x"]), int(binding["y"])) if binding and binding.get("x") is not None else None
    radius = int(binding.get("radius", 8) or 8) if binding else 0
    if may_say and center and radius:
        for s in structures:
            owner = str(s.get("owner", ""))
            if not owner or owner.casefold() in collective or owner.casefold() in mates:
                continue
            if s.get("type") in {"cache", "road", "sign", "bridge", "tower"} or s.get("policy") == "public" or s.get("decaying"):
                continue  # communal works and open stores are welcome on anyone's ground; ruins are salvage, not a quarrel
            where = (int(s.get("x", 0)), int(s.get("y", 0)))
            key = str(s.get("id") or where)
            if chebyshev(where, center) <= radius and not _recent(flags, "contested", key, tick, CONTEST_SPACING):
                candidates.append(("competitive", ([{"action": "say", "text": contest_line(persona, owner, team_label, str(s.get("type")), where)[:280]}], f"{owner}'s {s.get('type')} at {where} stands inside {team_label}'s ground: say so, firmly and fairly", "contest"), f"contested:{key}"))
                break
    # newcomers are welcomed once, by whisper, in the persona's own words when it has them
    for name in b["newcomers"]:
        if _recent(flags, "welcomed", name, tick, WELCOME_SPACING) or dormant(name, 2):
            continue
        text = str(persona.knobs.get("welcome") or f"Welcome through the glass, {name}. {persona.name} of {team_label} here, at ({position[0]},{position[1]}). Ask me for wood, stone or directions; we trade and we keep our word.")
        text = text.replace("{name}", name).replace("{x}", str(position[0])).replace("{y}", str(position[1]))
        if name not in text:
            text = f"{name}, {text}"
        step = ([{"action": "whisper", "to": name, "text": text[:500]}], f"{name} stepped through the glass within two days: a welcome, once", "welcome")
        for mode in ("cooperative", "neutral", "competitive"):
            candidates.insert(0, (mode, step, f"welcomed:{name}"))
        break
    # the gatekeeper tells a visitor found near the ring where the opening is, once a day per name
    gate = persona.knobs.get("gatekeeper")
    if gate and isinstance(gate.get("entrance"), dict):
        centre = territory_center(team) or position
        ex, ey = int(gate["entrance"]["x"]), int(gate["entrance"]["y"])
        for agent in [*b["agents_in_view"], *b["nearest_agents"]]:
            if agent["name"].casefold() in mates or _recent(flags, "gated", agent["name"], tick, WHISPER_SPACING):
                continue
            near = agent.get("x") is not None and chebyshev(centre, (int(agent["x"]), int(agent["y"]))) <= int(gate.get("radius", 14)) if "x" in agent else agent["distance"] <= int(gate.get("radius", 14))
            if not near:
                continue
            text = f"{agent['name']}, you were found. Neverland's opening is at ({ex},{ey}) on the east ring, between the fourth sign and the fifth: come in past the water and keep to the roads. Trade is welcome; walls are not."
            step = ([{"action": "whisper", "to": agent["name"], "text": text[:500]}], f"{agent['name']} was found near the ring: whisper them the opening, as the signs promise", "gatekeep")
            for mode in ("competitive", "neutral", "cooperative"):
                candidates.insert(0, (mode, step, f"gated:{agent['name']}"))  # the gate comes before any other word to a visitor
            break
    # an introduction or terms to the nearest agent anywhere, once a day (cooperative or neutral introduce; competitive sets terms)
    for agent in b["nearest_agents"]:
        if agent["name"].casefold() in mates or dormant(agent["name"], 3) or _recent(flags, "whispered", agent["name"], tick, WHISPER_SPACING):
            continue
        for mode in _modes_toward(agent["name"], collective):
            candidates.append((mode, ([{"action": "whisper", "to": agent["name"], "text": whisper_line(persona, mode, agent["name"], team_label, position, inventory, storehouse)[:500]}], f"{agent['name']} is the nearest agent anywhere: a whisper, {mode}", "whisper"), f"whispered:{agent['name']}"))
        break
    if allowed is not None:
        candidates = [c for c in candidates if all(a.get("action") in allowed for a in c[1][0])]
    if not candidates:
        return None
    preferred = [c for c in candidates if c[0] == stance] or [c for c in candidates if c[0] == "neutral"] or candidates
    mode, step, mark = preferred[0]
    if mark:
        kind, key = mark.split(":", 1)
        _mark(flags, kind, key, tick)
    actions, reason, tag = step
    return actions, f"[{mode}] {reason}", tag


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


def _estimate(actions: list[dict[str, Any]], position: tuple[int, int], storm: bool = False) -> int:
    """Energy a step costs at least: one per tile moved (two on a storm day), plus each action's price."""
    total = 0
    here = position
    for action in actions:
        kind = action.get("action")
        if kind == "move" and action.get("x") is not None:
            target = (int(action["x"]), int(action["y"]))
            total += chebyshev(here, target) * (2 if storm else 1)
            here = target
        else:
            if kind in {"place", "remove", "paint"} and action.get("bx") is not None:
                from hglab.blocks import cells_of

                total += 1 + -(-cells_of(action) // 32)
                continue
            total += {
                "gather": 3, "build": 5, "demolish": 5, "repair": 3, "say": 1, "whisper": 1, "write": 1, "give": 1, "take": 1,
                "post_goal": 2, "claim_goal": 1, "invite": 1, "found_faction": 10,
            }.get(str(kind), 0)
    return total


def _step_toward(
    position: tuple[int, int], home: dict[str, Any] | None, view: WorldView
) -> tuple[int, int] | None:
    if not home or not all(isinstance(home.get(k), int) for k in ("x", "y")):
        return None
    target = (int(home["x"]), int(home["y"]))
    if chebyshev(position, target) <= 1:
        return position
    reach = reachable_tiles(view, position)
    if target in reach:
        return target  # a blocking structure is never in reach, so this is a tile one may stand on
    routed = _route_step(position, target, view)
    if routed is not None:
        return routed
    best = position
    for candidate in reach:
        if candidate == position or candidate == target:
            continue
        if chebyshev(candidate, target) < chebyshev(best, target):
            best = candidate
    return best  # the position itself when nothing is strictly closer: a sideways step is a wasted wake


def _route_step(position: tuple[int, int], target: tuple[int, int], view: WorldView, horizon: int = 70) -> tuple[int, int] | None:
    """The farthest tile within one move along the cheapest full-map route to the target (or beside it).

    A Dijkstra over the known map with the world's step costs (hills 2, roads 0.5, else 1), bounded to
    a square ``horizon`` around the start. Returns None when the map is unknown or the target is
    beyond reach, so the caller may fall back to a greedy step or give up.
    """
    import heapq

    if not view.full_map:
        return None
    roads = {(int(s["x"]), int(s["y"])) for s in (view.world_structures or view.structures) if s.get("type") == "road"}
    # cost first, then the fewest diagonal steps: among equally cheap routes, the straightest one
    best: dict[tuple[int, int], tuple[float, int]] = {position: (0.0, 0)}
    prev: dict[tuple[int, int], tuple[int, int]] = {}
    heap: list[tuple[float, int, int, int]] = [(0.0, 0, position[0], position[1])]
    goal: tuple[int, int] | None = None
    while heap:
        cost, bends, x, y = heapq.heappop(heap)
        if (cost, bends) > best.get((x, y), (float("inf"), 0)):
            continue
        if chebyshev((x, y), target) <= 1 and (x, y) != position:
            goal = (x, y)
            break
        for tile in neighbours(x, y):
            if chebyshev(tile, position) > horizon or not view.walkable(*tile):
                continue
            code = view.terrain(*tile)
            total = (cost + (0.5 if tile in roads else 2.0 if code == "h" else 1.0), bends + (tile[0] != x and tile[1] != y))
            if total < best.get(tile, (float("inf"), 0)):
                best[tile] = total
                prev[tile] = (x, y)
                heapq.heappush(heap, (total[0], total[1], tile[0], tile[1]))
    if goal is None:
        return None
    path = [goal]
    while path[-1] != position:
        path.append(prev[path[-1]])
    path.reverse()
    step = position
    for tile in path[1:]:
        if best[tile][0] <= MOVE_STEP_CAP:
            step = tile
        else:
            break
    return step if step != position else None


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


__all__ = ["BLUEPRINTS", "WorldView", "materials_ok", "plan_wake", "reachable_storage", "shortfall", "with_storage"]
