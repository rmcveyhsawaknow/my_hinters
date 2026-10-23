"""Crews: a materials pipeline for a team's works, and the land office's claims.

A team file names a ``pipeline`` (the works' site, its radius, how far gatherers range, the stock the
stores should hold, the structures to raise in order, the node floor) and, for the land office, a
``claims`` block (the registrar, how many of its best staked lots are holdings, that every ore lot is
one, how many depots to raise, the floor its holdings are worked to and where the collective's floor
still stands); a persona's ``crew`` knob names its role. Every wake of a crew member runs
``plan_crew`` first: walk to the works when far, unload a heavy pack into the nearest store with room
(the works' stores, or in claims mode any depot of the team), raise the first store when none stands
and the pack can pay, eat from a store when hungry, then the role's own work. Woodcutters, quarriers
and provisioners gather the node nearest the works first, or in claims mode the best holding first;
haulers fill whatever the stock is shortest of, taking from open stores of the collective (or from the
team's depots) when beside one; the mason raises the plan's next structure beside a store so the build
pays from it, or in claims mode the depots on the best holdings first, or gathers the shortfall by
hand. Nodes are gathered to the floor the team sets (the collective's five by default); nothing here
speaks.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

from hglab.lots import holdings as office_holdings
from hglab.lots import lot_bounds, lot_id, node_floor
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
CARRY_RANGE = 40  # how far a load is carried to a store
HUNGRY = 3  # berries below this, with the energy near the reserve, draw ten from a store beside us
EMPTY_DEPOT_TICKS = 2160  # a depot found empty is left alone for six hours
FAR_RANK = 10**6  # a node outside every holding, in claims mode: after all of them

Step = tuple[list[dict[str, Any]], str, str]
FloorFor = Callable[[tuple[int, int]], int]


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


def _team_stores(view: WorldView, mates: set[str]) -> dict[tuple[int, int], dict[str, Any]]:
    """Every storehouse of a team member; the in-view copy (with its storage) wins over the snapshot."""
    by_tile: dict[tuple[int, int], dict[str, Any]] = {}
    for s in [*view.world_structures, *view.structures]:
        if s.get("type") != "storehouse" or str(s.get("owner", "")).casefold() not in mates:
            continue
        if s.get("x") is None or s.get("y") is None:
            continue
        by_tile[(int(s["x"]), int(s["y"]))] = s
    return by_tile


def factory_stores(view: WorldView, mates: set[str], site: tuple[int, int], radius: int) -> list[dict[str, Any]]:
    """Storehouses of team members within the works' radius, nearest the site first."""
    stores = [s for where, s in _team_stores(view, mates).items() if chebyshev(where, site) <= radius]
    return sorted(stores, key=lambda s: chebyshev((int(s["x"]), int(s["y"])), site))


def depots(view: WorldView, mates: set[str], site: tuple[int, int], radius: int) -> list[dict[str, Any]]:
    """Storehouses of team members beyond the works' radius: the field depots on the holdings."""
    return [s for where, s in _team_stores(view, mates).items() if chebyshev(where, site) > radius]


def stock_levels(stores: list[dict[str, Any]], wanted: dict[str, int]) -> dict[str, tuple[int, int]]:
    """Per kind: what the stores in view hold against the stock target."""
    held: Counter[str] = Counter()
    for s in stores:
        storage = s.get("storage") if isinstance(s.get("storage"), dict) else {}
        for item, qty in storage.items():
            held[str(item)] += int(qty or 0)
    return {kind: (held.get(kind, 0), int(target or 0)) for kind, target in wanted.items()}


def shortest_first(levels: dict[str, tuple[int, int]]) -> list[str]:
    return [k for k, _ in sorted(levels.items(), key=lambda kv: (kv[1][0] / kv[1][1] if kv[1][1] else 1.0, kv[0]))]


