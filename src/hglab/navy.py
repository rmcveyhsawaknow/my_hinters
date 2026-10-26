"""The Admiralty's sea: the water around the island charted for the Navy (Fathomark), and its works.

What the world allows at sea (the guide, 2026-10): water is deep (``W``) or shallow (``w``); nobody walks on
either; a ``bridge`` (15 wood, 40 hp) stands only on shallow water and makes its tile walkable for everyone;
blocks never stand on water, even under a bridge; deep water takes nothing at all. The public 3D viewer draws
water below the land (``hglab.terrain3d``: shallow about -0.35, deep -1.1 and lower): those heights are the
chart's soundings, not ground to build on. So the Navy's sea is the shallow shelf: it sounds and charts the
coast all the way round, runs piers out to the edge of the deep, and lays causeways across bays and lakes
where a short bridge saves a long walk round.

``chart`` reads the public terrain once (cached per map): the coast, the shelf, waypoints round the island,
pier and causeway candidates. ``plan_step`` is the Navy's rules step for shifts and the suggestion its model
sees: build the next bridge of the current work when wood is in the pack and the builder stands beside it,
walk there when not, gather wood when the pack holds less than a bridge's cost, sign a finished work, and
otherwise sail on round the coast to the next uncharted waypoint. ``brief`` is the chart in words for the model.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

WALKABLE = set("sgfh")
BRIDGE_COST = 15
MAX_PIER = 8  # shallow tiles from the shore to the deep edge (the shelf runs up to 12 in places)
MAX_CAUSEWAY = 8  # shallow tiles between two shores
MIN_SAVING = 12  # a causeway must save at least this many steps of walking round
PIER_SPACING = 14  # piers at least this far apart, so the shelf is sounded all round
MAX_PIERS = 12
WAYPOINT_EVERY = 10  # coast tiles between charting waypoints
LAND_SEARCH = 90  # how far round a walk is searched before a causeway is judged worth it
SIGN_KEEP = 1  # wood kept for the sign that marks a finished work
CAUSEWAY_HEAD_START = 20  # a causeway serves everyone who walks: counted this many tiles nearer than a pier


@dataclass
class Work:
    id: str
    kind: str  # pier or causeway
    shore: tuple[int, int]  # the land tile it starts from
    tiles: list[tuple[int, int]]  # shallow tiles, in building order from the shore
    far: tuple[int, int]  # the tile beyond the last: the deep edge (pier) or the far shore (causeway)
    saves: int = 0  # steps of walking saved (causeway)


@dataclass
class Chart:
    width: int
    height: int
    terrain: str
    coast: list[tuple[int, int]] = field(default_factory=list)
    waypoints: list[tuple[int, int]] = field(default_factory=list)
    shallow: int = 0
    deep: int = 0
    lakes: int = 0
    works: list[Work] = field(default_factory=list)

    def at(self, x: int, y: int) -> str:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.terrain[y * self.width + x]
        return "W"


def _terrain(world_or_rows: Any) -> tuple[int, int, str]:
    if isinstance(world_or_rows, dict):
        terrain = world_or_rows["terrain"]
        text = terrain if isinstance(terrain, str) else "".join(terrain)
        return int(world_or_rows.get("width", 128)), int(world_or_rows.get("height", 128)), text
    rows = list(world_or_rows)
    return len(rows[0]), len(rows), "".join(rows)


def chart(world_or_rows: Any) -> Chart:
    """The chart of a map (a public world snapshot or terrain rows), cached per terrain."""
    width, height, text = _terrain(world_or_rows)
    return _chart(width, height, text)


@lru_cache(maxsize=2)
def _chart(width: int, height: int, text: str) -> Chart:
    c = Chart(width, height, text)
    c.shallow = text.count("w")
    c.deep = text.count("W")
    neighbours8 = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]
    c.coast = [(x, y) for y in range(height) for x in range(width) if c.at(x, y) in WALKABLE and any(c.at(x + dx, y + dy) in "wW" for dx, dy in neighbours8)]
    if c.coast:
        cx = sum(x for x, _ in c.coast) / len(c.coast)
        cy = sum(y for _, y in c.coast) / len(c.coast)
        ring = sorted(c.coast, key=lambda t: math.atan2(t[1] - cy, t[0] - cx))
        c.waypoints = ring[::WAYPOINT_EVERY]
    c.lakes = _lakes(c)
    c.works = _causeways(c) + _piers(c)
    return c


def _lakes(c: Chart) -> int:
    """Shallow bodies that touch no deep water: lakes and lagoons inside the island."""
    seen: set[tuple[int, int]] = set()
    lakes = 0
    for y in range(c.height):
        for x in range(c.width):
            if (x, y) in seen or c.at(x, y) != "w":
                continue
            queue, body, open_sea = deque([(x, y)]), 0, False
            seen.add((x, y))
            while queue:
                px, py = queue.popleft()
                body += 1
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = px + dx, py + dy
                        code = c.at(nx, ny)
                        if code == "W":
                            open_sea = True
                        elif code == "w" and (nx, ny) not in seen:
                            seen.add((nx, ny))
                            queue.append((nx, ny))
            lakes += 0 if open_sea else 1
    return lakes


def _piers(c: Chart) -> list[Work]:
    """Straight runs of shallows from the shore to the edge of the deep, spread round the island, the widest shelf first."""
    found: list[Work] = []
    for sx, sy in c.coast:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            tiles = []
            for k in range(1, MAX_PIER + 1):
                tx, ty = sx + dx * k, sy + dy * k
                if c.at(tx, ty) != "w":
                    break
                tiles.append((tx, ty))
            if tiles and c.at(tiles[-1][0] + dx, tiles[-1][1] + dy) == "W":
                found.append(Work("", "pier", (sx, sy), tiles, (tiles[-1][0] + dx, tiles[-1][1] + dy)))
    found.sort(key=lambda w: (-len(w.tiles), w.shore))  # the widest shelf first: the furthest soundings
    chosen: list[Work] = []
    for work in found:
        if all(max(abs(work.shore[0] - o.shore[0]), abs(work.shore[1] - o.shore[1])) >= PIER_SPACING for o in chosen):
            chosen.append(work)
        if len(chosen) >= MAX_PIERS:
            break
    for i, work in enumerate(chosen, start=1):
        work.id = f"pier-{i:02d}"
    return chosen


def _land_steps(c: Chart, a: tuple[int, int], b: tuple[int, int]) -> int:
    """Steps from a to b over walkable land (eight-way), searched to ``LAND_SEARCH``; beyond it counts as that far."""
    if a == b:
        return 0
    seen = {a: 0}
    queue = deque([a])
    while queue:
        cur = queue.popleft()
        d = seen[cur]
        if d >= LAND_SEARCH:
            continue
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nxt = (cur[0] + dx, cur[1] + dy)
                if nxt in seen or c.at(*nxt) not in WALKABLE:
                    continue
                if nxt == b:
                    return d + 1
                seen[nxt] = d + 1
                queue.append(nxt)
    return LAND_SEARCH + 1


def _causeways(c: Chart) -> list[Work]:
    """Straight runs of shallows between two shores where the walk round is long: the biggest saving first."""
    found: list[Work] = []
    for sx, sy in c.coast:
        for dx, dy in ((1, 0), (0, 1)):  # each crossing once: east and south from its western or northern shore
            tiles = []
            for k in range(1, MAX_CAUSEWAY + 1):
                tx, ty = sx + dx * k, sy + dy * k
                if c.at(tx, ty) != "w":
                    break
                tiles.append((tx, ty))
            if not tiles:
                continue
            far = (tiles[-1][0] + dx, tiles[-1][1] + dy)
            if c.at(*far) not in WALKABLE:
                continue
            saves = _land_steps(c, (sx, sy), far) - (len(tiles) + 1)
            if saves >= MIN_SAVING:
                found.append(Work("", "causeway", (sx, sy), tiles, far, saves))
    found.sort(key=lambda w: (-w.saves, len(w.tiles), w.shore))
    chosen: list[Work] = []
    for work in found:
        near = any(max(abs(work.shore[0] - o.shore[0]), abs(work.shore[1] - o.shore[1])) <= 3 for o in chosen)
        if not near:
            chosen.append(work)
    for i, work in enumerate(chosen, start=1):
        work.id = f"causeway-{i:02d}"
    return chosen


def bridges_of(structures: list[dict[str, Any]]) -> set[tuple[int, int]]:
    return {(int(s["x"]), int(s["y"])) for s in structures if isinstance(s, dict) and s.get("type") == "bridge" and isinstance(s.get("x"), int) and isinstance(s.get("y"), int)}


def taken_tiles(structures: list[dict[str, Any]]) -> set[tuple[int, int]]:
    return {(int(s["x"]), int(s["y"])) for s in structures if isinstance(s, dict) and s.get("type") != "bridge" and isinstance(s.get("x"), int) and isinstance(s.get("y"), int)}


def next_tile(work: Work, bridges: set[tuple[int, int]], taken: set[tuple[int, int]]) -> tuple[int, int] | None:
    """The first unbuilt tile of a work, or None when it is finished or blocked by someone's structure."""
    for tile in work.tiles:
        if tile in bridges:
            continue
        return None if tile in taken else tile
    return None


