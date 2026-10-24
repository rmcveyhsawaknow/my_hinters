"""The Chocolate Factory blueprint: a design of blocks over four plots, expanded into ordered ``place`` steps.

The design (``teams/blueprints/<name>.yaml``) names sections (tile rectangles with a style, a height, a
palette and doors), the chocolate river (the tiles of its branches) and the depots. ``expand`` turns it
into steps a builder can place one at a time: doors and pillars first, then wall rings from the ground
up (window bands among them), then the roof; the river as brown slabs at level 0, which close no tile.
Every step is simulated against the cells already filled, so its block count and its cost are what the
world will charge, and the world's support rule (reach level 0 or touch a block face to face) is checked
in order. The world's limits shape the design: a box holds at most 256 cells and lies within 2 tiles of
the builder (so every section is at most 5 tiles wide), the tallest build is 16 levels (four tiles),
blocks never stand on water or mountain, and a slab at level 0 or anything at level 6 and above never
closes a tile.

Progress is a small ledger per blueprint on this host (``runs/local/blueprints/<name>.json``): steps the
world accepted, or refused because every cell was already filled, are done. Builders take the first
undone step of a section, so a section rises in order and sections rise in parallel.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import math
import os
from collections import Counter, deque
from pathlib import Path
from typing import Any

import yaml

from hglab.blocks import MATERIAL_ITEM, box

DESIGN_DIR = "teams/blueprints"
LEDGER_DIR = "runs/local/blueprints"
MAX_CELLS = 256
TOP_LEVEL = 15
REACH = 2  # a box's every tile within 2 tiles of the builder
OWNED_CAP = 4000  # stop short of the world's 4096 blocks per agent
BUILD_COST = {"storehouse": {"wood": 20, "stone": 10}}

Rect = tuple[int, int, int, int]  # inclusive cell rectangle bx0, by0, bx1, by1


# ---------------------------------------------------------------- the design


def design_path(root: Path, name: str) -> Path:
    return Path(root) / DESIGN_DIR / f"{name}.yaml"


def load_design(root: Path, name: str) -> dict[str, Any]:
    data = yaml.safe_load(design_path(root, name).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("sections"):
        raise ValueError(f"blueprint {name} has no sections")
    return data


def cells_rect(tiles: list[int] | tuple[int, ...]) -> Rect:
    x0, y0, x1, y1 = (int(v) for v in tiles)
    return 4 * x0, 4 * y0, 4 * x1 + 3, 4 * y1 + 3


def _ring(rect: Rect, z0: int, z1: int, material: str, **extra: Any) -> dict[str, Any]:
    bx0, by0, bx1, by1 = rect
    return box(bx0, by0, z0, bx1, by1, z1, material=material, fill="walls", **extra)


def _perimeter(rect: Rect) -> int:
    bx0, by0, bx1, by1 = rect
    w, d = bx1 - bx0 + 1, by1 - by0 + 1
    return 2 * (w + d) - 4


def _door(rect: Rect, side: str, material: str, color: str, height: int = 4) -> dict[str, Any]:
    """A door two cells wide in the middle of a wall, ``height`` levels tall, facing out."""
    bx0, by0, bx1, by1 = rect
    mx, my = (bx0 + bx1) // 2, (by0 + by1) // 2
    top = height - 1
    if side == "west":
        return box(bx0, my, 0, by2=my + 1, bz2=top, material=material, shape="door", facing="west", color=color)
    if side == "east":
        return box(bx1, my, 0, by2=my + 1, bz2=top, material=material, shape="door", facing="east", color=color)
    if side == "north":
        return box(mx, by0, 0, bx2=mx + 1, bz2=top, material=material, shape="door", facing="north", color=color)
    return box(mx, by1, 0, bx2=mx + 1, bz2=top, material=material, shape="door", facing="south", color=color)


def _corners(rect: Rect, size: int) -> list[Rect]:
    """The four corner columns of ``size`` by ``size`` cells, NW, NE, SW, SE."""
    bx0, by0, bx1, by1 = rect
    s = size - 1
    return [(bx0, by0, bx0 + s, by0 + s), (bx1 - s, by0, bx1, by0 + s), (bx0, by1 - s, bx0 + s, by1), (bx1 - s, by1 - s, bx1, by1)]


def _column(cell: Rect, z0: int, z1: int, material: str, **extra: Any) -> dict[str, Any]:
    cx0, cy0, cx1, cy1 = cell
    return box(cx0, cy0, z0, cx1, cy1, z1, material=material, **extra)


def _bands(z0: int, z1: int, per_box: int) -> list[tuple[int, int]]:
    out, z = [], z0
    while z <= z1:
        top = min(z1, z + per_box - 1)
        out.append((z, top))
        z = top + 1
    return out


def _hip_roof(rect: Rect, z: int, slope: tuple[str, str], cap: tuple[str, str]) -> list[tuple[str, dict[str, Any]]]:
    """A ring of slopes rising inward at level ``z`` and a flat cap inside it at the same level."""
    bx0, by0, bx1, by1 = rect
    material, color = slope
    steps = [
        ("roof north", box(bx0, by0, z, bx1, by0, z, material=material, shape="slope", facing="south", color=color)),
        ("roof south", box(bx0, by1, z, bx1, by1, z, material=material, shape="slope", facing="north", color=color)),
        ("roof west", box(bx0, by0 + 1, z, bx0, by1 - 1, z, material=material, shape="slope", facing="east", color=color)),
        ("roof east", box(bx1, by0 + 1, z, bx1, by1 - 1, z, material=material, shape="slope", facing="west", color=color)),
    ]
    if bx1 - bx0 >= 2 and by1 - by0 >= 2:
        steps.append(("roof cap", box(bx0 + 1, by0 + 1, z, bx1 - 1, by1 - 1, z, material=cap[0], shape="slab", color=cap[1])))
    return steps


def _pair(value: Any, default: tuple[str, str]) -> tuple[str, str]:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return str(value[0]), str(value[1])
    return default


def _section_steps(section: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The named place actions of one section, in building order."""
    rect = cells_rect(section["tiles"])
    style = str(section.get("style", "hall"))
    levels = int(section.get("levels", 10))
    top = min(TOP_LEVEL, levels - 1)
    door_mat, door_color = _pair(section.get("door"), ("metal", "yellow"))
    steps: list[tuple[str, dict[str, Any]]] = []
    for side in section.get("doors") or ["south"]:
        steps.append((f"{side} door", _door(rect, str(side), door_mat, door_color)))
    per_level = _perimeter(rect)
    if style == "glass_tower":
        pillar = _pair(section.get("pillars"), ("stone", "white"))
        for i, cell in enumerate(_corners(rect, 1)):
            steps.append((f"pillar {i + 1}", _column(cell, 0, top - 1, pillar[0], color=pillar[1])))
        colors = [str(c) for c in section.get("bands") or ["red", "orange", "yellow", "lime", "green", "cyan", "blue", "purple"]]
        height = int(section.get("band_levels", 2))
        for i, (z0, z1) in enumerate(_bands(0, top - 1, height)):
            steps.append((f"glass band {z0}-{z1} {colors[i % len(colors)]}", _ring(rect, z0, z1, "wood", shape="window", color=colors[i % len(colors)])))
        crown = _pair(section.get("crown"), ("metal", "yellow"))
        bx0, by0, bx1, by1 = rect
        steps.append(("crown", box(bx0, by0, top, bx1, by1, top, material=crown[0], shape="slab", color=crown[1])))
        return steps
    if style == "stripe_tower":
        colors = [str(c) for c in section.get("stripes") or ["red", "white"]]
        windows = {int(z) for z in section.get("window_levels") or []}
        window_color = str(section.get("window_color", "yellow"))
        for z in range(top):
            if z in windows:
                steps.append((f"window ring {z}", _ring(rect, z, z, "wood", shape="window", color=window_color)))
            else:
                color = colors[z % len(colors)]
                steps.append((f"stripe {z} {color}", _ring(rect, z, z, "stone", color=color)))
        crown_slope = _pair(section.get("crown_slope"), ("thatch", "pink"))
        crown_cap = _pair(section.get("crown_cap"), ("thatch", "lime"))
        steps.extend(_hip_roof(rect, top, crown_slope, crown_cap))
        return steps
    # hall: corner turrets or pillars, coloured courses with window bands, a hip roof
    turret = section.get("turrets")
    if isinstance(turret, dict):
        size = int(turret.get("size", 2))
        t_top = min(TOP_LEVEL - 1, int(turret.get("levels", levels + 3)) - 1)
        mat, color = _pair(turret.get("block"), ("stone", "yellow"))
        for i, cell in enumerate(_corners(rect, size)):
            steps.append((f"turret {i + 1}", _column(cell, 0, t_top, mat, color=color)))
        cap = _pair(turret.get("cap"), ("thatch", "pink"))
        for i, cell in enumerate(_corners(rect, size)):
            steps.append((f"turret cap {i + 1}", _column(cell, t_top + 1, t_top + 1, cap[0], shape="slab", color=cap[1])))
    else:
        pillar = _pair(section.get("pillars"), ("stone", "natural"))
        wall_top = top - 1
        for i, cell in enumerate(_corners(rect, 1)):
            steps.append((f"pillar {i + 1}", _column(cell, 0, wall_top, pillar[0], color=pillar[1])))
    chimney = section.get("chimney")
    if isinstance(chimney, dict):
        cx, cy = int(chimney["x"]), int(chimney["y"])
        c_top = min(TOP_LEVEL, int(chimney.get("levels", 15)) - 1)
        colors = [str(c) for c in chimney.get("stripes") or ["red", "white"]]
        for i, (z0, z1) in enumerate(_bands(0, c_top, int(chimney.get("stripe_levels", 3)))):
            steps.append((f"chimney {z0}-{z1}", box(cx, cy, z0, cx + 1, cy + 1, z1, material="stone", color=colors[i % len(colors)])))
    colors = [str(c) for c in section.get("courses") or ["purple", "pink"]]
    course_levels = int(section.get("course_levels", 1))
    windows = {int(z) for z in section.get("window_levels") or []}
    window_color = str(section.get("window_color", "cyan"))
    wall_top = top - 1
    per_box = max(1, MAX_CELLS // per_level)
    z = 0
    course = 0
    while z <= wall_top:
        if z in windows:
            steps.append((f"window band {z}", _ring(rect, z, z, "wood", shape="window", color=window_color)))
            z += 1
            continue
        z1 = z
        while z1 + 1 <= wall_top and z1 + 1 not in windows and (z1 + 1 - z) < min(course_levels, per_box):
            z1 += 1
        color = colors[course % len(colors)]
        steps.append((f"course {z}-{z1} {color}", _ring(rect, z, z1, "stone", color=color)))
        course += 1
        z = z1 + 1
    slope = _pair(section.get("roof_slope"), ("thatch", "pink"))
    cap = _pair(section.get("roof_cap"), ("thatch", "purple"))
    steps.extend(_hip_roof(rect, top, slope, cap))
    return steps


def _river_runs(path: list[list[int]]) -> list[list[tuple[int, int]]]:
    """Split a river branch into straight runs of at most 5 tiles (a box within 2 tiles of its builder)."""
    tiles = [(int(p[0]), int(p[1])) for p in path]
    runs: list[list[tuple[int, int]]] = []
    for t in tiles:
        if runs:
            run = runs[-1]
            if len(run) < 5 and (len(run) == 1 and (abs(t[0] - run[-1][0]) + abs(t[1] - run[-1][1]) == 1) or (len(run) > 1 and _collinear(run[-2], run[-1], t))):
                run.append(t)
                continue
        runs.append([t])
    return runs


def _collinear(a: tuple[int, int], b: tuple[int, int], c: tuple[int, int]) -> bool:
    return (b[0] - a[0], b[1] - a[1]) == (c[0] - b[0], c[1] - b[1]) and abs(c[0] - b[0]) + abs(c[1] - b[1]) == 1


def _cells_of(action: dict[str, Any]) -> set[tuple[int, int, int]]:
    from hglab.blocks import _box_cells

    return _box_cells(action)


def _touches(cells: set[tuple[int, int, int]], filled: set[tuple[int, int, int]]) -> bool:
    for x, y, z in cells:
        for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            if (x + d[0], y + d[1], z + d[2]) in filled:
                return True
    return False


def tiles_of(action: dict[str, Any]) -> Rect:
    bx, by = int(action["bx"]), int(action["by"])
    bx2, by2 = int(action.get("bx2", bx)), int(action.get("by2", by))
    return min(bx, bx2) // 4, min(by, by2) // 4, max(bx, bx2) // 4, max(by, by2) // 4


def signature(action: dict[str, Any]) -> tuple[Any, ...]:
    """What identifies a place action, whatever order its fields came in."""
    bx, by, bz = int(action["bx"]), int(action["by"]), int(action["bz"])
    return (
        bx, by, bz, int(action.get("bx2", bx)), int(action.get("by2", by)), int(action.get("bz2", bz)),
        str(action.get("material")), str(action.get("shape") or "cube"), str(action.get("facing") or "north"),
        str(action.get("color") or "natural"), str(action.get("fill") or ""),
    )


def expand(design: dict[str, Any]) -> list[dict[str, Any]]:
    """Every step of the blueprint in order, simulated cell by cell.

    Each step carries ``id`` (section and index), ``section``, ``name``, ``kind`` (place or build),
    ``action``, ``tiles`` (the tile rectangle it touches), ``cells`` (blocks it adds after earlier steps),
    ``items`` and ``item`` (what it costs), ``supported`` (the world's support rule holds in this order)
    and ``top`` (its highest level).
    """
    steps: list[dict[str, Any]] = []
    filled: set[tuple[int, int, int]] = set()
    for i, depot in enumerate(design.get("depots") or []):
        x, y = int(depot["x"]), int(depot["y"])
        steps.append({
            "id": f"depots:{i:02d}", "section": "depots", "name": str(depot.get("name") or f"depot {i + 1}"), "kind": "build",
            "action": {"action": "build", "type": "storehouse", "x": x, "y": y, "policy": "faction"}, "tiles": (x, y, x, y),
            "cells": 0, "items": 30, "item": "wood", "costs": dict(BUILD_COST["storehouse"]), "supported": True, "top": 0,
        })

    def add(section: str, index: int, name: str, action: dict[str, Any]) -> None:
        cells = _cells_of(action)
        new = cells - filled
        supported = any(z == 0 for _, _, z in cells) or _touches(cells, filled)
        filled.update(cells)
        steps.append({
            "id": f"{section}:{index:02d}", "section": section, "name": name, "kind": "place", "action": action,
            "tiles": tiles_of(action), "cells": len(new), "items": max(1, math.ceil(len(new) / 4)) if new else 0,
            "item": MATERIAL_ITEM[str(action["material"])], "supported": supported, "top": max(z for _, _, z in cells),
            "box_cells": len(cells),
        })

    for section in design["sections"]:
        sid = str(section["id"])
        for i, (name, action) in enumerate(_section_steps(section)):
            add(sid, i, f"{section.get('name', sid)}: {name}", action)
    river = design.get("river") or {}
    material, color = _pair(river.get("block"), ("stone", "brown"))
    width = int(river.get("width_cells", 4))
    for branch, path in (river.get("branches") or {}).items():
        for i, run in enumerate(_river_runs(path)):
            xs, ys = [t[0] for t in run], [t[1] for t in run]
            pad = (4 - width) // 2
            if len(set(xs)) == 1:  # a north-south run: the slab band sits in the middle of the tile
                action = box(4 * xs[0] + pad, 4 * min(ys), 0, 4 * xs[0] + pad + width - 1, 4 * max(ys) + 3, 0, material=material, shape="slab", color=color)
            else:
                action = box(4 * min(xs), 4 * ys[0] + pad, 0, 4 * max(xs) + 3, 4 * ys[0] + pad + width - 1, 0, material=material, shape="slab", color=color)
            add(f"river-{branch}", i, f"the chocolate river ({branch}) {run[0]}..{run[-1]}", action)
    return steps


def materials(steps: list[dict[str, Any]], done: set[str] | frozenset[str] = frozenset()) -> Counter[str]:
    """Items the steps not yet done still cost."""
    need: Counter[str] = Counter()
    for step in steps:
        if step["id"] in done:
            continue
        if step["kind"] == "build":
            need.update(step.get("costs") or {})
        else:
            need[step["item"]] += int(step["items"])
    return need


def summary(design: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    by_section: dict[str, dict[str, Any]] = {}
    for step in steps:
        s = by_section.setdefault(step["section"], {"steps": 0, "blocks": 0, "top": 0})
        s["steps"] += 1
        s["blocks"] += int(step.get("cells", 0))
        s["top"] = max(s["top"], int(step.get("top", 0)))
    return {
        "name": design.get("name"), "steps": len(steps), "blocks": sum(int(s.get("cells", 0)) for s in steps),
        "materials": dict(materials(steps)), "sections": by_section, "tallest": max((int(s.get("top", 0)) for s in steps), default=0) + 1,
    }


# ---------------------------------------------------------------- checks against the world


def check(design: dict[str, Any], steps: list[dict[str, Any]], world: dict[str, Any] | None = None) -> list[str]:
    """Problems with the blueprint: the world's box and height limits, support order, and (with the public
    world) terrain under every tile, scarce nodes and the ore apron kept clear of walls, the plots kept."""
    problems: list[str] = []
    for step in steps:
        if step["kind"] != "place":
            continue
        action = step["action"]
        x0, y0, x1, y1 = step["tiles"]
        if step["box_cells"] > MAX_CELLS:
            problems.append(f"{step['id']}: {step['box_cells']} cells in one box")
        if x1 - x0 > 2 * REACH or y1 - y0 > 2 * REACH:
            problems.append(f"{step['id']}: {x1 - x0 + 1}x{y1 - y0 + 1} tiles, wider than a builder's reach")
        if step["top"] > TOP_LEVEL:
            problems.append(f"{step['id']}: level {step['top']} above the ceiling")
        if not step["supported"]:
            problems.append(f"{step['id']}: unsupported in this order")
        if not step["cells"]:
            problems.append(f"{step['id']}: adds nothing")
        if str(action.get("shape") or "cube") not in {"cube", "slab", "slope", "door", "window"}:
            problems.append(f"{step['id']}: unknown shape")
    if world is None:
        return problems
    from hglab.lots import lot_id, terrain_lookup

    terrain = terrain_lookup(world)
    nodes = {(int(r["x"]), int(r["y"])): str(r.get("kind")) for r in world.get("resources") or [] if isinstance(r, dict)}
    structures = {(int(s["x"]), int(s["y"])): str(s.get("type")) for s in world.get("structures") or [] if isinstance(s, dict)}
    apron = {(x + dx, y + dy) for (x, y), k in nodes.items() if k == "ore" for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    plots = {str(p) for p in design.get("plots") or []}
    river_ok = {"road", "sign"}
    for step in steps:
        x0, y0, x1, y1 = step["tiles"]
        floor = step["kind"] == "place" and str(step["action"].get("shape")) == "slab" and int(step["action"]["bz"]) == 0
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                where = (x, y)
                code = terrain(x, y)
                if code in (None, "W", "w", "m"):
                    problems.append(f"{step['id']}: tile {where} is {code or 'off the map'}")
                if plots and lot_id(x, y)[:3] not in plots:
                    problems.append(f"{step['id']}: tile {where} lies outside the plots")
                if step["kind"] == "build":
                    if where in structures:
                        problems.append(f"{step['id']}: tile {where} already holds a {structures[where]}")
                    continue
                if nodes.get(where) in ("stone", "ore"):
                    problems.append(f"{step['id']}: tile {where} holds a {nodes[where]} node")
                if floor:
                    if where in structures and structures[where] not in river_ok:
                        problems.append(f"{step['id']}: river over a {structures[where]} at {where}")
                    continue
                if where in apron:
                    problems.append(f"{step['id']}: wall in the ore apron at {where}")
                if where in structures:
                    problems.append(f"{step['id']}: wall over a {structures[where]} at {where}")
    return sorted(set(problems))


def route(world: dict[str, Any], waypoints: list[tuple[int, int]], blocked: set[tuple[int, int]]) -> list[tuple[int, int]]:
    """The river through its waypoints: the shortest four-way path over ground that may take a slab.

    Not water or mountain, not a stone or ore node, not a structure other than a road or a sign, and
    not inside a section. Ties prefer going straight, so runs are long and boxes few.
    """
    from hglab.lots import terrain_lookup

    terrain = terrain_lookup(world)
    nodes = {(int(r["x"]), int(r["y"])) for r in world.get("resources") or [] if isinstance(r, dict) and r.get("kind") in ("stone", "ore")}
    structures = {(int(s["x"]), int(s["y"])): str(s.get("type")) for s in world.get("structures") or [] if isinstance(s, dict)}

    def ok(t: tuple[int, int]) -> bool:
        return terrain(*t) in ("s", "g", "f", "h") and t not in nodes and t not in blocked and structures.get(t, "road") in ("road", "sign")

    path: list[tuple[int, int]] = []
    for a, b in itertools.pairwise(waypoints):
        prev: dict[tuple[int, int], tuple[int, int] | None] = {a: None}
        heading: dict[tuple[int, int], tuple[int, int]] = {a: (0, 0)}
        queue: deque[tuple[int, int]] = deque([a])
        while queue:
            cur = queue.popleft()
            if cur == b:
                break
            moves = [(1, 0), (-1, 0), (0, 1), (0, -1)]
            moves.sort(key=lambda d: d != heading[cur])
            for d in moves:
                nxt = (cur[0] + d[0], cur[1] + d[1])
                if nxt in prev or not (ok(nxt) or nxt == b):
                    continue
                prev[nxt] = cur
                heading[nxt] = d
                queue.append(nxt)
        if b not in prev:
            raise ValueError(f"no river path from {a} to {b}")
        leg: list[tuple[int, int]] = []
        cur: tuple[int, int] | None = b
        while cur is not None:
            leg.append(cur)
            cur = prev[cur]
        leg.reverse()
        path.extend(leg if not path else leg[1:])
    return path


# ---------------------------------------------------------------- the ledger


def ledger_path(root: Path, name: str) -> Path:
    return Path(root) / LEDGER_DIR / f"{name}.json"


def load_ledger(root: Path, name: str) -> dict[str, Any]:
    try:
        data = json.loads(ledger_path(root, name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("done", {})
    return data


def mark_done(root: Path, name: str, ids: list[str], tick: int, by: str) -> None:
    if not ids:
        return
    path = ledger_path(root, name)
    data = load_ledger(root, name)
    for sid in ids:
        data["done"].setdefault(sid, {"tick": int(tick), "by": by})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    with contextlib.suppress(OSError):
        os.replace(tmp, path)


_CACHE: dict[tuple[str, float], tuple[dict[str, Any], list[dict[str, Any]], dict[tuple[Any, ...], str]]] = {}


def blueprint(root: Path, name: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[tuple[Any, ...], str]]:
    """The design, its steps and an index from place signature to step id (cached per file version)."""
    path = design_path(root, name)
    key = (str(path), path.stat().st_mtime)
    if key not in _CACHE:
        design = load_design(root, name)
        steps = expand(design)
        index = {signature(s["action"]): s["id"] for s in steps if s["kind"] == "place"}
        _CACHE.clear()
        _CACHE[key] = (design, steps, index)
    return _CACHE[key]


def settle(root: Path, name: str, actions: list[dict[str, Any]], results: list[dict[str, Any]], tick: int, by: str, structures: list[dict[str, Any]] | None = None) -> list[str]:
    """Mark the steps a live wake completed: placements the world accepted, or refused as already filled."""
    try:
        _design, steps, index = blueprint(root, name)
    except (OSError, ValueError):
        return []
    done: list[str] = []
    for action, result in zip(actions, results, strict=False):
        if not isinstance(action, dict) or not isinstance(result, dict):
            continue
        if action.get("action") == "place" and action.get("bx") is not None:
            sid = index.get(signature(action))
            if sid is None:
                continue
            refused = str(result.get("error") or "")
            text = json.dumps(result).casefold()
            if result.get("ok") or (refused == "not_allowed" and "filled" in text):
                done.append(sid)
        elif action.get("action") == "build" and action.get("type") == "storehouse" and result.get("ok"):
            for step in steps:
                if step["kind"] == "build" and (step["action"]["x"], step["action"]["y"]) == (action.get("x"), action.get("y")):
                    done.append(step["id"])
    mark_done(root, name, done, tick, by)
    return done


# ---------------------------------------------------------------- the builder


def ready_steps(steps: list[dict[str, Any]], done: set[str], skip: set[str] | frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """The first undone step of each section: a section rises in order, sections in parallel."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for step in steps:
        if step["section"] in seen or step["id"] in done:
            continue
        seen.add(step["section"])
        if step["id"] in skip:
            # planned earlier this wake: the next step of the section may follow it
            seen.discard(step["section"])
            continue
        out.append(step)
    return out


def _admits(store: dict[str, Any], me: str, faction: str) -> bool:
    policy = str(store.get("policy") or "private")
    owner = str(store.get("owner", "")).casefold()
    theirs = store.get("faction")
    theirs = str(theirs.get("name") if isinstance(theirs, dict) else theirs or "")
    return owner == me.casefold() or policy == "public" or (policy == "faction" and bool(faction) and theirs.casefold() == faction.casefold())


EMPTY_STORE_TICKS = 1440  # a store found without the item a builder came for is passed over for four hours
BUILD_RANGE = 16  # a builder further than this from every ready step (the crew's range) leaves the walk to the team-site migration


def root_of(team: Any) -> Path:
    """The repository a team file lives in (``teams/<slug>.yaml``), else the working directory."""
    path = getattr(team, "path", None)
    return Path(path).resolve().parents[1] if path else Path.cwd()


def builder_sections(team: Any, slug: str) -> list[str] | None:
    """The sections a builder raises first, or None when the persona does not build the team's blueprint."""
    cfg = (getattr(team, "extra", None) or {}).get("pipeline") if team is not None else None
    if not isinstance(cfg, dict) or not cfg.get("blueprint"):
        return None
    builders = cfg.get("builders") or {}
    if isinstance(builders, dict):
        return [str(s) for s in builders[slug]] if slug in builders else None
    return [] if slug in builders else None


def plan_step(
    persona: Any,
    team: Any,
    state: Any,
    observe: dict[str, Any],
    view: Any,
    inventory: dict[str, int],
    position: tuple[int, int],
    room: int,
    mates: set[str] | None = None,
    root: Path | None = None,
) -> tuple[list[dict[str, Any]], str, str] | None:
    """One step of the team's blueprint for a builder: place the next box, carry its material, or raise a depot.

    The builder takes the first undone step of its own sections (the team file's ``pipeline.builders``),
    then of any section, nearest first, skipping a step whose material it cannot find. It places when the
    pack, or a store it may take from within a tile of where it will stand, holds the step's cost; else
    it walks to the nearest store that holds the material (a store found without it is passed over for
    four hours) and takes enough for several steps. When no store holds the material, the step is left
    for the gatherers and ``state._bp_need`` names what is missing.
    """
    from hglab.planner import _step_toward, chebyshev, reachable_tiles

    prefs = builder_sections(team, persona.slug)
    if prefs is None or room < 1:
        return None
    you = observe.get("you") or {}
    if int(you.get("blocks_owned", 0) or 0) >= OWNED_CAP:
        return None
    root = root or root_of(team)
    name = str(team.extra["pipeline"]["blueprint"])
    try:
        _design, steps, _index = blueprint(root, name)
    except (OSError, ValueError):
        return None
    done = set((load_ledger(root, name).get("done") or {}).keys())
    structures = list(view.world_structures or []) + list(view.structures or [])
    standing = {(int(s.get("x", -1)), int(s.get("y", -1))) for s in structures if s.get("type") == "storehouse"}
    for step in steps:
        if step["kind"] == "build" and (step["action"]["x"], step["action"]["y"]) in standing:
            done.add(step["id"])
    planned: set[str] = getattr(state, "_bp_planned", None) or set()
    ready = ready_steps(steps, done, planned)
    if not ready:
        return None
    rank = {sec: i for i, sec in enumerate(prefs)}

    def centre(step: dict[str, Any]) -> tuple[int, int]:
        x0, y0, x1, y1 = step["tiles"]
        return (x0 + x1) // 2, (y0 + y1) // 2

    if min(chebyshev(position, centre(s)) for s in ready) > BUILD_RANGE:
        return None  # far from the factory: the migration walks there first, and errands nearer home still run
    ready = [s for s in ready if chebyshev(position, centre(s)) <= BUILD_RANGE + 10]
    ready.sort(key=lambda s: (rank.get(s["section"], len(rank)), chebyshev(position, centre(s)), s["id"]))
    faction = you.get("faction")
    faction = str(faction.get("name") if isinstance(faction, dict) else faction or "")
    me = str(getattr(persona, "name", ""))
    mates_cf = {m.casefold() for m in (mates or set())} | {me.casefold()}
    tick = int(observe.get("tick", 0) or 0)
    empty = state.flags.get("bp_empty") if isinstance(state.flags.get("bp_empty"), dict) else {}
    empty = {k: v for k, v in empty.items() if tick - int(v or 0) < EMPTY_STORE_TICKS}
    seen_stores = [s for s in view.structures if s.get("type") == "storehouse" and isinstance(s.get("storage"), dict) and _admits(s, me, faction)]
    far_stores = [
        s for s in (view.world_structures or [])
        if s.get("type") == "storehouse" and str(s.get("owner", "")).casefold() in mates_cf
        and chebyshev(position, (int(s.get("x", -999)), int(s.get("y", -999)))) <= BUILD_RANGE
        and not any((t.get("x"), t.get("y")) == (s.get("x"), s.get("y")) for t in view.structures)
    ]
    reach = reachable_tiles(view, position) | {position}
    pack = sum(int(v) for v in inventory.values())
    missing: list[str] = []
    for step in ready:
        costs = dict(step.get("costs") or {step["item"]: int(step["items"])})
        x0, y0, x1, y1 = step["tiles"]
        if step["kind"] == "build":
            stands = [(x, y) for x in range(x0 - 1, x1 + 2) for y in range(y0 - 1, y1 + 2) if (x, y) != (x0, y0)]
        else:
            stands = [(x, y) for x in range(x1 - REACH, x0 + REACH + 1) for y in range(y1 - REACH, y0 + REACH + 1)]
        stands = [t for t in stands if t == position or view.walkable(*t)]
        if not stands:
            continue

        def near_stock(tile: tuple[int, int], item: str) -> int:
            return sum(int(s["storage"].get(item, 0) or 0) for s in seen_stores if chebyshev(tile, (int(s["x"]), int(s["y"]))) <= 1)

        def short(tile: tuple[int, int], costs: dict[str, int] = costs) -> dict[str, int]:
            gaps = {item: qty - int(inventory.get(item, 0)) - near_stock(tile, item) for item, qty in costs.items()}
            return {item: gap for item, gap in gaps.items() if gap > 0}

        here_ok = [t for t in stands if t in reach and not short(t)]
        if here_ok:
            stand = min(here_ok, key=lambda t: (t != position, chebyshev(position, t), t))
            act = dict(step["action"])
            label = f"{step['name']} ({step['cells']} blocks, {step['items']} {step['item']})" if step["kind"] == "place" else f"{step['name']} at {(x0, y0)}"
            planned.add(step["id"])
            state._bp_planned = planned
            if stand == position:
                return [act], f"the factory blueprint: {label}", "blueprint"
            return [{"action": "move", "x": stand[0], "y": stand[1]}, act], f"the factory blueprint: walk to {stand} and raise {label}", "blueprint"
        lacking = {item: qty - int(inventory.get(item, 0)) for item, qty in costs.items() if qty - int(inventory.get(item, 0)) > 0}
        # carry it: the nearest store that holds the material, or a team store not yet looked into
        for item, qty in sorted(lacking.items(), key=lambda kv: -kv[1]):
            holders = [s for s in seen_stores if int(s["storage"].get(item, 0) or 0) >= min(qty, 4)]
            beside = [s for s in holders if chebyshev(position, (int(s["x"]), int(s["y"]))) <= 1]
            if beside and pack < 50:
                store = beside[0]
                take = min(50 - pack, int(store["storage"].get(item, 0) or 0), max(qty, 40))
                return [{"action": "take", "x": int(store["x"]), "y": int(store["y"]), "item": item, "qty": take}], f"the factory blueprint needs {qty} {item} for {step['name']}: take {take} from the store at ({store['x']}, {store['y']})", "blueprint"
            for s in [s for s in seen_stores if chebyshev(position, (int(s["x"]), int(s["y"]))) <= 1 and not int(s["storage"].get(item, 0) or 0)]:
                empty[f"{s['x']},{s['y']}:{item}"] = tick
            targets = sorted(holders, key=lambda s: chebyshev(position, (int(s["x"]), int(s["y"]))))
            targets += sorted(
                (s for s in far_stores if f"{s.get('x')},{s.get('y')}:{item}" not in empty),
                key=lambda s: chebyshev(position, (int(s["x"]), int(s["y"]))),
            )
            for store in targets:
                where = (int(store["x"]), int(store["y"]))
                if chebyshev(position, where) <= 1:
                    continue
                target = _step_toward(position, {"x": where[0], "y": where[1]}, view)
                if target is not None and target != position:
                    state.flags["bp_empty"] = dict(sorted(empty.items(), key=lambda kv: -int(kv[1]))[:12])
                    return [{"action": "move", "x": target[0], "y": target[1]}], f"the factory blueprint needs {qty} {item} for {step['name']}: walk to the store at {where} for it", "blueprint"
            missing.append(item)
    state.flags["bp_empty"] = dict(sorted(empty.items(), key=lambda kv: -int(kv[1]))[:12])
    if missing:
        state._bp_need = missing[0]
        return None
    # every ready step is out of reach this wake: walk toward the nearest
    goal = centre(ready[0])
    target = _step_toward(position, {"x": goal[0], "y": goal[1]}, view)
    if target is not None and target != position:
        return [{"action": "move", "x": target[0], "y": target[1]}], f"the factory blueprint: walk toward {ready[0]['name']} at {goal}", "blueprint"
    return None


__all__ = [
    "LEDGER_DIR", "blueprint", "builder_sections", "cells_rect", "check", "expand", "load_design", "load_ledger", "mark_done",
    "materials", "plan_step", "ready_steps", "root_of", "route", "settle", "signature", "summary", "tiles_of",
]
