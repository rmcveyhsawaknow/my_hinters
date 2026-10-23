"""The factory crew: a materials pipeline for a team's works.

A team file names a ``pipeline`` (the works' site, its radius, how far gatherers range, the stock the
factory stores should hold, and the structures to raise in order); a persona's ``crew`` knob names
its role in it. Every wake of a crew member runs ``plan_crew`` first: walk to the works when far,
unload a heavy pack into the nearest factory store (a storehouse of a team member within the works'
radius), raise the first store when none stands and the pack can pay, eat from a store when hungry,
then the role's own work: woodcutters clear the forest nearest the works, quarriers work the hills and
the mountain edge, provisioners the grass, haulers fill whatever the stock is shortest of (taking from
open stores of the collective when beside one), and the mason raises the plan's next structure beside
a store so the build pays from it, or gathers the shortfall by hand. Nodes are gathered to the
collective's floor, never stripped; nothing here speaks.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from hglab.mood import PersonaState
from hglab.persona import Persona, Team
from hglab.planner import (
    BERRY_KEEP,
    BLUEPRINTS,
    NODE_FLOOR,
    WorldView,
    _adjacent_stand,
    _full_stores,
    _mark_full,
    _step_toward,
    chebyshev,
    materials_ok,
    neighbours,
    reachable_storage,
    shortfall,
    storehouse_room,
    with_storage,
)

ROLE_WANTED: dict[str, list[str]] = {
    "woodcutter": ["wood"],
    "quarrier": ["stone", "ore"],
    "provisioner": ["fiber", "berries"],
    "hauler": ["wood", "berries", "fiber", "stone"],
    "mason": [],
}
HEAVY = 30  # goods in the pack (berries beyond the keep aside) that send a hand to the store
CARRY_RANGE = 40  # how far a load is carried to a factory store
HUNGRY = 3  # berries below this, with the energy near the reserve, draw ten from a store beside us

Step = tuple[list[dict[str, Any]], str, str]


def pipeline_of(team: Team | None) -> dict[str, Any] | None:
    cfg = (team.extra or {}).get("pipeline") if team is not None else None
    if not isinstance(cfg, dict) or not isinstance(cfg.get("site"), dict):
        return None
    return cfg


def team_member_names(persona: Persona, team: Team | None, names: dict[str, str] | None) -> set[str]:
    """The in-world names of the team's members, casefolded, this persona included."""
    out = {persona.name.casefold()}
    for name, slug in (names or {}).items():
        if team is not None and slug in team.members:
            out.add(str(name).casefold())
    return out


def factory_stores(view: WorldView, mates: set[str], site: tuple[int, int], radius: int) -> list[dict[str, Any]]:
    """Storehouses of team members within the works' radius; the in-view copy (with its storage) wins over the snapshot."""
    by_tile: dict[tuple[int, int], dict[str, Any]] = {}
    for s in [*view.world_structures, *view.structures]:
        if s.get("type") != "storehouse" or str(s.get("owner", "")).casefold() not in mates:
            continue
        where = (int(s["x"]), int(s["y"]))
        if chebyshev(where, site) <= radius:
            by_tile[where] = s
    return sorted(by_tile.values(), key=lambda s: chebyshev((int(s["x"]), int(s["y"])), site))


def stock_levels(stores: list[dict[str, Any]], wanted: dict[str, int]) -> dict[str, tuple[int, int]]:
    """Per kind: what the factory stores in view hold against the stock target."""
    held: Counter[str] = Counter()
    for s in stores:
        storage = s.get("storage") if isinstance(s.get("storage"), dict) else {}
        for item, qty in storage.items():
            held[str(item)] += int(qty or 0)
    return {kind: (held.get(kind, 0), int(target or 0)) for kind, target in wanted.items()}


def shortest_first(levels: dict[str, tuple[int, int]]) -> list[str]:
    return [k for k, _ in sorted(levels.items(), key=lambda kv: (kv[1][0] / kv[1][1] if kv[1][1] else 1.0, kv[0]))]