def office_claims(view: WorldView, claims: dict[str, Any] | None, tick: int) -> list[dict[str, Any]]:
    """The registrar's holdings as the hands see them, from the public snapshot (empty without a map or a registrar)."""
    if not claims or not claims.get("registrar") or not view.full_map:
        return []
    structures = view.world_structures or view.structures
    resources = view.world_resources or view.resources
    return office_holdings(claims, structures, view.terrain, resources, view.residents, tick, str(claims["registrar"]))


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
    floor_default = int(cfg["floor"]) if cfg.get("floor") is not None else NODE_FLOOR
    claims = cfg.get("claims") if isinstance(cfg.get("claims"), dict) else None
    held = office_claims(view, claims, tick) if claims else []
    ranks = {str(h["lot"]): int(h.get("rank", 0) or 0) for h in held}
    structures_all = view.world_structures or view.structures
    registrar = str((claims or {}).get("registrar") or "")

    def floor_for(node: tuple[int, int]) -> int:
        if claims and lot_id(*node) in ranks:
            return node_floor(claims, node, structures_all, registrar, default=floor_default)
        return floor_default

    field = depots(view, mates, site, radius) if claims else []
    drop_points = [*stores, *field] if role != "hauler" else stores

    # a. far from the works: walk there first
    distance = chebyshev(position, site)
    if distance > reach:
        target = _step_toward(position, {"x": site[0], "y": site[1]}, view)
        if target is not None and target != position:
            return [{"action": "move", "x": target[0], "y": target[1]}], f"{distance} tiles from the works at {site}: walk there", "crew"
        return None

    # b. a heavy pack goes to the nearest store of ours with room (the mason carries its materials to the site instead)
    heavy = pack >= 46 if role == "mason" else (goods >= HEAVY or pack >= 46)
    if heavy and drop_points:
        step = _unload(inventory, position, view, drop_points, room, state, tick, pack)
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
        return _gather_toward(persona, team, list(dict.fromkeys(wanted)), inventory, position, view, site, reach, room, teammates, "for the first store", floor_for, ranks)

    # d. hungry beside a store that holds berries: eat from the crew's own stock
    if inventory.get("berries", 0) < HUNGRY and energy < reserve + 15:
        for s in drop_points:
            where = (int(s["x"]), int(s["y"]))
            storage = s.get("storage") if isinstance(s.get("storage"), dict) else {}
            if chebyshev(position, where) <= 1 and int(storage.get("berries", 0) or 0) >= 5:
                qty = min(10, int(storage["berries"]), 50 - pack)
                if qty >= 1:
                    return [{"action": "take", "x": where[0], "y": where[1], "item": "berries", "qty": qty}], f"{inventory.get('berries', 0)} berries left and energy {energy}: take {qty} from the store at {where}", "crew"

    # e. the role's own work
    if role == "mason":
        if claims and held and int(claims.get("depots", 0) or 0) > 0:
            step = _depot_step(persona, team, claims, held, inventory, position, view, mates, site, reach, room, teammates, floor_for, ranks)
            if step is not None:
                return step
        return _mason(persona, team, cfg, inventory, position, view, stores, site, radius, reach, room, teammates, observe, floor_for, ranks)
    if role == "hauler":
        step = _haul(persona, cfg, inventory, position, view, stores, field, collective_names, mates, pack, observe, state, tick)
        if step is not None:
            return step
    wanted = list(ROLE_WANTED.get(role, []))
    if role == "hauler":
        levels = stock_levels(stores, cfg.get("stock") or {})
        wanted = [k for k in shortest_first(levels) if k in {"wood", "stone", "ore", "fiber", "berries"}] or wanted
    return _gather_toward(persona, team, wanted, inventory, position, view, site, reach, room, teammates, "for the works", floor_for, ranks)


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


def _lot_tile(position: tuple[int, int], view: WorldView, lid: str) -> tuple[int, int] | None:
    """A free walkable tile beside the builder inside the lot."""
    x0, y0, x1, y1 = lot_bounds(lid)
    options = [t for t in neighbours(*position) if x0 <= t[0] <= x1 and y0 <= t[1] <= y1 and view.free_tile(*t)]
    options.sort()
    return options[0] if options else None


