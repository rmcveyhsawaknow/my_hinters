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

from hglab.evict import (
    due_owners,
    evict_cfg,
    held_lots,
    intruders,
    load_shared,
    notice_ticks,
    policed_lots,
)
from hglab.lots import holdings as office_holdings
from hglab.lots import lot_anchor, lot_bounds, lot_id, node_floor
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
    full_agents,
    materials_ok,
    neighbours,
    reachable_storage,
    shortfall,
    storehouse_room,
    with_storage,
)
from hglab.walls import (
    WALL_COST,
    WALL_DRAW,
    WALL_ENERGY,
    blocked_near,
    no_wall,
    open_tiles,
    wall_lots,
    walls_cfg,
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
STORES_MAX = 6  # storehouses at the works before the hands stop raising more for a full stock (pipeline.stores_max)
OVERFLOW_ROOM = 25  # a store with less room than this counts as full for the next-store decision and is not worth a walk with a load
MASON_KEEP = {"wood": 20, "stone": 10, "fiber": 5}  # the mason unloads only what a storehouse, a farm or a hut will not need: the hands hand it the cost

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


def blueprint_depots(team: Team | None) -> set[tuple[int, int]]:
    """The depot tiles of the team's blueprint (``pipeline.blueprint``): stores there are the works' stores too."""
    cfg = pipeline_of(team)
    if not cfg or not cfg.get("blueprint"):
        return set()
    from hglab.factory import blueprint, root_of

    try:
        design, _steps, _index = blueprint(root_of(team), str(cfg["blueprint"]))
    except (OSError, ValueError):
        return set()
    return {(int(d["x"]), int(d["y"])) for d in design.get("depots") or []}


def factory_stores(view: WorldView, mates: set[str], site: tuple[int, int], radius: int, depots: set[tuple[int, int]] | None = None) -> list[dict[str, Any]]:
    """Storehouses of team members within the works' radius, nearest the site first."""
    stores = [s for where, s in _team_stores(view, mates).items() if chebyshev(where, site) <= radius or where in (depots or set())]
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
    crew_roles: dict[str, str] | None = None,
) -> Step | None:
    """One pipeline step for a crew member, or None when the role has nothing to do from here.

    ``crew_roles`` maps every crew persona's slug to its role, so a hand can find the mason when the
    works' stores are full and hand it the next store's cost.
    """
    cfg = pipeline_of(team)
    knob = persona.knobs.get("crew")
    if not cfg or not isinstance(knob, dict) or room < 1:
        return None
    role = str(knob.get("role") or "")
    site = (int(cfg["site"]["x"]), int(cfg["site"]["y"]))
    radius = int(cfg.get("radius", 7) or 7)
    reach = int(cfg.get("range", 16) or 16)
    mates = team_member_names(persona, team, names)
    stores = factory_stores(view, mates, site, radius, blueprint_depots(team))
    tick = int(view.tick or observe.get("tick", 0) or 0)
    full = _full_stores(state, tick)
    open_stores = [s for s in stores if (int(s["x"]), int(s["y"])) not in full and storehouse_room(s) >= OVERFLOW_ROOM]
    stores_max = int(cfg.get("stores_max", STORES_MAX) or STORES_MAX)
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
    office_stores = [*stores, *field]

    # a. far from the works: walk there first
    distance = chebyshev(position, site)
    if distance > reach:
        target = _step_toward(position, {"x": site[0], "y": site[1]}, view)
        if target is not None and target != position:
            return [{"action": "move", "x": target[0], "y": target[1]}], f"{distance} tiles from the works at {site}: walk there", "crew"
        return None

    # a1. the office's ground (owner, 2026-10-25): what outsiders built on a staked lot without buying it comes down once its notice ran out
    if claims and evict_cfg(claims) is not None:
        step = _evict_step(persona, team, claims, position, view, observe, room, energy, reserve, collective_names, tick)
        if step is not None:
            return step

    # a2. the office's walls (owner, 2026-10-25): every store full, the stone goes into walls on the staked lots
    if claims and walls_cfg(claims) is not None and office_stores and not any(_has_room(s, full) for s in office_stores):
        step = _wall_step(persona, claims, held, inventory, position, view, mates, office_stores, room, energy, reserve, state, tick, observe, team=team)
        if step is not None:
            return step

    # b. a heavy pack goes to the nearest store of ours with room (the mason carries its materials to the site instead)
    heavy = pack >= 46 if role == "mason" else (goods >= HEAVY or pack >= 46)
    if heavy and drop_points:
        step = _unload(inventory, position, view, drop_points, room, state, tick, pack, keep=MASON_KEEP if role == "mason" and stores else None)
        if step is not None:
            return step
        if stores and not open_stores and role != "mason":
            step = _hand_to_mason(persona, team, inventory, position, view, site, teammates, names, collective_names, crew_roles, stores_max, len(stores), full=full_agents(state, tick))
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
        step = _mason(persona, team, cfg, inventory, position, view, stores, site, radius, reach, room, teammates, observe, floor_for, ranks, stores_max=stores_max, open_stores=open_stores)
        if step is not None:
            return step
        return _blueprint(persona, team, state, observe, view, inventory, position, room, mates, site, reach, teammates, floor_for, ranks)
    if role == "hauler":
        step = _haul(persona, cfg, inventory, position, view, stores, field, collective_names, mates, pack, observe, state, tick)
        if step is not None:
            return step
    wanted = _role_wanted(role, stock_levels(stores, cfg.get("stock") or {}))
    return _gather_toward(persona, team, wanted, inventory, position, view, site, reach, room, teammates, "for the works", floor_for, ranks)