def plan_crew(
    persona: Persona,
    team: Team | None,
    state: PersonaState,
    observe: dict[str, Any],
    view: WorldView,
    inventory: dict[str, int],
    position: tuple[int, int],
    energy: int,
    reserve: int,
    room: int,
    collective_names: set[str] | None,
    names: dict[str, str] | None,
    teammates: dict[str, tuple[int, int]] | None,
) -> Step | None:
    """One pipeline step for a crew member, or None when the role has nothing to do from here."""
    cfg = pipeline_of(team)
    knob = persona.knobs.get("crew")
    if not cfg or not isinstance(knob, dict) or room < 1:
        return None
    role = str(knob.get("role") or "")
    site = (int(cfg["site"]["x"]), int(cfg["site"]["y"]))
    radius = int(cfg.get("radius", 7) or 7)
    reach = int(cfg.get("range", 16) or 16)
    mates = team_member_names(persona, team, names)
    stores = factory_stores(view, mates, site, radius)
    tick = int(view.tick or observe.get("tick", 0) or 0)
    pack = sum(inventory.values())
    goods = pack - min(inventory.get("berries", 0), BERRY_KEEP)

    # a. far from the works: walk there first
    distance = chebyshev(position, site)
    if distance > reach:
        target = _step_toward(position, {"x": site[0], "y": site[1]}, view)
        if target is not None and target != position:
            return [{"action": "move", "x": target[0], "y": target[1]}], f"{distance} tiles from the works at {site}: walk there", "crew"
        return None

    # b. a heavy pack goes to the nearest factory store with room
    if (goods >= HEAVY or pack >= 46) and stores:
        step = _unload(inventory, position, view, stores, room, state, tick, pack)
        if step is not None:
            return step

    # c. no store at the works yet: raise the first one when the pack can pay
    if not stores:
        if materials_ok(inventory, "storehouse"):
            if distance <= 3:
                tile = _works_tile("storehouse", position, view, site, radius)
                if tile is not None:
                    return (
                        [{"action": "build", "type": "storehouse", "x": tile[0], "y": tile[1], "policy": "faction"}],
                        f"no store at the works yet and the pack holds its cost: raise the first storehouse at {tile}",
                        "crew",
                    )
            target = _step_toward(position, {"x": site[0], "y": site[1]}, view)
            if target is not None and target != position:
                return [{"action": "move", "x": target[0], "y": target[1]}], f"carrying the first store's cost to the works at {site}", "crew"
        wanted = [*shortfall(inventory, "storehouse"), *ROLE_WANTED.get(role, [])]
        return _gather_toward(persona, team, list(dict.fromkeys(wanted)), inventory, position, view, site, reach, room, teammates, "for the first store")

    # d. hungry beside a store that holds berries: eat from the crew's own stock
    if inventory.get("berries", 0) < HUNGRY and energy < reserve + 15:
        for s in stores:
            where = (int(s["x"]), int(s["y"]))
            storage = s.get("storage") if isinstance(s.get("storage"), dict) else {}
            if chebyshev(position, where) <= 1 and int(storage.get("berries", 0) or 0) >= 5:
                qty = min(10, int(storage["berries"]), 50 - pack)
                if qty >= 1:
                    return [{"action": "take", "x": where[0], "y": where[1], "item": "berries", "qty": qty}], f"{inventory.get('berries', 0)} berries left and energy {energy}: take {qty} from the store at {where}", "crew"

    # e. the role's own work
    if role == "mason":
        return _mason(persona, team, cfg, inventory, position, view, stores, site, radius, reach, room, teammates, observe)
    if role == "hauler":
        step = _haul(persona, cfg, inventory, position, view, stores, collective_names, mates, pack, observe)
        if step is not None:
            return step
    wanted = list(ROLE_WANTED.get(role, []))
    if role == "hauler":
        levels = stock_levels(stores, cfg.get("stock") or {})
        wanted = [k for k in shortest_first(levels) if k in {"wood", "stone", "ore", "fiber", "berries"}] or wanted
    return _gather_toward(persona, team, wanted, inventory, position, view, site, reach, room, teammates, "for the works")


