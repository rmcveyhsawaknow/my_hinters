"""Lots: the land office's unit of sale, a 5 by 5 block inside the 10 by 10 plots.

Lot ids read ``F05-NW``: the plot (column letter by x, row by y) and the quadrant. The lot grid
is 26 by 26 (the last column and row are narrower), 676 lots in all. A lot is free when no
structure stands in it; staking a lot means one sign on its anchor tile (the centre), the
cheapest claim the world allows, and the price of a lot rises as free lots run out.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

LOT = 5
WALKABLE = set("sgfh")
WORLD = 128
COLUMNS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
QUADRANTS = ("NW", "NE", "SW", "SE")
GRID = math.ceil(WORLD / LOT)  # 26 lot columns and rows


def lot_grid(x: int, y: int) -> tuple[int, int]:
    return int(x) // LOT, int(y) // LOT


def lot_id_from_grid(lx: int, ly: int) -> str:
    return f"{COLUMNS[lx // 2]}{ly // 2:02d}-{QUADRANTS[(ly % 2) * 2 + lx % 2]}"


def lot_id(x: int, y: int) -> str:
    """(67, 56) lies in plot G05, north-east quadrant: G05-NE."""
    return lot_id_from_grid(*lot_grid(x, y))


def lot_grid_of(lid: str) -> tuple[int, int]:
    plot, quadrant = lid.split("-")
    col, row = COLUMNS.index(plot[0].upper()), int(plot[1:])
    q = QUADRANTS.index(quadrant.upper())
    return col * 2 + q % 2, row * 2 + q // 2


def lot_bounds(lid: str) -> tuple[int, int, int, int]:
    lx, ly = lot_grid_of(lid)
    x0, y0 = lx * LOT, ly * LOT
    return x0, y0, min(x0 + LOT - 1, WORLD - 1), min(y0 + LOT - 1, WORLD - 1)


def lot_anchor(lid: str) -> tuple[int, int]:
    """The tile a claim sign goes on: the lot's centre."""
    x0, y0, x1, y1 = lot_bounds(lid)
    return (x0 + x1) // 2, (y0 + y1) // 2


def all_lots() -> list[str]:
    return [lot_id_from_grid(lx, ly) for ly in range(GRID) for lx in range(GRID)]


def total_lots() -> int:
    return GRID * GRID


def occupied_lots(structures: list[dict[str, Any]]) -> set[str]:
    return {
        lot_id(s["x"], s["y"]) for s in structures
        if isinstance(s, dict) and isinstance(s.get("x"), int) and isinstance(s.get("y"), int)
    }


def free_lots(structures: list[dict[str, Any]]) -> set[str]:
    return set(all_lots()) - occupied_lots(structures)


def homestead_ring(structures: list[dict[str, Any]], exclude_owner: str) -> set[str]:
    """Lots holding another agent's hut, plus the ring of lots around each: the office leaves homesteads room."""
    ring: set[str] = set()
    for s in structures:
        if not isinstance(s, dict) or s.get("type") != "hut" or str(s.get("owner", "")).casefold() == exclude_owner.casefold():
            continue
        if not isinstance(s.get("x"), int) or not isinstance(s.get("y"), int):
            continue
        lx, ly = lot_grid(s["x"], s["y"])
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if 0 <= lx + dx < GRID and 0 <= ly + dy < GRID:
                    ring.add(lot_id_from_grid(lx + dx, ly + dy))
    return ring


def lot_price(free_share: float, base: int = 5, cap: int = 50, value: float = 0.0) -> int:
    """Price of one lot: the base while land is plentiful, rising as free lots run out, never above the cap.

    With half the lots free a lot costs twice the base; with a tenth free, ten times; the cap keeps it
    inside what one give can deliver (50). ``value`` is the lot's worth from ``lot_value`` (0 for plain
    sand with nothing near): every three points of worth add the base again, so ore-rich land with a
    mountain view and neighbours costs four or five times what basic sand does at the same scarcity.
    """
    share = max(min(float(free_share), 1.0), 0.0)
    worth = 1.0 + max(0.0, float(value)) / 3.0
    return int(max(base, min(cap, round(base * worth / max(share, base / cap)))))


