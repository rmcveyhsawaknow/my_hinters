"""Houses out of blocks (API 0.30): a plan for the walls, door, windows and roof around a hut.

Every tile is a 4 by 4 grid of block cells, 16 levels tall; tile (x, y) holds bx 4x..4x+3 and
by 4y..4y+3. One ``place`` fills one box (at most 256 cells, within 2 tiles of the builder) with
one material at one item per 4 blocks, and cells already filled are skipped free, so a plan can
be replayed step by step: the next step is the first whose cumulative block count the builder's
blocks on the footprint have not reached. A house is what people watching the site see of an
agent; the fixtures (hut, farm, storehouse) stay small inside it.
"""

from __future__ import annotations

import math
from typing import Any

MATERIAL_ITEM = {"wood": "wood", "stone": "stone", "thatch": "fiber", "metal": "ore"}
COLORS = (
    "natural", "white", "grey", "black", "brown", "red", "orange", "yellow", "lime", "green", "teal", "cyan", "blue",
    "indigo", "purple", "pink", "tan",
)


def tile_cells(x: int, y: int) -> tuple[int, int, int, int]:
    """Inclusive (bx0, by0, bx1, by1) of one tile."""
    return 4 * x, 4 * y, 4 * x + 3, 4 * y + 3


def footprint(hx: int, hy: int, size: int) -> tuple[int, int, int, int]:
    """Tiles (x0, y0, x1, y1) of a house of ``size`` by ``size`` tiles centred on the hut, kept inside the world."""
    half = (size - 1) // 2
    x0, y0 = max(0, hx - half), max(0, hy - half)
    x1, y1 = min(127, x0 + size - 1), min(127, y0 + size - 1)
    return x0, y0, x1, y1


def box(bx: int, by: int, bz: int, bx2: int | None = None, by2: int | None = None, bz2: int | None = None, **extra: Any) -> dict[str, Any]:
    action: dict[str, Any] = {"action": "place", "bx": bx, "by": by, "bz": bz}
    if bx2 is not None and bx2 != bx:
        action["bx2"] = bx2
    if by2 is not None and by2 != by:
        action["by2"] = by2
    if bz2 is not None and bz2 != bz:
        action["bz2"] = bz2
    action.update(extra)
    return action


def cells_of(action: dict[str, Any]) -> int:
    bx, by, bz = int(action["bx"]), int(action["by"]), int(action["bz"])
    bx2, by2, bz2 = int(action.get("bx2", bx)), int(action.get("by2", by)), int(action.get("bz2", bz))
    w, d, h = abs(bx2 - bx) + 1, abs(by2 - by) + 1, abs(bz2 - bz) + 1
    if action.get("fill") == "walls":
        return (w * d - max(w - 2, 0) * max(d - 2, 0)) * h
    return w * d * h


