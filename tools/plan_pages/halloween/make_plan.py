"""Build halloween-plan.html from the Halloween and signposts blueprints, their expanded steps and the public world.

Run from the repository root with the project venv:
    .venv/Scripts/python tools/plan_pages/halloween/make_plan.py
It reads teams/blueprints/halloween.yaml and signposts.yaml (through hglab.factory), runs/local/world.json, the
blueprint ledgers and teams/*.yaml, fills template.html (beside this script) with one JSON literal and writes
halloween-plan.html beside it. The page draws every block of the design in 3D, so the model town can be seen whole.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from hglab import factory
from hglab.blocks import _box_cells
from hglab.lots import lot_bounds, lot_id

ROOT = Path(__file__).resolve().parents[3]  # the repository: tools/plan_pages/<name>/make_plan.py
HERE = Path(__file__).resolve().parent
NAME = "halloween"
X0, Y0, X1, Y1 = 93, 25, 116, 56  # the drawing: the site and a tile or two round it
GROUPS = [
    ("opening", "The opening", "the woods the camera glides over, the house on the hill and the bridge on the road into town",
     ["haunted-woods", "maitland-house", "covered-bridge"]),
    ("street", "Village Street", "the town of the model: church, hardware store, library and lions, school, fire house, barber, green and two houses",
     ["church", "hardware", "library", "library-lions", "school", "fire-house", "barber", "town-green", "dark-house", "lantern-house"]),
    ("afterlife", "The afterlife", "the model's graveyard and the striped ghost's crypt, the handbook, the waiting room and the sandworm",
     ["graveyard", "crypt", "striped-ghost", "handbook", "waiting-room", "sandworm"]),
    ("harvest", "The harvest", "the pumpkin patch and its scarecrow, and the great jack-o'-lantern", ["pumpkin-patch", "great-jack"]),
]
COLORS = ["natural", "white", "grey", "black", "brown", "red", "orange", "yellow", "lime", "green", "teal", "cyan", "blue", "indigo", "purple", "pink", "tan"]
MATERIALS = ["stone", "wood", "thatch", "metal"]
SHAPES = ["cube", "slab", "slope", "window", "door"]
FACINGS = ["north", "east", "south", "west"]


def _progress(name: str) -> dict:
    design, steps, _ = factory.blueprint(ROOT, name)
    done = factory.load_ledger(ROOT, factory.ledger_name(design, name)).get("done") or {}
    ids = {s["id"] for s in steps}
    return {"id": name, "name": str(design.get("name") or name), "steps": len(steps), "done": len([k for k in done if k in ids])}


def main() -> None:
    design, steps, _ = factory.blueprint(ROOT, NAME)
    world = json.loads((ROOT / "runs/local/world.json").read_text(encoding="utf-8"))
    info = factory.summary(design, steps)
    problems = factory.check(design, steps, world)
    width = int(world.get("width", 128))
    terrain = world["terrain"]
    by_id = {str(s["id"]): s for s in design["sections"]}
    assert set(by_id) == {sid for g in GROUPS for sid in g[3]}, "every section belongs to one group"

    cells: list[int] = []
    for s in steps:
        if s["kind"] != "place":
            continue
        a = s["action"]
        c = COLORS.index(str(a.get("color") or "natural"))
        m = MATERIALS.index(str(a["material"]))
        sh = SHAPES.index(str(a.get("shape") or "cube"))
        f = FACINGS.index(str(a.get("facing") or "north"))
        for x, y, z in _box_cells(a):
            cells += [x - 4 * X0, y - 4 * Y0, z, c, m, sh, f]

    number, sections = {}, []
    for key, _title, _blurb, ids in GROUPS:
        for sid in ids:
            sec = by_id[sid]
            number[sid] = len(number) + 1
            sv = info["sections"][sid]
            sections.append({
                "n": number[sid], "id": sid, "name": sec["name"], "group": key, "style": sec["style"].replace("_", " "),
                "tiles": [int(v) for v in sec["tiles"]], "top": sv["top"], "blocks": sv["blocks"], "steps": sv["steps"],
                "sign": [int(sec["sign"]["x"]), int(sec["sign"]["y"])], "text": sec["sign"]["text"],
            })
    groups = [{"key": k, "title": t, "blurb": b, "sections": [number[s] for s in ids],
               "blocks": sum(info["sections"][s]["blocks"] for s in ids)} for k, t, b, ids in GROUPS]
    lots = sorted({lid for s in steps for lid in factory.step_lots(s)})

    signposts_design, _steps, _ = factory.blueprint(ROOT, "signposts")
    signposts = [{"id": s["id"], "name": s["name"], "tiles": [int(v) for v in s["tiles"]], "sign": [int(s["sign"]["x"]), int(s["sign"]["y"])], "text": s["sign"]["text"]}
                 for s in signposts_design["sections"]]

    chains = []
    for path in sorted((ROOT / "teams").glob("*.yaml")):
        team = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        pipe = team.get("pipeline") or {}
        if not pipe.get("blueprint"):
            continue
        seq = [str(pipe["blueprint"])] + [str(n) for n in pipe.get("next_blueprint") or []]
        chains.append({"team": str(team.get("name") or path.stem), "designs": [_progress(n) for n in seq]})
    chains.sort(key=lambda c: -len(c["designs"]))

    structures = [[int(s["x"]), int(s["y"]), str(s["type"])] for s in world.get("structures") or []
                  if X0 <= int(s["x"]) <= X1 and Y0 <= int(s["y"]) <= Y1]
    data = {
        "bounds": [X0, Y0, X1, Y1], "tick": int(world.get("tick", 0)),
        "terrain": ["".join(terrain[y * width + x] for x in range(X0, X1 + 1)) for y in range(Y0, Y1 + 1)],
        "lots": [[lid, *lot_bounds(lid)] for lid in lots],
        "centres": sorted({((b := lot_bounds(lid))[0] + 2, b[1] + 2) for lid in {lot_id(x, y) for x in range(X0, X1 + 1) for y in range(Y0, Y1 + 1)}}),
        "structures": structures, "sections": sections, "groups": groups, "cells": cells,
        "streets": [{"name": s["name"], "tiles": [int(v) for v in s["tiles"]]} for s in design.get("streets") or []],
        "river": [list(t) for t in (design.get("river") or {}).get("branches", {}).get("winter", [])],
        "gate": [_progress(n) for n in design["after"]], "self": _progress(NAME), "chains": chains,
        "signposts": signposts, "signpostsOpen": factory.design_open(ROOT, "signposts"), "open": factory.design_open(ROOT, NAME),
        "totals": {"sections": len(sections), "steps": info["steps"], "blocks": info["blocks"], "items": dict(info["materials"]), "lots": len(lots),
                   "problems": len(problems), "signposts": len(signposts), "tallest": info["tallest"] - 1},
    }
    page = (HERE / "template.html").read_text(encoding="utf-8")
    literal = json.dumps(data, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    out = HERE / "halloween-plan.html"
    out.write_text(page.replace("__DATA__", literal), encoding="utf-8", newline="\n")
    print(f"written {out} ({out.stat().st_size} bytes): {len(sections)} sections, {len(cells) // 7} cells, {info['blocks']} blocks, {len(problems)} problems")


if __name__ == "__main__":
    main()