def _has_room(store: dict[str, Any], full: set[tuple[int, int]]) -> bool:
    """A store a load may still go into: not refused as full lately, and room to spare when its contents show."""
    where = (int(store["x"]), int(store["y"]))
    if where in full:
        return False
    return not isinstance(store.get("storage"), dict) or storehouse_room(store) >= OVERFLOW_ROOM


def _admits(persona: Persona, store: dict[str, Any], faction: str) -> bool:
    """Whether this agent may take from the store: its own, public, or its faction's."""
    policy = str(store.get("policy") or "private")
    theirs = store.get("faction")
    theirs = str(theirs.get("name") if isinstance(theirs, dict) else theirs or "")
    return str(store.get("owner", "")).casefold() == persona.name.casefold() or policy == "public" or (policy == "faction" and bool(faction) and theirs.casefold() == faction.casefold())


def _evict_step(
    persona: Persona,
    team: Team | None,
    claims: dict[str, Any],
    position: tuple[int, int],
    view: WorldView,
    observe: dict[str, Any],
    room: int,
    energy: int,
    reserve: int,
    collective_names: set[str] | None,
    tick: int,
) -> Step | None:
    """Take down what an outsider built on a staked lot of the office once the registrar's notice to them ran out (``hglab.evict``).

    Beside a target: hits on the weakest first (10 damage each), as many as the wake and the energy allow.
    Blocks within two tiles: removals of their tile's box, eight blocks a time. Else a walk toward the
    nearest. Where the view reaches it is the truth: a structure gone from it is gone, its hp is current.
    """
    from hglab.factory import root_of

    cfg = evict_cfg(claims)
    shared = load_shared(root_of(team))
    due = due_owners(shared, tick, notice_ticks(cfg))
    if not due:
        return None
    collective = {n.casefold() for n in (collective_names or set())} | {persona.name.casefold()}
    snapshot = view.world_structures or view.structures
    policed = policed_lots(claims, snapshot, held_lots(snapshot, str(claims["registrar"]), shared))
    if not policed:
        return None

    def in_view(x: int, y: int) -> bool:
        return bool(view.rows) and 0 <= y - view.y0 < len(view.rows) and 0 <= x - view.x0 < len(view.rows[y - view.y0])

    current = [s for s in snapshot if not (isinstance(s.get("x"), int) and isinstance(s.get("y"), int) and in_view(s["x"], s["y"]))] + list(view.structures)
    targets = [i for i in intruders(policed, current, collective) if i["owner"].casefold() in due]
    blocks = [
        b for b in (observe.get("blocks") or [])
        if isinstance(b, dict) and isinstance(b.get("x"), int) and isinstance(b.get("y"), int) and b.get("owner")
        and str(b["owner"]).casefold() not in collective and str(b["owner"]).casefold() in due and lot_id(b["x"], b["y"]) in policed
    ]
    if not targets and not blocks:
        return None
    spare = max(0, energy - reserve)
    beside = sorted((i for i in targets if chebyshev(position, (i["x"], i["y"])) <= 1), key=lambda i: (int(i.get("hp") or 10), i["x"], i["y"]))
    if beside:
        budget = min(room, spare // 5)
        if budget < 1:
            return None
        hits: list[dict[str, Any]] = []
        struck: list[str] = []
        for item in beside:
            need = max(1, -(-int(item.get("hp") or 10) // 10))
            take = min(need, budget - len(hits))
            hits.extend({"action": "demolish", "x": item["x"], "y": item["y"]} for _ in range(take))
            struck.append(f"{item['owner']}'s {item['type']} at ({item['x']},{item['y']})")
            if len(hits) >= budget:
                break
        return hits, f"lot {beside[0]['lot']} is staked ground of the office and the notice to its builder has run out: {len(hits)} hit(s) on {', '.join(struck)}", "crew"
    near = sorted((b for b in blocks if chebyshev(position, (b["x"], b["y"])) <= 2), key=lambda b: (b["x"], b["y"]))
    if near:
        b = near[0]
        top = max(1, min(16, int(b.get("top") or 16)))
        box = {"action": "remove", "bx": b["x"] * 4, "by": b["y"] * 4, "bz": 0, "bx2": b["x"] * 4 + 3, "by2": b["y"] * 4 + 3, "bz2": top - 1}
        cost = 1 + -(-(16 * top) // 32)  # as the planner counts a box: one, plus one per 32 cells
        count = min(room, spare // cost, max(1, -(-int(b.get("count") or 8) // 8)))
        if count < 1:
            return None
        return [dict(box) for _ in range(count)], f"{b['owner']}'s blocks at ({b['x']},{b['y']}) stand on staked lot {lot_id(b['x'], b['y'])} and the notice has run out: {count} removal(s), eight blocks each", "crew"
    spots = [(i["x"], i["y"], f"{i['owner']}'s {i['type']}") for i in targets] + [(b["x"], b["y"], f"{b['owner']}'s blocks") for b in blocks]
    spots = [s for s in spots if chebyshev(position, (s[0], s[1])) <= CARRY_RANGE]
    if not spots:
        return None
    x, y, what = min(spots, key=lambda s: (chebyshev(position, (s[0], s[1])), s[0], s[1]))
    target = _step_toward(position, {"x": x, "y": y}, view)
    if target is None or target == position:
        return None
    return [{"action": "move", "x": target[0], "y": target[1]}], f"{what} at ({x},{y}) stands on staked lot {lot_id(x, y)} and its notice has run out: walk there", "crew"


def _wall_step(
    persona: Persona,
    claims: dict[str, Any],
    held: list[dict[str, Any]],
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    mates: set[str],
    stores: list[dict[str, Any]],
    room: int,
    energy: int,
    reserve: int,
    state: PersonaState,
    tick: int,
    observe: dict[str, Any],
    team: Team | None = None,
) -> Step | None:
    """Every store of the office is full: wall the staked lots, the holdings first, with the pack's stone, then the stores'.

    Walls go on a lot's border, never on the middle tile of a side (the gate), never on a road, a sign, a
    node, a tile someone stands on or beside another resident's building (``hglab.walls``). The nearest
    open wall tiles first: beside us, every build the wake allows; else a walk toward the nearest. With
    no stone in the pack, a draw of up to thirty from the nearest full store that admits us.
    """
    structures = view.world_structures or view.structures
    from hglab.factory import root_of

    held_by = set(held_lots(structures, str(claims["registrar"]), load_shared(root_of(team)))) if evict_cfg(claims) is not None else set()
    first, rest = wall_lots(claims, held, structures, mates, held_by=held_by)
    if not first and not rest:
        return None
    skip = blocked_near([*view.world_structures, *view.structures], mates) | no_wall(state, tick)
    skip |= {(int(r["x"]), int(r["y"])) for r in (view.world_resources or view.resources) if isinstance(r.get("x"), int) and isinstance(r.get("y"), int)}
    skip |= {(int(a["x"]), int(a["y"])) for a in [*view.agents, *view.residents] if isinstance(a.get("x"), int) and isinstance(a.get("y"), int)}
    tiles: list[tuple[str, tuple[int, int]]] = []
    for tier in (first, rest):
        near = [lid for lid in tier if chebyshev(position, lot_anchor(lid)) <= CARRY_RANGE]
        tiles = [(lid, t) for lid in near for t in open_tiles(lid, view.free_tile, skip)]
        if tiles:
            break  # the holdings before the lots for sale
    if not tiles:
        return None
    stone = int(inventory.get("stone", 0) or 0)
    pack = sum(inventory.values())
    if stone >= WALL_COST:
        builds = min(room, stone // WALL_COST, max(0, (energy - reserve) // WALL_ENERGY))
        if builds < 1:
            return None  # too tired to build: rest first
        beside = sorted((pair for pair in tiles if pair[1] != position and chebyshev(position, pair[1]) <= 1), key=lambda pair: pair[1])
        if beside:
            chosen = beside[:builds]
            lots = ", ".join(sorted({lid for lid, _ in chosen}))
            return (
                [{"action": "build", "type": "wall", "x": t[0], "y": t[1]} for _, t in chosen],
                f"every store of the office is full: {len(chosen)} wall(s) on lot {lots} from the pack's {stone} stone, the middle of each side left open as a gate",
                "crew",
            )
        lid, target = min(tiles, key=lambda pair: (chebyshev(position, pair[1]), pair[1]))
        step = _step_toward(position, {"x": target[0], "y": target[1]}, view)
        if step is not None and step != position:
            return [{"action": "move", "x": step[0], "y": step[1]}], f"every store of the office is full: carry {stone} stone to lot {lid}, its wall ring open at {target}", "crew"
        return None
    if 50 - pack < 10:
        return None  # no room to carry stone: the pack's other goods wait for a store with room
    faction = (observe.get("you") or {}).get("faction")
    faction = str(faction.get("name") if isinstance(faction, dict) else faction or "")
    for store in sorted(stores, key=lambda s: chebyshev(position, (int(s["x"]), int(s["y"])))):
        storage = store.get("storage") if isinstance(store.get("storage"), dict) else None
        if not storage or int(storage.get("stone", 0) or 0) < 10 or not _admits(persona, store, faction):
            continue
        where = (int(store["x"]), int(store["y"]))
        if chebyshev(position, where) <= 1:
            qty = min(int(storage["stone"]), 50 - pack, WALL_DRAW)
            return [{"action": "take", "x": where[0], "y": where[1], "item": "stone", "qty": qty}], f"every store of the office is full: take {qty} stone from the store at {where} to wall the staked lots", "crew"
        if chebyshev(position, where) > CARRY_RANGE:
            continue
        step = _step_toward(position, {"x": where[0], "y": where[1]}, view)
        if step is not None and step != position:
            return [{"action": "move", "x": step[0], "y": step[1]}], f"every store of the office is full: walk to the store at {where} for stone to wall with", "crew"
    return None


def _blueprint(
    persona: Persona,
    team: Team | None,
    state: PersonaState,
    observe: dict[str, Any],
    view: WorldView,
    inventory: dict[str, int],
    position: tuple[int, int],
    room: int,
    mates: set[str],
    site: tuple[int, int],
    reach: int,
    teammates: dict[str, tuple[int, int]] | None,
    floor_for: FloorFor | None,
    ranks: dict[str, int] | None,
) -> Step | None:
    """The works stand: the mason raises the team's blueprint, and gathers what no store holds for it."""
    from hglab.factory import plan_step

    step = plan_step(persona, team, state, observe, view, inventory, position, room, mates=mates)
    if step is not None:
        return step
    need = getattr(state, "_bp_need", None)
    if need:
        return _gather_toward(persona, team, [str(need)], inventory, position, view, site, reach, room, teammates, f"for the blueprint's {need}", floor_for, ranks)
    return None


def _role_wanted(role: str, levels: dict[str, tuple[int, int]]) -> list[str]:
    """What a hand gathers: its own kinds, the one furthest below the stock target first; when all of its
    kinds stand at target and the works is short of another kind, that kind; the hauler takes the shortest of all.

    The stock targets set the mix, not a ceiling: with every kind at target the hands keep gathering in
    the stock's proportions until the stores are full, and then the mason raises another store.
    """
    kinds = {"wood", "stone", "ore", "fiber", "berries"}
    if role == "hauler":
        return [k for k in shortest_first(levels) if k in kinds] or list(ROLE_WANTED["hauler"])
    own = list(ROLE_WANTED.get(role, []))
    if not own:
        return own

    def ratio(kind: str) -> float:
        held, target = levels.get(kind, (0, 0))
        return held / target if target else (9.0 if held else 0.0)

    own.sort(key=ratio)
    short = [k for k in shortest_first(levels) if k in kinds and ratio(k) < 1.0]
    if ratio(own[0]) >= 1.0 and short:
        return [*short, *own]  # the works has enough of ours: fetch what it is short of
    return [*own, *[k for k in short if k not in own]]


def _hand_to_mason(
    persona: Persona,
    team: Team | None,
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    site: tuple[int, int],
    teammates: dict[str, tuple[int, int]] | None,
    names: dict[str, str] | None,
    collective_names: set[str] | None,
    crew_roles: dict[str, str] | None,
    stores_max: int,
    standing: int,
    full: set[str] | frozenset[str] = frozenset(),
) -> Step | None:
    """Every store at the works is full: the heavy pack carries the next store's cost to the mason, who raises it.

    A give to an agent reaches two tiles; the mason's position comes from the view or the public roster.
    With the works at its cap of stores, or the mason's pack full (``full``: it refused a hand-over
    within the hour), the hand waits by the site instead of wandering or handing again.
    """
    proper = {n.casefold(): n for n in (collective_names or set())}
    by_slug = {slug: proper.get(str(name).casefold(), str(name)) for name, slug in (names or {}).items()}
    masons = [slug for slug, role in (crew_roles or {}).items() if role == "mason" and (team is None or slug in team.members) and slug != persona.slug]
    where = None
    mason_name = ""
    for slug in masons:
        mason_name = by_slug.get(slug, "")
        seen = next((a for a in view.agents if mason_name and str(a.get("name", "")).casefold() == mason_name.casefold()), None)
        if seen is not None and isinstance(seen.get("x"), int) and isinstance(seen.get("y"), int):
            where = (int(seen["x"]), int(seen["y"]))
            break
        if teammates and slug in teammates:
            where = tuple(teammates[slug])
            break
    packed = bool(mason_name) and mason_name.casefold() in full
    if standing >= stores_max or where is None or not mason_name or packed:
        if chebyshev(position, site) > 3:
            target = _step_toward(position, {"x": site[0], "y": site[1]}, view)
            if target is not None and target != position:
                also = " and the mason's pack too" if packed else ""
                return [{"action": "move", "x": target[0], "y": target[1]}], f"every store at the works is full ({standing} of {stores_max}){also}: wait by the works", "crew"
        return None
    if chebyshev(position, where) <= 2:
        gives: list[dict[str, Any]] = []
        for item, qty in BLUEPRINTS["storehouse"].items():
            have = inventory.get(item, 0)
            if have >= 1:
                gives.append({"action": "give", "to": mason_name, "item": item, "qty": min(have, qty)})
        if not gives:
            return None
        what = ", ".join(f"{g['qty']} {g['item']}" for g in gives)
        return gives, f"every store at the works is full: hand {what} to the mason for the next store", "crew"
    if chebyshev(position, where) > CARRY_RANGE:
        return None
    target = _step_toward(position, {"x": where[0], "y": where[1]}, view)
    if target is not None and target != position:
        return [{"action": "move", "x": target[0], "y": target[1]}], f"every store at the works is full: carry the next store's cost to the mason at {where}", "crew"
    return None


def _unload(
    inventory: dict[str, int],
    position: tuple[int, int],
    view: WorldView,
    stores: list[dict[str, Any]],
    room: int,
    state: PersonaState,
    tick: int,
    pack: int,
    keep: dict[str, int] | None = None,
) -> Step | None:
    """Give the pack into the nearest store with room; ``keep`` holds back what the next build needs (the mason's case)."""
    full = _full_stores(state, tick)
    candidates = sorted(
        (s for s in stores if (int(s["x"]), int(s["y"])) not in full),
        key=lambda s: chebyshev(position, (int(s["x"]), int(s["y"]))),
    )
    for s in candidates:
        where = (int(s["x"]), int(s["y"]))
        known = isinstance(s.get("storage"), dict)
        if known and storehouse_room(s) < 5:
            _mark_full(state, where, tick)  # seen full from here: no walk to it
            continue
        if known and chebyshev(position, where) > 1 and storehouse_room(s) < OVERFLOW_ROOM:
            continue  # the last few slots are not worth the walk with a load; the mason raises another store
        if chebyshev(position, where) <= 1:
            space = storehouse_room(s)
            if space < 5:
                _mark_full(state, where, tick)
                continue
            gives: list[dict[str, Any]] = []
            for item in ("wood", "stone", "ore", "fiber", "berries"):
                held_back = BERRY_KEEP if item == "berries" else int((keep or {}).get(item, 0) or 0)
                qty = min(inventory.get(item, 0) - held_back, space)
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


def _works_goal(kind: str, position: tuple[int, int], view: WorldView, site: tuple[int, int], radius: int) -> tuple[int, int] | None:
    """The nearest free tile in the works where this blueprint fits (a farm wants grass), when none is beside the builder."""
    terrain_ok = {"g"} if kind == "farm" else None
    options = [
        (x, y)
        for x in range(site[0] - radius, site[0] + radius + 1)
        for y in range(site[1] - radius, site[1] + radius + 1)
        if chebyshev((x, y), position) > 1 and view.free_tile(x, y, terrain_ok)
    ]
    options.sort(key=lambda t: (chebyshev(position, t), chebyshev(t, site), t))
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
    stores_max: int = STORES_MAX,
    open_stores: list[dict[str, Any]] | None = None,
) -> Step | None:
    """The mason raises the plan's next piece beside a store that pays for it, or carries the cost to where the piece fits.

    A build pays from the pack first and then from storehouses within a tile that admit the builder
    (the guide), so standing by a store is enough when a fitting tile is beside it. A farm wants grass
    and the works stand on sand, so when no tile beside the store fits, the mason takes the shortfall
    into its pack and walks to a tile in the works that does. When every store is full the next piece
    is another storehouse, up to ``stores_max``, so the hands keep stockpiling.
    """
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
    if stores and open_stores is not None and not open_stores and len(stores) < stores_max:
        item = {"type": "storehouse", "count": len(stores) + 1}  # every store at the works is full: another one, so the hands keep stockpiling
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
            why = "every store at the works is full" if open_stores is not None and stores and not open_stores and kind == "storehouse" else f"the plan's next piece is a {kind} ({counts.get(kind, 0)} of {item.get('count', 1)} standing)"
            return [action], f"{why}: raise it at {tile}, paid from {paid}", "crew"
        if materials_ok(inventory, kind):
            goal = _works_goal(kind, position, view, site, radius)
            if goal is None:
                return None  # nothing in the works fits this blueprint: the planner's other steps take the wake
            target = _step_toward(position, {"x": goal[0], "y": goal[1]}, view)
            if target is not None and target != position:
                return [{"action": "move", "x": target[0], "y": target[1]}], f"materials for the {kind} in hand: walk to {goal} in the works, where it fits", "crew"
            return None
    beside = [s for s in stores if chebyshev(position, (int(s["x"]), int(s["y"]))) <= 1]
    lacking = shortfall(inventory, kind)
    if beside and lacking:
        takes: list[dict[str, Any]] = []
        pack_room = 50 - sum(inventory.values())
        for s in beside:
            held = s.get("storage") if isinstance(s.get("storage"), dict) else {}
            for kind_, qty in lacking.items():
                if int(held.get(kind_, 0) or 0) >= qty and pack_room >= qty and all(t["item"] != kind_ for t in takes):
                    takes.append({"action": "take", "x": int(s["x"]), "y": int(s["y"]), "item": kind_, "qty": qty})
                    pack_room -= qty
        if takes and len(takes) == len(lacking):
            what = ", ".join(f"{t['qty']} {t['item']}" for t in takes)
            return takes[: max(1, room)], f"the {kind} is next and no tile beside this store fits it: take {what} into the pack and carry it where it does", "crew"
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
            if where in {(int(d["x"]), int(d["y"])) for d in field}:
                _mark_empty(state, where, tick)  # not ours to take from: Drayhand paced between two private depots of the registrar's on 2026-10-25
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


__all__ = ["ROLE_WANTED", "blueprint_depots", "depots", "factory_stores", "office_claims", "pipeline_of", "plan_crew", "shortest_first", "stock_levels"]