WATER = set("wW")
RESOURCE_WORTH = {"ore": 3.0, "stone": 1.5, "wood": 1.0, "fiber": 0.5, "berries": 0.5}
VENUE_TYPES = {"hut", "storehouse", "tower", "monument", "farm", "bridge", "wall"}
DAY = 8640  # ticks in a real day


def _chebyshev(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def terrain_lookup(world: dict[str, Any]) -> Callable[[int, int], str | None]:
    """A ``terrain(x, y)`` function over the public map (a 16384-character string or a list of rows)."""
    raw = world.get("terrain")
    width = int(world.get("width", WORLD) or WORLD)
    if isinstance(raw, str):
        rows = [raw[i * width:(i + 1) * width] for i in range(len(raw) // width)]
    elif isinstance(raw, list):
        rows = [str(r) for r in raw]
    else:
        rows = []

    def terrain(x: int, y: int) -> str | None:
        if 0 <= y < len(rows) and 0 <= x < len(rows[y]):
            return rows[y][x]
        return None

    return terrain


def lot_tiles(lid: str) -> list[tuple[int, int]]:
    x0, y0, x1, y1 = lot_bounds(lid)
    return [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]


def adjacent_lots(lid: str) -> list[str]:
    lx, ly = lot_grid_of(lid)
    out = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = lx + dx, ly + dy
        if 0 <= nx < GRID and 0 <= ny < GRID:
            out.append(lot_id_from_grid(nx, ny))
    return out


def lot_value(
    lid: str,
    terrain: Callable[[int, int], str | None],
    resources: list[dict[str, Any]],
    structures: list[dict[str, Any]],
    residents: list[dict[str, Any]],
    tick: int,
    exclude_owner: str | None = None,
) -> dict[str, Any]:
    """What a lot is worth, as the land office sees it: resources, vista, venues and demand.

    Ore nodes within two tiles count most (3 each), stone 1.5, wood 1, fiber and berries half; water
    along the edge is a river view (coast when the lot is mostly shore) and mountains within three tiles
    a mountain view; other residents' structures within ten tiles are venues, and residents seen within
    two days within fifteen tiles are demand. A lot with fewer than fifteen buildable tiles is worth
    nothing to build on.
    """
    x0, y0, x1, y1 = lot_bounds(lid)
    centre = lot_anchor(lid)
    tiles = lot_tiles(lid)
    buildable = sum(1 for t in tiles if (terrain(*t) or "") in WALKABLE)
    tags: list[str] = []
    found: dict[str, int] = {}
    resource_score = 0.0
    for node in resources:
        if not isinstance(node, dict) or int(node.get("amount", 0) or 0) < 4:
            continue
        nx, ny = int(node.get("x", -99)), int(node.get("y", -99))
        if x0 - 2 <= nx <= x1 + 2 and y0 - 2 <= ny <= y1 + 2:
            kind = str(node.get("kind", ""))
            found[kind] = found.get(kind, 0) + 1
            resource_score += RESOURCE_WORTH.get(kind, 0.5)
    resource_score = min(resource_score, 6.0)
    if found.get("ore"):
        tags.append("ore-rich")
    if found.get("stone"):
        tags.append("stone near")
    if found.get("wood"):
        tags.append("timber")
    edge = [(x, y) for y in range(y0 - 1, y1 + 2) for x in range(x0 - 1, x1 + 2) if not (x0 <= x <= x1 and y0 <= y <= y1)]
    water_edge = sum(1 for t in edge if (terrain(*t) or "") in WATER)
    vista = 0.0
    if water_edge >= 8:
        vista += 2.0
        tags.append("coast")
    elif water_edge >= 3:
        vista += 1.0
        tags.append("river view")
    mountains = sum(1 for y in range(y0 - 3, y1 + 4) for x in range(x0 - 3, x1 + 4) if terrain(x, y) == "m")
    if mountains:
        vista += 1.0
        tags.append("mountain view")
    if sum(1 for t in tiles if terrain(*t) == "h") >= 5:
        vista += 0.5
        tags.append("high ground")
    venues = 0
    for s in structures:
        if not isinstance(s, dict) or s.get("type") not in VENUE_TYPES:
            continue
        if exclude_owner and str(s.get("owner", "")).casefold() == exclude_owner.casefold():
            continue
        if _chebyshev(centre, (int(s.get("x", -99)), int(s.get("y", -99)))) <= 10:
            venues += 1
    venue_score = min(venues * 0.3, 2.0)
    if venues >= 3:
        tags.append("near venues")
    demand = 0
    for a in residents:
        if not isinstance(a, dict) or not isinstance(a.get("x"), int) or not isinstance(a.get("y"), int):
            continue
        if tick - int(a.get("last_seen_tick", 0) or 0) > 2 * DAY:
            continue
        if exclude_owner and str(a.get("name", "")).casefold() == exclude_owner.casefold():
            continue
        if _chebyshev(centre, (a["x"], a["y"])) <= 15:
            demand += 1
    demand_score = min(demand * 0.5, 1.5)
    if demand >= 2:
        tags.append("in demand")
    score = resource_score + vista + venue_score + demand_score
    if buildable < 15:
        score = 0.0
        tags = ["unbuildable"]
    return {"lot": lid, "centre": centre, "score": round(score, 2), "tags": tags, "buildable": buildable, "resources": found, "water_edge": water_edge, "venues": venues, "demand": demand}


def site_search(
    request: dict[str, Any],
    terrain: Callable[[int, int], str | None],
    resources: list[dict[str, Any]],
    structures: list[dict[str, Any]],
    residents: list[dict[str, Any]],
    tick: int,
    *,
    registrar: str | None = None,
    exclude: set[str] | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """The best free lots for a client's brief: buildable, expandable into free neighbours, near what
    the brief names, with the resources it wants; each with its worth, its reasons and its price input."""
    free = free_lots(structures) - set(exclude or ())
    if registrar:
        free -= homestead_ring(structures, registrar)
    wants = [str(w) for w in request.get("wants", [])]
    out: list[dict[str, Any]] = []
    for lid in free:
        value = lot_value(lid, terrain, resources, structures, residents, tick, exclude_owner=registrar)
        if value["buildable"] < int(request.get("min_buildable", 20)):
            continue
        expandable = [n for n in adjacent_lots(lid) if n in free]
        if len(expandable) < int(request.get("expandable", 0)):
            continue
        score = value["score"]
        reasons = list(value["tags"])
        for target in request.get("near", []) or []:
            if not isinstance(target, dict):
                continue
            distance = _chebyshev(value["centre"], (int(target["x"]), int(target["y"])))
            farthest = int(target.get("max", 40) or 40)
            if distance <= farthest:
                score += float(target.get("weight", 2)) * (1 - distance / farthest)
                reasons.append(f"{distance} tiles from {target.get('label', 'the mark')}")
        for kind in wants:
            if value["resources"].get(kind):
                score += 1.0
        prefer = request.get("prefer") or {}
        if isinstance(prefer, dict) and prefer.get("y_min") is not None and value["centre"][1] >= int(prefer["y_min"]):
            score += 1.0
            reasons.append("in the south")
        out.append({**value, "score": round(score, 2), "expandable": sorted(expandable), "reasons": reasons})
    out.sort(key=lambda v: (-v["score"], v["lot"]))
    return out[:limit]


WORLD_CENTRE = (64, 64)  # newcomers start near here; the guide asks that the spawn area is never stripped
HOLDING_TEXT = "Lot {lot}: land office holding ({tags}). Not for sale: its nodes are the office's stock, sold from the vault. A public record, not a wall."


def holdings(
    cfg: dict[str, Any] | None,
    structures: list[dict[str, Any]],
    terrain: Callable[[int, int], str | None],
    resources: list[dict[str, Any]],
    residents: list[dict[str, Any]],
    tick: int,
    registrar: str,
    sold: set[str] | frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """The office's holdings: its ``keep`` most valuable staked, unsold lots, plus (``always_ore``) every staked lot with ore within two tiles.

    Ranked by worth, then ore, then id; each row carries the lot, its score and tags, the anchor, the
    claim sign standing there, the ore count and a rank from one.
    """
    if not cfg:
        return []
    keep = int(cfg.get("keep", 0) or 0)
    staked = staked_lots(structures, registrar)
    rows: list[dict[str, Any]] = []
    for lid, sign in staked.items():
        if lid in sold:
            continue
        value = lot_value(lid, terrain, resources, structures, list(residents or []), tick, exclude_owner=registrar)
        rows.append({
            "lot": lid, "score": value["score"], "tags": list(value["tags"]), "anchor": lot_anchor(lid),
            "sign": sign, "ore": int((value.get("resources") or {}).get("ore", 0) or 0), "resources": dict(value.get("resources") or {}),
        })
    rows.sort(key=lambda r: (-r["score"], -r["ore"], r["lot"]))
    chosen = rows[:keep]
    if cfg.get("always_ore", True):
        seen = {r["lot"] for r in chosen}
        chosen.extend(r for r in rows[keep:] if r["ore"] > 0 and r["lot"] not in seen)
    for index, row in enumerate(chosen, start=1):
        row["rank"] = index
    return chosen


def holding_text(cfg: dict[str, Any] | None, entry: dict[str, Any], registrar: str) -> str:
    """What a holding's claim sign says once the claim is firm."""
    template = str((cfg or {}).get("text") or HOLDING_TEXT)
    tags = ", ".join(str(t) for t in (entry.get("tags") or [])[:3]) or "surveyed"
    return template.format(lot=entry["lot"], tags=tags, registrar=registrar)[:200]


def node_floor(cfg: dict[str, Any] | None, node: tuple[int, int], structures: list[dict[str, Any]], registrar: str, default: int = 5) -> int:
    """How low a node may be worked: the claims floor, except near the spawn and in other residents' homestead rings."""
    cfg = cfg or {}
    floor = int(cfg.get("floor", default) if cfg.get("floor") is not None else default)
    if _chebyshev(node, WORLD_CENTRE) <= int(cfg.get("protect_spawn", 12) or 0):
        return default
    if cfg.get("protect_homesteads", True) and lot_id(*node) in homestead_ring(structures, registrar):
        return default
    return floor


def staked_lots(structures: list[dict[str, Any]], registrar: str) -> dict[str, dict[str, Any]]:
    """Lot id -> the office's claim sign standing on it (a sign owned by the registrar whose text starts with 'Lot ')."""
    out: dict[str, dict[str, Any]] = {}
    for s in structures:
        if not isinstance(s, dict) or s.get("type") != "sign" or str(s.get("owner", "")).casefold() != registrar.casefold():
            continue
        if not str(s.get("text") or "").startswith("Lot ") or not isinstance(s.get("x"), int) or not isinstance(s.get("y"), int):
            continue
        out[lot_id(s["x"], s["y"])] = s
    return out


def stake_text(lid: str, registrar: str, price: int | None = None, tags: list[str] | tuple[str, ...] = ()) -> str:
    worth = (" " + ", ".join(tags[:3]).capitalize() + ".") if tags else ""
    cost = f" {price} wood." if price else ""
    return f"Lot {lid}: staked by {registrar} for the land office.{worth}{cost} For sale; buy through my posted goal or ask by whisper."[:200]


__all__ = [
    "GRID",
    "LOT",
    "adjacent_lots",
    "all_lots",
    "free_lots",
    "holding_text",
    "holdings",
    "homestead_ring",
    "lot_anchor",
    "lot_bounds",
    "lot_grid",
    "lot_grid_of",
    "lot_id",
    "lot_id_from_grid",
    "lot_price",
    "lot_tiles",
    "lot_value",
    "node_floor",
    "occupied_lots",
    "site_search",
    "stake_text",
    "staked_lots",
    "terrain_lookup",
    "total_lots",
]