def house_plan(hx: int, hy: int, size: int = 1, color: str = "natural", style: str = "house") -> list[dict[str, Any]]:
    """The steps of a house around the hut at (hx, hy): door, windows, walls, roof.

    ``style`` ``factory`` is the Chocolate Factory: a 3 x 3 footprint with metal pillars and a double
    metal door, coloured stone walls, tall glowing windows on every side, a pitched thatch roof with a
    metal ridge, and one pillar raised to the glass elevator's height (``factory_plan``).

    ``size`` 1 wraps the hut's own tile (about 2 wood, 8 stone, 4 fiber); ``size`` 3 wraps the 3 by 3
    tiles around it (about 2 wood, 66 stone, 36 fiber). Each step is one ``place`` with its material,
    the blocks it adds and the items it costs; ``cumulative`` is the footprint's block count once the
    step is done, which is how progress is read from ``observe.blocks``.
    """
    if style == "factory":
        return factory_plan(hx, hy, color)
    size = 3 if int(size) >= 3 else 1
    color = color if color in COLORS else "natural"
    x0, y0, x1, y1 = footprint(hx, hy, size)
    bx0, by0, _, _ = tile_cells(x0, y0)
    _, _, bx1, by1 = tile_cells(x1, y1)
    width = bx1 - bx0 + 1
    levels = 3 if size == 1 else 6
    door_x = bx0 + width // 2
    door_top = 2 if size == 1 else 3
    steps: list[dict[str, Any]] = [
        {"name": "door", "action": box(door_x, by1, 0, bz2=door_top, material="wood", shape="door", facing="south")},
        {"name": "window", "action": box(bx0, by0 + width // 2 - 1, 0, by2=by0 + width // 2, bz2=2, material="wood", shape="window", facing="west")},  # from the ground: a placement must reach level 0 or touch a block
    ]
    if size == 1:
        steps.append({"name": "walls", "action": box(bx0, by0, 0, bx1, by1, levels - 1, material="stone", fill="walls")})
    else:
        steps.append({"name": "lower walls", "action": box(bx0, by0, 0, bx1, by1, 2, material="stone", fill="walls")})
        steps.append({"name": "upper walls", "action": box(bx0, by0, 3, bx1, by1, 5, material="stone", fill="walls")})
    steps.append({"name": "roof", "action": box(bx0, by0, levels, bx1, by1, material="thatch", shape="slab", color=color)})
    placed = 0
    skip = 0  # openings already filled by the door and window steps are skipped by the wall boxes
    for step in steps:
        cells = cells_of(step["action"])
        if step["name"] in {"walls", "lower walls"}:
            cells -= skip
        if step["name"] in {"door", "window"}:
            skip += cells
        step["cells"] = max(cells, 0)
        step["items"] = math.ceil(step["cells"] / 4)
        step["item"] = MATERIAL_ITEM[step["action"]["material"]]
        step["energy"] = 1 + math.ceil(step["cells"] / 32)
        placed += step["cells"]
        step["cumulative"] = placed
    return steps


ROOF_OF = {"purple": "pink", "pink": "purple", "red": "orange", "orange": "yellow", "yellow": "orange", "brown": "red", "green": "lime", "lime": "green", "teal": "cyan", "cyan": "teal", "blue": "indigo", "indigo": "blue", "tan": "brown", "grey": "red", "white": "red", "black": "grey", "natural": "red"}


def _box_cells(action: dict[str, Any]) -> set[tuple[int, int, int]]:
    """Every cell a place action covers, before the world skips the filled ones."""
    bx, by, bz = int(action["bx"]), int(action["by"]), int(action["bz"])
    bx2, by2, bz2 = int(action.get("bx2", bx)), int(action.get("by2", by)), int(action.get("bz2", bz))
    xs, ys, zs = range(min(bx, bx2), max(bx, bx2) + 1), range(min(by, by2), max(by, by2) + 1), range(min(bz, bz2), max(bz, bz2) + 1)
    if action.get("fill") == "walls":
        return {(x, y, z) for x in xs for y in ys for z in zs if x in (xs[0], xs[-1]) or y in (ys[0], ys[-1])}
    return {(x, y, z) for x in xs for y in ys for z in zs}


def factory_plan(hx: int, hy: int, color: str = "purple") -> list[dict[str, Any]]:
    """The Chocolate Factory around the hearth at (hx, hy), on the 3 x 3 tiles around it.

    Order matters for the world's support rule (a placement reaches level 0 or touches a block): the
    double metal door and the four metal pillars first, the lower course of coloured stone, then the
    windows resting on it, the upper course around them, the pitched thatch roof on the walls and the
    metal ridge between its halves. Cells are simulated so each step's count, cost and ``cumulative``
    are what the world will see; the north-west pillar climbs to level 9, the glass elevator.
    """
    color = color if color in COLORS else "purple"
    roof = ROOF_OF.get(color, "pink")
    x0, y0, x1, y1 = footprint(hx, hy, 3)
    bx0, by0, _, _ = tile_cells(x0, y0)
    _, _, bx1, by1 = tile_cells(x1, y1)
    mid = bx0 + 5  # the door's west column; the ridge runs over columns mid and mid + 1
    steps: list[dict[str, Any]] = [
        {"name": "door", "action": box(mid, by1, 0, bx2=mid + 1, bz2=3, material="metal", shape="door", facing="south")},
        {"name": "elevator pillar", "action": box(bx0, by0, 0, bz2=9, material="metal")},
        {"name": "pillar NE", "action": box(bx1, by0, 0, bz2=5, material="metal")},
        {"name": "pillar SW", "action": box(bx0, by1, 0, bz2=5, material="metal")},
        {"name": "pillar SE", "action": box(bx1, by1, 0, bz2=5, material="metal")},
        {"name": "lower walls", "action": box(bx0, by0, 0, bx1, by1, 1, material="stone", color=color, fill="walls")},
        {"name": "west windows", "action": box(bx0, by0 + 4, 2, by2=by0 + 7, bz2=3, material="wood", shape="window", facing="west")},
        {"name": "east windows", "action": box(bx1, by0 + 4, 2, by2=by0 + 7, bz2=3, material="wood", shape="window", facing="east")},
        {"name": "north windows", "action": box(bx0 + 4, by0, 2, bx2=bx0 + 7, bz2=3, material="wood", shape="window", facing="north")},
        {"name": "south windows west", "action": box(bx0 + 2, by1, 2, bx2=bx0 + 3, bz2=3, material="wood", shape="window", facing="south")},
        {"name": "south windows east", "action": box(bx0 + 8, by1, 2, bx2=bx0 + 9, bz2=3, material="wood", shape="window", facing="south")},
        {"name": "upper walls", "action": box(bx0, by0, 2, bx1, by1, 5, material="stone", color=color, fill="walls")},
        {"name": "roof west", "action": box(bx0, by0, 6, mid - 1, by1, material="thatch", shape="slope", facing="east", color=roof)},
        {"name": "roof east", "action": box(mid + 2, by0, 6, bx1, by1, material="thatch", shape="slope", facing="west", color=roof)},
        {"name": "ridge", "action": box(mid, by0, 6, mid + 1, by1, material="metal", shape="slab")},
    ]
    filled: set[tuple[int, int, int]] = set()
    for step in steps:
        new = _box_cells(step["action"]) - filled
        filled |= new
        step["cells"] = len(new)
        step["items"] = math.ceil(len(new) / 4)
        step["item"] = MATERIAL_ITEM[step["action"]["material"]]
        step["energy"] = 1 + math.ceil(len(new) / 32)
        step["cumulative"] = len(filled)
    return steps


def next_step(plan: list[dict[str, Any]], blocks_on_footprint: int) -> dict[str, Any] | None:
    """The first step the footprint's block count has not reached, or None when the house stands."""
    for step in plan:
        if blocks_on_footprint < step["cumulative"]:
            return step
    return None


def blocks_on(observe: dict[str, Any], owner: str, tiles: tuple[int, int, int, int]) -> int:
    """How many blocks the owner holds on the footprint tiles, from observe's ``blocks`` summary."""
    x0, y0, x1, y1 = tiles
    total = 0
    for row in observe.get("blocks") or []:
        if not isinstance(row, dict) or str(row.get("owner", "")).casefold() != owner.casefold():
            continue
        if isinstance(row.get("x"), int) and isinstance(row.get("y"), int) and x0 <= row["x"] <= x1 and y0 <= row["y"] <= y1:
            total += int(row.get("count", 0) or 0)
    return total


__all__ = [
    "COLORS",
    "MATERIAL_ITEM",
    "blocks_on",
    "box",
    "cells_of",
    "factory_plan",
    "footprint",
    "house_plan",
    "next_step",
    "tile_cells",
]