def _unload(
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    stores: list[dict[str, Any]],
    room: int,
    state: PersonaState,
    tick: int,
    pack: int,
) -> Step | None:
    full = _full_stores(state, tick)
    candidates = sorted(
        (s for s in stores if (int(s["x"]), int(s["y"])) not in full),
        key=lambda s: chebyshev(position, (int(s["x"]), int(s["y"]))),
    )
    for s in candidates:
        where = (int(s["x"]), int(s["y"]))
        if chebyshev(position, where) <= 1:
            space = storehouse_room(s)
            if space < 5:
                _mark_full(state, where, tick)
                continue
            gives: list[dict[str, Any]] = []
            for item in ("wood", "stone", "ore", "fiber", "berries"):
                keep = BERRY_KEEP if item == "berries" else 0
                qty = min(inventory.get(item, 0) - keep, space)
                if qty >= 1:
                    gives.append({"action": "give", "x": where[0], "y": where[1], "item": item, "qty": qty})
                    space -= qty
                if len(gives) >= room or space <= 0:
                    break
            if gives:
                what = ", ".join(f"{g['qty']} {g['item']}" for g in gives)
                return gives, f"pack {pack}/50: unload {what} into the store at {where}", "crew"
            continue
        if chebyshev(position, where) > CARRY_RANGE:
            continue
        target = _step_toward(position, {"x": where[0], "y": where[1]}, view)
        if target is not None and target != position:
            return [{"action": "move", "x": target[0], "y": target[1]}], f"pack {pack}/50: carry it to the store at {where}", "crew"
    return None


def _works_tile(kind: str, position: tuple[int, int], view: WorldView, site: tuple[int, int], radius: int) -> tuple[int, int] | None:
    """A free tile beside the builder, within the works, for this blueprint (farms want grass)."""
    terrain_ok = {"g"} if kind == "farm" else None
    options = [t for t in neighbours(*position) if chebyshev(t, site) <= radius and view.free_tile(*t, terrain_ok)]
    if kind == "bridge":
        options = [t for t in neighbours(*position) if view.terrain(*t) == "w" and view.structure_at(*t) is None]
    options.sort(key=lambda t: (chebyshev(t, site), t))
    return options[0] if options else None


def _mason(
    persona: Persona,
    team: Team | None,
    cfg: dict[str, Any],
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    stores: list[dict[str, Any]],
    site: tuple[int, int],
    radius: int,
    reach: int,
    room: int,
    teammates: dict[str, tuple[int, int]] | None,
    observe: dict[str, Any],
) -> Step | None:
    mates = team_member_names(persona, team, None) | {str(s.get("owner", "")).casefold() for s in stores}
    standing: dict[tuple[int, int], dict[str, Any]] = {}
    for s in [*view.world_structures, *view.structures]:
        if s.get("x") is None or s.get("y") is None:
            continue
        where = (int(s["x"]), int(s["y"]))
        if chebyshev(where, site) <= radius and (str(s.get("owner", "")).casefold() in mates or s.get("owner") is None):
            standing[where] = s
    counts = Counter(str(s.get("type")) for s in standing.values())
    item = next((p for p in (cfg.get("plan") or []) if isinstance(p, dict) and counts.get(str(p.get("type")), 0) < int(p.get("count", 1) or 1)), None)
    if item is None:
        return None  # the works stand; upkeep and the generic steps take over
    kind = str(item["type"])
    if kind not in BLUEPRINTS:
        return None
    you = observe.get("you") or {}
    faction = you.get("faction")
    faction_name = str(faction.get("name") if isinstance(faction, dict) else faction or "") or None
    storage = reachable_storage(persona, position, view, faction=faction_name)
    available = with_storage(inventory, storage)
    if materials_ok(available, kind):
        tile = _works_tile(kind, position, view, site, radius)
        if tile is not None:
            action: dict[str, Any] = {"action": "build", "type": kind, "x": tile[0], "y": tile[1]}
            if kind == "storehouse":
                action["policy"] = "faction"
            if kind == "sign" and item.get("text"):
                action["text"] = str(item["text"])[:200]
            paid = "the pack" if materials_ok(inventory, kind) else "the pack and the store beside me"
            return [action], f"the plan's next piece is a {kind} ({counts.get(kind, 0)} of {item.get('count', 1)} standing): raise it at {tile}, paid from {paid}", "crew"
        if chebyshev(position, site) > 2:
            target = _step_toward(position, {"x": site[0], "y": site[1]}, view)
            if target is not None and target != position:
                return [{"action": "move", "x": target[0], "y": target[1]}], f"materials for the {kind} in hand: walk to the works at {site}", "crew"
    beside = [s for s in stores if chebyshev(position, (int(s["x"]), int(s["y"]))) <= 1]
    if stores and not beside:
        nearest = stores[0]
        where = (int(nearest["x"]), int(nearest["y"]))
        target = _step_toward(position, {"x": where[0], "y": where[1]}, view)
        if target is not None and target != position:
            return [{"action": "move", "x": target[0], "y": target[1]}], f"the {kind} is next: stand by the store at {where} so the build pays from it", "crew"
    missing = shortfall(available, kind)
    wanted = [k for k, _ in sorted(missing.items(), key=lambda kv: -kv[1])]
    return _gather_toward(persona, team, wanted, inventory, position, view, site, reach, room, teammates, f"for the {kind}")


