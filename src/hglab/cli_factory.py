"""`hglab factory`: the team blueprint's survey, steps, checks, river route, progress and a render export."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from hglab import factory

factory_app = typer.Typer(help="The Chocolate Factory blueprint: survey the ground, show and check the steps, route the river, read progress.")
NAME = typer.Option("chocolate-factory", "--name", help="teams/blueprints/<name>.yaml")


def _world(root: Path) -> dict:
    from hglab.cli_personas import fetch_public_world, world_cache_path

    world = fetch_public_world(world_cache_path(root))
    if not world:
        raise typer.BadParameter("the public world snapshot could not be read")
    return world


@factory_app.command("survey")
def survey_command(x0: int = typer.Option(78), y0: int = typer.Option(76), x1: int = typer.Option(101), y1: int = typer.Option(102)) -> None:
    """The ground as characters: terrain, nodes (T wood, o stone, * ore, v fiber, b berries) and structures."""
    from hglab.lots import terrain_lookup

    world = _world(Path.cwd())
    terrain = terrain_lookup(world)
    nodes = {(r["x"], r["y"]): r["kind"] for r in world.get("resources") or []}
    marks = {"storehouse": "S", "hut": "H", "farm": "F", "tower": "^", "sign": "!", "road": "=", "bridge": "#", "wall": "X"}
    structures = {(s["x"], s["y"]): marks.get(s["type"], "?") for s in world.get("structures") or []}
    code = {"W": "~", "w": "w", "s": ".", "g": ",", "f": "f", "h": "h", "m": "M"}
    kind = {"wood": "T", "stone": "o", "ore": "*", "fiber": "v", "berries": "b"}
    typer.echo("    " + "".join(str(x % 10) for x in range(x0, x1 + 1)))
    for y in range(y0, y1 + 1):
        row = "".join(structures.get((x, y)) or kind.get(nodes.get((x, y)), "") or code.get(terrain(x, y) or "", " ") for x in range(x0, x1 + 1))
        typer.echo(f"{y:3} {row}")


@factory_app.command("show")
def show_command(name: str = NAME) -> None:
    """Sections, steps, blocks and materials, and what the ledger says is done."""
    root = Path.cwd()
    design, steps, _ = factory.blueprint(root, name)
    info = factory.summary(design, steps)
    done = set(factory.load_ledger(root, name).get("done") or {})
    typer.echo(f"{info['name']}: {info['steps']} steps, {info['blocks']} blocks, tallest {info['tallest']} levels; {len(done)} steps done")
    typer.echo("materials still needed: " + ", ".join(f"{k} {v}" for k, v in sorted(factory.materials(steps, done).items())))
    for sid, s in info["sections"].items():
        left = sum(1 for st in steps if st["section"] == sid and st["id"] not in done)
        typer.echo(f"  {sid:14} {s['steps']:3} steps, {s['blocks']:5} blocks, up to level {s['top']}; {left} to go")


@factory_app.command("check")
def check_command(name: str = NAME, world: bool = typer.Option(True, "--world/--no-world")) -> None:
    """The world's limits and the land survey: exit 1 when the blueprint breaks a rule."""
    root = Path.cwd()
    design, steps, _ = factory.blueprint(root, name)
    problems = factory.check(design, steps, _world(root) if world else None)
    for p in problems:
        typer.echo(f"  ! {p}")
    typer.echo(f"{len(steps)} steps checked: {len(problems)} problem(s)")
    if problems:
        raise typer.Exit(code=1)