def _depot_step(
    persona: Persona,
    team: Team | None,
    claims: dict[str, Any],
    held: list[dict[str, Any]],
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    mates: set[str],
    site: tuple[int, int],
    reach: int,
    room: int,
    teammates: dict[str, tuple[int, int]] | None,
    floor_for: FloorFor,
    ranks: dict[str, int],
) -> Step | None:
    """A depot (a storehouse, faction policy) on each of the best holdings that has none, in the office's order."""
    stores = _team_stores(view, mates)
    for holding in held[: int(claims.get("depots", 0) or 0)]:
        lid = str(holding["lot"])
        x0, y0, x1, y1 = lot_bounds(lid)
        if any(x0 <= wx <= x1 and y0 <= wy <= y1 for wx, wy in stores):
            continue
        anchor = tuple(holding.get("anchor") or (0, 0))
        if materials_ok(inventory, "storehouse"):
            if chebyshev(position, anchor) <= 3:
                tile = _lot_tile(position, view, lid)
                if tile is not None:
                    return (
                        [{"action": "build", "type": "storehouse", "x": tile[0], "y": tile[1], "policy": "faction"}],
                        f"holding {lid} (rank {holding.get('rank')}) has no depot: raise one at {tile}, paid from the pack",
                        "crew",
                    )
            target = _step_toward(position, {"x": anchor[0], "y": anchor[1]}, view)
            if target is not None and target != position:
                return [{"action": "move", "x": target[0], "y": target[1]}], f"the depot's cost is in the pack: walk to holding {lid} at {anchor}", "crew"
            return None
        missing = shortfall(inventory, "storehouse")
        wanted = [k for k, _ in sorted(missing.items(), key=lambda kv: -kv[1])]
        return _gather_toward(persona, team, wanted, inventory, position, view, site, reach, room, teammates, f"for the depot on {lid}", floor_for, ranks)
    return None


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
    floor_for: FloorFor | None = None,
    ranks: dict[str, int] | None = None,
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
    return _gather_toward(persona, team, wanted, inventory, position, view, site, reach, room, teammates, f"for the {kind}", floor_for, ranks)


def _haul(
    persona: Persona,
    cfg: dict[str, Any],
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    stores: list[dict[str, Any]],
    field: list[dict[str, Any]],
    collective_names: set[str] | None,
    mates: set[str],
    pack: int,
    observe: dict[str, Any],
    state: PersonaState | None = None,
    tick: int = 0,
) -> Step | None:
    """Beside a source (an open store of the collective, or a depot of the team): take what the stock is shortest of; else walk to the nearest depot."""
    if pack >= 40:
        return None
    you = observe.get("you") or {}
    faction = you.get("faction")
    faction_name = str(faction.get("name") if isinstance(faction, dict) else faction or "")
    site_tiles = {(int(s["x"]), int(s["y"])) for s in stores}
    collective = {n.casefold() for n in (collective_names or set())} | mates
    levels = stock_levels(stores, cfg.get("stock") or {})
    order = shortest_first(levels)
    empty = _empty_depots(state, tick)
    sources = [s for s in view.structures if s.get("type") == "storehouse" and (int(s["x"]), int(s["y"])) not in site_tiles and str(s.get("owner", "")).casefold() in collective]
    for s in sources:
        where = (int(s["x"]), int(s["y"]))
        if chebyshev(position, where) > 1:
            continue
        policy = str(s.get("policy") or "private")
        owner = str(s.get("owner", "")).casefold()
        admits = owner == persona.name.casefold() or policy == "public" or (policy == "faction" and faction_name and str(s.get("faction") or "").casefold() == faction_name.casefold())
        if not admits:
            continue
        storage = s.get("storage") if isinstance(s.get("storage"), dict) else {}
        for kind in order:
            held, target = levels.get(kind, (0, 0))
            if target and held >= target:
                continue
            qty = min(int(storage.get(kind, 0) or 0), 50 - pack, 20)
            if qty >= 5:
                return [{"action": "take", "x": where[0], "y": where[1], "item": kind, "qty": qty}], f"the works is short of {kind} ({held} of {target}): take {qty} from the store at {where}", "crew"
        if isinstance(s.get("storage"), dict) and where in {(int(d["x"]), int(d["y"])) for d in field}:
            _mark_empty(state, where, tick)  # a depot with nothing worth carrying: left alone for a while
    if pack < 20 and field:
        for depot in sorted(field, key=lambda d: chebyshev(position, (int(d["x"]), int(d["y"])))):
            where = (int(depot["x"]), int(depot["y"]))
            if where in empty or chebyshev(position, where) <= 1 or chebyshev(position, where) > CARRY_RANGE:
                continue
            target = _step_toward(position, {"x": where[0], "y": where[1]}, view)
            if target is not None and target != position:
                return [{"action": "move", "x": target[0], "y": target[1]}], f"the pack is light: walk to the depot at {where} for a load", "crew"
    return None