def finished(work: Work, bridges: set[tuple[int, int]]) -> bool:
    return all(t in bridges for t in work.tiles)


def _depth(ground: Any, tile: tuple[int, int]) -> float | None:
    if ground is None:
        return None
    return round(-ground.height_at(tile[0] + 0.5, tile[1] + 0.5), 2)


def sign_text(work: Work, ground: Any = None) -> str:
    head = _depth(ground, work.tiles[-1]) if work.tiles else None
    sounding = f", sounded {head} at the head" if head is not None else ""
    if work.kind == "pier":
        return f"{work.id.title()}: {len(work.tiles)} tiles of shallows to the deep{sounding}. Walk out and look. Charted by the Admiralty."[:200]
    return f"{work.id.title()}: {len(work.tiles)} tiles across the shallows, {work.saves} steps shorter than the walk round. Built by the Admiralty."[:200]


def _note(state: Any) -> dict[str, Any]:
    flags = state.flags if state is not None and isinstance(getattr(state, "flags", None), dict) else {}
    note = flags.get("navy") if isinstance(flags.get("navy"), dict) else {}
    flags["navy"] = note
    return note


def plan_step(
    persona: Any,
    state: Any,
    observe: dict[str, Any],
    view: Any,
    inventory: dict[str, int],
    position: tuple[int, int],
    room: int,
    ground: Any = None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """One step of the Navy's rules: build the next bridge, carry wood to it, sign a finished work, or chart on."""
    from hglab.planner import NODE_FLOOR, _step_toward, chebyshev

    if not persona.knobs.get("navy") or room < 1 or not view.full_map:
        return None
    c = chart(view.full_map)
    structures = list(view.world_structures or []) + list(view.structures or [])
    bridges, taken = bridges_of(structures), taken_tiles(structures)
    note = _note(state)
    wood = int(inventory.get("wood", 0) or 0)
    open_works = [w for w in c.works if next_tile(w, bridges, taken) is not None]
    open_works.sort(key=lambda w: (chebyshev(position, w.shore) - (CAUSEWAY_HEAD_START if w.kind == "causeway" else 0), w.id))  # the nearest work, a causeway counted 20 tiles nearer
    current = next((w for w in open_works if w.id == note.get("work")), None) or (open_works[0] if open_works else None)
    # 1. a finished work of ours gets its sign on the shore
    signed = {str(s) for s in note.get("signed") or []}
    for work in c.works:
        if work.id in signed or not finished(work, bridges) or wood < 1:
            continue
        spots = [t for t in [work.shore, *[(work.shore[0] + dx, work.shore[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]] if c.at(*t) in WALKABLE and t not in taken and t not in bridges]
        spot = next((t for t in spots if chebyshev(position, t) <= 1), None)
        if spot is not None:
            note["signed"] = sorted(signed | {work.id})[-24:]
            return [{"action": "build", "type": "sign", "x": spot[0], "y": spot[1], "text": sign_text(work, ground)}], f"{work.id} is finished: its sign goes on the shore at {spot}", "navy"
        if spots and chebyshev(position, work.shore) <= 12:
            target = _step_toward(position, {"x": spots[0][0], "y": spots[0][1]}, view)
            if target is not None and target != position:
                return [{"action": "move", "x": target[0], "y": target[1]}], f"{work.id} is finished: walk to its shore to sign it", "navy"
    # 2. the current work: build its next bridge, or carry wood to it
    if current is not None:
        note["work"] = current.id
        tile = next_tile(current, bridges, taken)
        if tile is not None and wood >= BRIDGE_COST:
            if chebyshev(position, tile) <= 1 and position != tile:
                return [{"action": "build", "type": "bridge", "x": tile[0], "y": tile[1]}], f"{current.id} ({current.kind}, {len(current.tiles)} tiles): the next bridge at {tile}, {BRIDGE_COST} wood from the pack", "navy"
            index = current.tiles.index(tile)
            stand = current.shore if index == 0 else current.tiles[index - 1]
            target = stand if chebyshev(position, stand) == 1 else _step_toward(position, {"x": stand[0], "y": stand[1]}, view)  # one step onto the last bridge: _step_toward calls a neighbour arrived
            if target is not None and target != position:
                return [{"action": "move", "x": target[0], "y": target[1]}], f"{current.id}: carry {wood} wood to {stand}, beside the next bridge at {tile}", "navy"
        if tile is not None and wood < BRIDGE_COST and sum(int(v) for v in inventory.values()) < 46:
            nodes = [r for r in (view.world_resources or view.resources or []) if r.get("kind") == "wood" and int(r.get("amount", 0) or 0) > NODE_FLOOR and isinstance(r.get("x"), int)]
            if nodes:
                node = min(nodes, key=lambda r: (chebyshev(position, (int(r["x"]), int(r["y"]))), chebyshev(tile, (int(r["x"]), int(r["y"])))))
                where = (int(node["x"]), int(node["y"]))
                if chebyshev(position, where) <= 1:
                    return [{"action": "gather", "kind": "wood"}], f"{current.id} needs {BRIDGE_COST} wood a bridge and the pack holds {wood}: gather at {where}", "navy"
                target = _step_toward(position, {"x": where[0], "y": where[1]}, view)
                if target is not None and target != position:
                    return [{"action": "move", "x": target[0], "y": target[1]}], f"{current.id} needs wood ({wood} of {BRIDGE_COST}): walk to the forest at {where}", "navy"
    # 3. chart on: the next waypoint round the coast
    if not c.waypoints:
        return None
    index = int(note.get("next", 0) or 0) % len(c.waypoints)
    if chebyshev(position, c.waypoints[index]) <= 2:
        index = (index + 1) % len(c.waypoints)
        note["charted"] = int(note.get("charted", 0) or 0) + 1
    note["next"] = index
    goal = c.waypoints[index]
    target = _step_toward(position, {"x": goal[0], "y": goal[1]}, view)
    if target is None or target == position:
        return None
    return [{"action": "move", "x": target[0], "y": target[1]}], f"charting the coast: waypoint {index + 1} of {len(c.waypoints)} at {goal} ({int(note.get('charted', 0) or 0)} sounded so far)", "navy"


def brief(world: dict[str, Any], position: tuple[int, int] | None, note: dict[str, Any] | None = None, ground: Any = None) -> str:
    """The chart in words for the Navy's model: the shelf, the works and their state, where the next one is."""
    from hglab.planner import chebyshev

    c = chart(world)
    structures = list(world.get("structures") or [])
    bridges, taken = bridges_of(structures), taken_tiles(structures)
    here = position or (c.coast[0] if c.coast else (64, 64))
    done = [w for w in c.works if finished(w, bridges)]
    blocked = [w for w in c.works if not finished(w, bridges) and next_tile(w, bridges, taken) is None]
    open_works = sorted((w for w in c.works if next_tile(w, bridges, taken) is not None), key=lambda w: (w.kind != "causeway", chebyshev(here, w.shore)))
    lines = [
        ("World rules at sea: nobody walks on water; a bridge (15 wood) stands only on shallow water and makes it walkable for everyone;"
        " blocks never stand on water; deep water takes nothing. The viewer's negative heights are soundings, not ground."),
        (f"The sea: {c.shallow} shallow tiles (the shelf) and {c.deep} deep; {len(c.coast)} coast tiles; {c.lakes} lake(s) inside the island;"
        f" {len(bridges)} bridge(s) stand in the world."),
        (f"Works charted: {sum(1 for w in c.works if w.kind == 'causeway')} causeway(s), {sum(1 for w in c.works if w.kind == 'pier')} pier(s);"
        f" {len(done)} finished, {len(blocked)} blocked by someone's structure."),
    ]
    for work in open_works[:4]:
        tile = next_tile(work, bridges, taken)
        built = sum(1 for t in work.tiles if t in bridges)
        extra = f", saves {work.saves} steps" if work.kind == "causeway" else f", deep water at {work.far}"
        depth = _depth(ground, work.tiles[-1])
        sounding = f", sounding {depth} at the head" if depth is not None else ""
        lines.append(f"- {work.id} {work.kind} from the shore at {work.shore}: {built}/{len(work.tiles)} built, next bridge at {tile}{extra}{sounding}; {chebyshev(here, work.shore)} tiles from you.")
    if c.waypoints:
        index = int((note or {}).get("next", 0) or 0) % len(c.waypoints)
        lines.append(f"Charting round the coast: waypoint {index + 1} of {len(c.waypoints)} next at {c.waypoints[index]}; {int((note or {}).get('charted', 0) or 0)} sounded so far.")
    return "\n".join(lines)


__all__ = ["BRIDGE_COST", "Chart", "Work", "bridges_of", "brief", "chart", "finished", "next_tile", "plan_step", "sign_text"]