@factory_app.command("route")
def route_command(name: str = NAME, write: bool = typer.Option(False, "--write")) -> None:
    """Route the chocolate river through its waypoints over the current map (and write the branches)."""
    root = Path.cwd()
    design = factory.load_design(root, name)
    world = _world(root)
    blocked: set[tuple[int, int]] = set()
    for s in design["sections"]:
        x0, y0, x1, y1 = s["tiles"]
        blocked |= {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
    blocked |= {(int(d["x"]), int(d["y"])) for d in design.get("depots") or []}
    branches = {b: factory.route(world, [tuple(p) for p in pts], blocked) for b, pts in (design.get("river") or {}).get("waypoints", {}).items()}
    for b, path in branches.items():
        typer.echo(f"{b}: {len(path)} tiles {path}")
    if write:
        path = factory.design_path(root, name)
        text = path.read_text(encoding="utf-8")
        head, _, tail = text.partition("  branches:")
        rest = tail.split("\n", 1)[1] if "\n" in tail else ""
        while rest.startswith("    "):
            rest = rest.split("\n", 1)[1] if "\n" in rest else ""
        lines = "\n".join(f"    {b}: [{', '.join(f'[{x}, {y}]' for x, y in p)}]" for b, p in branches.items())
        path.write_text(f"{head}  branches:\n{lines}\n{rest}", encoding="utf-8", newline="\n")
        typer.echo(f"written to {path}")


@factory_app.command("progress")
def progress_command(name: str = NAME) -> None:
    """The ledger: the last steps done and who placed them."""
    root = Path.cwd()
    _design, steps, _ = factory.blueprint(root, name)
    done = factory.load_ledger(root, name).get("done") or {}
    names = {s["id"]: s["name"] for s in steps}
    for sid, row in sorted(done.items(), key=lambda kv: -int(kv[1].get("tick", 0)))[:20]:
        typer.echo(f"  tick {row.get('tick')}: {row.get('by')} {names.get(sid, sid)}")
    typer.echo(f"{len(done)} of {len(steps)} steps done")


@factory_app.command("export")
def export_command(name: str = NAME, out: Path = typer.Option(Path("runs/local/blueprints/chocolate-factory-render.json"), "--out")) -> None:  # noqa: B008
    """Every cell of the finished blueprint with its material, shape, facing and colour, and the ground under it, for a render."""
    from hglab.blocks import _box_cells
    from hglab.lots import terrain_lookup

    root = Path.cwd()
    design, steps, _ = factory.blueprint(root, name)
    cells: dict[tuple[int, int, int], list] = {}
    order: list[list] = []
    for step in steps:
        if step["kind"] != "place":
            continue
        a = step["action"]
        n = len(order)
        order.append([step["id"], step["name"], step["section"], step["cells"], step["item"], step["items"]])
        for cell in _box_cells(a):
            cells.setdefault(cell, [a["material"], a.get("shape", "cube"), a.get("facing", "north"), a.get("color", "natural"), step["section"], n])
    world = _world(root)
    terrain = terrain_lookup(world)
    xs = [x for p in design.get("plots") or [] for x in range((ord(p[0]) - 65) * 10, (ord(p[0]) - 65) * 10 + 10)]
    ys = [y for p in design.get("plots") or [] for y in range(int(p[1:]) * 10, int(p[1:]) * 10 + 10)]
    x0, x1, y0, y1 = min(xs) - 4, max(xs) + 4, min(ys) - 6, max(ys) + 4
    ground = [[terrain(x, y) or "W" for x in range(x0, x1 + 1)] for y in range(y0, y1 + 1)]
    nodes = [[r["x"], r["y"], r["kind"]] for r in world.get("resources") or [] if x0 <= r["x"] <= x1 and y0 <= r["y"] <= y1]
    structures = [[s["x"], s["y"], s["type"], s.get("owner")] for s in world.get("structures") or [] if x0 <= s["x"] <= x1 and y0 <= s["y"] <= y1]
    payload = {
        "name": design.get("name"), "story": design.get("story"), "origin": [x0, y0], "ground": ["".join(r) for r in ground],
        "nodes": nodes, "structures": structures, "sections": [{k: s[k] for k in ("id", "name", "tiles", "levels")} for s in design["sections"]],
        "cells": [[x, y, z, *v] for (x, y, z), v in sorted(cells.items())], "steps": order, "summary": factory.summary(design, steps),
        "depots": [[int(d["x"]), int(d["y"]), d.get("name")] for d in design.get("depots") or []], "river": (design.get("river") or {}).get("branches") or {},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload), encoding="utf-8")
    typer.echo(f"{len(cells)} cells written to {out}")


def register(app: typer.Typer) -> None:
    app.add_typer(factory_app, name="factory")