def _haul(
    persona: Persona,
    cfg: dict[str, Any],
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    stores: list[dict[str, Any]],
    collective_names: set[str] | None,
    mates: set[str],
    pack: int,
    observe: dict[str, Any],
) -> Step | None:
    """Beside an open store of the collective outside the works: take what the stock is shortest of."""
    if pack >= 40:
        return None
    you = observe.get("you") or {}
    faction = you.get("faction")
    faction_name = str(faction.get("name") if isinstance(faction, dict) else faction or "")
    factory_tiles = {(int(s["x"]), int(s["y"])) for s in stores}
    collective = {n.casefold() for n in (collective_names or set())} | mates
    levels = stock_levels(stores, cfg.get("stock") or {})
    order = shortest_first(levels)
    for s in view.structures:
        if s.get("type") != "storehouse" or (int(s["x"]), int(s["y"])) in factory_tiles:
            continue
        where = (int(s["x"]), int(s["y"]))
        if chebyshev(position, where) > 1 or str(s.get("owner", "")).casefold() not in collective:
            continue
        policy = str(s.get("policy") or "private")
        admits = policy == "public" or (policy == "faction" and faction_name and str(s.get("faction") or "").casefold() == faction_name.casefold())
        if not admits:
            continue
        storage = s.get("storage") if isinstance(s.get("storage"), dict) else {}
        for kind in order:
            held, target = levels.get(kind, (0, 0))
            if target and held >= target:
                continue
            qty = min(int(storage.get(kind, 0) or 0), 50 - pack, 20)
            if qty >= 5:
                return [{"action": "take", "x": where[0], "y": where[1], "item": kind, "qty": qty}], f"the works is short of {kind} ({held} of {target}): take {qty} from the open store at {where}", "crew"
    return None


def _gather_toward(
    persona: Persona,
    team: Team | None,
    wanted: list[str],
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    site: tuple[int, int],
    reach: int,
    room: int,
    teammates: dict[str, tuple[int, int]] | None,
    why: str,
) -> Step | None:
    """Gather a wanted kind from the node nearest the works (clearing from the site outward), or walk toward one."""
    if sum(inventory.values()) >= 46 or not wanted:
        return None
    rank = {k: i for i, k in enumerate(wanted)}
    nodes = [
        r for r in view.resources
        if str(r.get("kind")) in rank and int(r.get("amount", 0) or 0) > NODE_FLOOR and chebyshev(site, (int(r["x"]), int(r["y"]))) <= reach
    ]
    nodes.sort(key=lambda r: (rank[str(r["kind"])], chebyshev(site, (int(r["x"]), int(r["y"]))), chebyshev(position, (int(r["x"]), int(r["y"])))))
    for node in nodes:
        where = (int(node["x"]), int(node["y"]))
        kind = str(node["kind"])
        if chebyshev(position, where) <= 1:
            return [{"action": "gather", "kind": kind}], f"{kind} at {where} beside me {why}: take five, leave the rest", "crew"
        if room < 2:
            continue
        stand = _adjacent_stand(where, position, view, persona, team, teammates)
        if stand is not None and stand != position:
            return [{"action": "move", "x": stand[0], "y": stand[1]}, {"action": "gather", "kind": kind}], f"walk to {stand} and gather {kind} at {where} {why}", "crew"
    far = [
        r for r in view.world_resources
        if str(r.get("kind")) in rank and int(r.get("amount", 0) or 0) > NODE_FLOOR and chebyshev(site, (int(r["x"]), int(r["y"]))) <= reach
    ]
    far.sort(key=lambda r: (rank[str(r["kind"])], chebyshev(site, (int(r["x"]), int(r["y"]))), chebyshev(position, (int(r["x"]), int(r["y"])))))
    for node in far[:6]:
        where = (int(node["x"]), int(node["y"]))
        target = _step_toward(position, {"x": where[0], "y": where[1]}, view)
        if target is not None and target != position:
            return [{"action": "move", "x": target[0], "y": target[1]}], f"toward the {node['kind']} at {where} {why}", "crew"
    return None


__all__ = ["ROLE_WANTED", "factory_stores", "pipeline_of", "plan_crew", "shortest_first", "stock_levels"]