def _empty_depots(state: PersonaState | None, tick: int) -> set[tuple[int, int]]:
    flags = state.flags.get("empty_depots") if state is not None and isinstance(state.flags.get("empty_depots"), dict) else {}
    return {tuple(int(v) for v in k.split(",")) for k, seen in flags.items() if tick - int(seen or 0) <= EMPTY_DEPOT_TICKS}


def _mark_empty(state: PersonaState | None, where: tuple[int, int], tick: int) -> None:
    if state is None:
        return
    flags = state.flags.get("empty_depots") if isinstance(state.flags.get("empty_depots"), dict) else {}
    flags[f"{where[0]},{where[1]}"] = tick
    state.flags["empty_depots"] = dict(sorted(flags.items(), key=lambda kv: -int(kv[1] or 0))[:8])


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
    floor_for: FloorFor | None = None,
    ranks: dict[str, int] | None = None,
) -> Step | None:
    """Gather a wanted kind from the node nearest the works (clearing from the site outward), or in claims mode from the best holding first; else walk toward one."""
    if sum(inventory.values()) >= 46 or not wanted:
        return None
    rank = {k: i for i, k in enumerate(wanted)}
    floors: FloorFor = floor_for or (lambda node: NODE_FLOOR)

    def lot_rank(where: tuple[int, int]) -> int:
        return ranks.get(lot_id(*where), FAR_RANK) if ranks else 0

    def usable(r: dict[str, Any]) -> bool:
        if str(r.get("kind")) not in rank:
            return False
        where = (int(r["x"]), int(r["y"]))
        return int(r.get("amount", 0) or 0) > floors(where) and chebyshev(site, where) <= reach

    def order(r: dict[str, Any]) -> tuple[int, int, int, int]:
        where = (int(r["x"]), int(r["y"]))
        return (lot_rank(where), rank[str(r["kind"])], chebyshev(site, where) if not ranks else 0, chebyshev(position, where))

    in_view = {(int(r["x"]), int(r["y"])): r for r in view.resources if usable(r)}
    for where, node in sorted(in_view.items(), key=lambda kv: order(kv[1])):
        if ranks and chebyshev(position, where) <= 1 and lot_id(*where) in ranks:
            return [{"action": "gather", "kind": str(node["kind"])}], f"{node['kind']} at {where} beside me {why}: take five, leave {floors(where)}", "crew"  # claims mode: never walk away from a holding's node beside us
    nodes = sorted(in_view.values(), key=order)
    if ranks:
        # claims mode: the best holding first wherever it lies, so a far ore seam outranks the stone beside the vault
        afar = {(int(r["x"]), int(r["y"])): r for r in view.world_resources if usable(r)}
        nodes = sorted({**afar, **in_view}.values(), key=order)
    tried = 0
    for node in nodes:
        where = (int(node["x"]), int(node["y"]))
        kind = str(node["kind"])
        if chebyshev(position, where) <= 1:
            return [{"action": "gather", "kind": kind}], f"{kind} at {where} beside me {why}: take five, leave {floors(where)}", "crew"
        if where in in_view:
            if room < 2:
                continue
            stand = _adjacent_stand(where, position, view, persona, team, teammates)
            if stand is not None and stand != position:
                return [{"action": "move", "x": stand[0], "y": stand[1]}, {"action": "gather", "kind": kind}], f"walk to {stand} and gather {kind} at {where} {why}", "crew"
            continue
        tried += 1
        if tried > 6:
            break
        target = _step_toward(position, {"x": where[0], "y": where[1]}, view)
        if target is not None and target != position:
            lot = f" (holding {lot_id(*where)})" if ranks and lot_id(*where) in ranks else ""
            return [{"action": "move", "x": target[0], "y": target[1]}], f"toward the {node['kind']} at {where}{lot} {why}", "crew"
    if not ranks:
        far = sorted((r for r in view.world_resources if usable(r)), key=order)
        for node in far[:6]:
            where = (int(node["x"]), int(node["y"]))
            target = _step_toward(position, {"x": where[0], "y": where[1]}, view)
            if target is not None and target != position:
                return [{"action": "move", "x": target[0], "y": target[1]}], f"toward the {node['kind']} at {where} {why}", "crew"
    return None


__all__ = ["ROLE_WANTED", "depots", "factory_stores", "office_claims", "pipeline_of", "plan_crew", "shortest_first", "stock_levels"]
