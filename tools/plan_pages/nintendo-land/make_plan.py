"""Build nintendo-land-plan.html from the blueprint, its expanded steps and the public world.

Run from the repository root with the project venv:
    .venv/Scripts/python <this folder>/make_plan.py
It reads teams/blueprints/nintendo-land.yaml (through hglab.factory), runs/local/world.json and teams/*.yaml,
fills template.html (beside this script) with one JSON literal and writes nintendo-land-plan.html beside it.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import yaml

from hglab import factory
from hglab.blocks import _box_cells
from hglab.lots import lot_bounds, lot_id

ROOT = Path(__file__).resolve().parents[3]  # the repository: tools/plan_pages/<name>/make_plan.py
HERE = Path(__file__).resolve().parent
NAME = "nintendo-land"
X0, Y0, X1, Y1 = 53, 18, 96, 41  # the drawing: the site and two tiles round it
SITE = (55, 20, 94, 39)
LOTS = ["F02-NE", "F02-SE", "F03-NE", "F03-SE"] + [f"{c}{r}-{q}" for c in "GHI" for r in ("02", "03") for q in ("NW", "NE", "SW", "SE")] + ["J02-NW", "J02-SW", "J03-NW", "J03-SW"]
FLAT = {"park", "pool"}

DISTRICTS = [
    ("mushroom", "The Mushroom Kingdom", "the castle and its keep, the giant mushroom, the first course and its goal fort",
     ["peach-castle", "super-mushroom", "course-meadow", "goal-fort"], ["tubes-warp-pipes", "tubes-question-blocks", "tubes-flagpole", "tubes-mushroom-cap"]),
    ("kart", "The Kart Circuit", "a black loop with red and white bends, the start gantry, the grandstand and the pit garage",
     ["grandstand", "pit-garage"], ["tubes-kart", "streets"]),
    ("dreamland", "Dream Land", "Kirby's house and the Warp Star pond", ["kirby-house", "warp-star-pond"], []),
    ("pokemon", "The Pokémon village", "the healing centre, the gym, the professor's lab and the route pond",
     ["healing-centre", "gym", "professor-lab", "route-pond"], []),
    ("history", "The History Walk and the Museum", "four pavilions of the company's story leading to the museum at the heart",
     ["hanafuda-house", "game-and-watch", "family-computer", "handheld", "museum"], []),
    ("inkopolis", "Inkopolis", "two bright towers over a plaza", ["inkopolis-tower", "ink-spire", "inkopolis-plaza"], []),
    ("village", "The animal village", "Resident Services, the shop, the town square and the orchard",
     ["resident-services", "village-shop", "town-square", "orchard"], []),
    ("hyrule", "Hyrule's woods", "the Lost Woods clearing and its blade, the Temple of Time, the Sage's Spire",
     ["lost-woods", "master-sword", "temple-of-time", "sages-spire"], []),
    ("zebes", "The sands of Zebes", "the landing pad and its hovering gunship, a Chozo statue and the Chozo ruins",
     ["landing-pad", "chozo-statue", "chozo-ruins"], ["tubes-gunship"]),
    ("jungle", "The Kong jungle", "two treehouses and their rope bridges, the barrel tower, the old ape's cabin and the banana hoard",
     ["kong-treehouse", "little-treehouse", "old-ape-cabin", "barrel-tower", "banana-hoard"], ["tubes-rope-bridges"]),
]


def main() -> None:
    design, steps, _ = factory.blueprint(ROOT, NAME)
    world = json.loads((ROOT / "runs/local/world.json").read_text(encoding="utf-8"))
    info = factory.summary(design, steps)
    problems = factory.check(design, steps, world)
    terrain = world["terrain"]
    width = int(world.get("width", 128))
    nodes = {(int(r["x"]), int(r["y"])): str(r["kind"]) for r in world.get("resources") or []}
    centres = {((b := lot_bounds(lid))[0] + 2, b[1] + 2) for lid in LOTS}
    by_id = {str(s["id"]): s for s in design["sections"]}
    district_of = {sid: d[0] for d in DISTRICTS for sid in d[3]} | {sec: d[0] for d in DISTRICTS for sec in d[4]}
    assert set(by_id) == {sid for d in DISTRICTS for sid in d[3]}, "every section belongs to one district"

    closed: dict[tuple[int, int], str] = {}
    mat_blocks: Counter[str] = Counter()
    plinth = 0
    for s in steps:
        if s["kind"] != "place":
            continue
        a = s["action"]
        mat_blocks[str(a["material"])] += int(s["cells"])
        if ": foundation (" in s["name"]:
            plinth += int(s["cells"])
        for x, y, z in _box_cells(a):
            if z < 6 and not (a.get("shape") in ("slab", "slope") and z == 0):
                closed.setdefault((x // 4, y // 4), s["section"])
    under = sorted(t for t in closed if t in nodes)

    number = {}
    sections = []
    for d in DISTRICTS:
        for sid in d[3]:
            sec = by_id[sid]
            number[sid] = len(number) + 1
            x0, y0, x1, y1 = (int(v) for v in sec["tiles"])
            tiles = {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
            sv = info["sections"][sid]
            kind = "deck" if sec["style"] == "treehouse" else "open" if sec["style"] in FLAT else "solid"
            sections.append({
                "n": number[sid], "id": sid, "name": sec["name"], "district": d[0], "style": sec["style"].replace("_", " "),
                "tiles": [x0, y0, x1, y1], "w": x1 - x0 + 1, "h": y1 - y0 + 1, "top": sv["top"], "blocks": sv["blocks"], "steps": sv["steps"],
                "sign": [int(sec["sign"]["x"]), int(sec["sign"]["y"])], "text": sec["sign"]["text"], "kind": kind,
                "trunks": [[int(x), int(y)] for x, y in sec.get("trunks") or []], "plinth": max((k for row in sec.get("foundation") or [] for k in row), default=0),
                "nodesUnder": len([t for t in under if t in tiles]),
            })
    districts = []
    for key, title, blurb, ids, extra in DISTRICTS:
        secs = set(ids) | set(extra)
        ground = set()
        for sid in ids:
            x0, y0, x1, y1 = by_id[sid]["tiles"]
            ground |= {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
        lots = sorted({lot_id(x, y) for x, y in ground})
        districts.append({
            "key": key, "title": title, "blurb": blurb, "sections": [number[s] for s in ids], "tiles": len(ground), "lots": lots,
            "blocks": sum(int(s["cells"]) for s in steps if s["section"] in secs), "steps": sum(1 for s in steps if s["section"] in secs),
            "extraBlocks": sum(int(s["cells"]) for s in steps if s["section"] in set(extra)),
        })

    tubes = []
    for t in design.get("tubes") or []:
        pts = []
        for bx, by, _bz in t["path"]:
            p = [round((bx + 0.5) / 4, 3), round((by + 0.5) / 4, 3)]
            if not pts or pts[-1] != p:
                pts.append(p)
        if len(pts) == 1:  # a vertical pipe or pole: a dot on the map
            pts.append([pts[0][0] + 0.001, pts[0][1]])
        zs = [int(p[2]) for p in t["path"]]
        tubes.append({"name": t["name"], "color": t["color"], "size": int(t.get("size", 1) or 1), "path": pts, "z": [min(zs), max(zs) + int(t.get("size", 1) or 1) - 1],
                      "district": district_of.get(str(t.get("section")), "mushroom"), "ground": min(zs) == 0})
    streets = [{"name": s["name"], "tiles": [int(v) for v in s["tiles"]], "color": s["block"][1]} for s in design.get("streets") or []]

    ground_union = set()
    for sec in design["sections"]:
        x0, y0, x1, y1 = sec["tiles"]
        ground_union |= {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}

    structures = [[int(s["x"]), int(s["y"]), str(s["type"])] for s in world.get("structures") or []
                  if X0 <= int(s["x"]) <= X1 and Y0 <= int(s["y"]) <= Y1 and (int(s["x"]), int(s["y"])) not in centres]
    node_list = [[x, y, k, 1 if (x, y) in closed else 0] for (x, y), k in sorted(nodes.items()) if X0 <= x <= X1 and Y0 <= y <= Y1]

    order = []
    for path in sorted((ROOT / "teams").glob("*.yaml")):
        team = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        pipe = team.get("pipeline") or {}
        if not pipe.get("blueprint"):
            continue
        seq = [str(pipe["blueprint"])] + [str(n) for n in pipe.get("next_blueprint") or []]
        works = []
        for name in seq:
            d2, st2, _ = factory.blueprint(ROOT, name)
            done = factory.load_ledger(ROOT, factory.ledger_name(d2, name)).get("done") or {}
            works.append({"id": name, "name": str(d2.get("name") or name), "steps": len(st2), "done": len([k for k in done if k in {s["id"] for s in st2}]),
                          "blocks": factory.summary(d2, st2)["blocks"]})
        builders = pipe.get("builders") or {}
        order.append({"team": str(team.get("name") or path.stem), "slug": path.stem, "builders": len(builders) if isinstance(builders, dict) else len(builders or []), "works": works})
    order.sort(key=lambda o: -len(o["works"]))

    data = {
        "bounds": [X0, Y0, X1, Y1], "site": list(SITE), "tick": int(world.get("tick", 0)),
        "terrain": ["".join(terrain[y * width + x] for x in range(X0, X1 + 1)) for y in range(Y0, Y1 + 1)],
        "lots": [[lid, *lot_bounds(lid)] for lid in LOTS], "centres": sorted([list(c) for c in centres]),
        "nodes": node_list, "structures": structures, "sections": sections, "districts": districts, "tubes": tubes, "streets": streets,
        "totals": {
            "sections": len(design["sections"]), "districts": len(DISTRICTS), "styles": len({s["style"] for s in design["sections"]}),
            "tiles": len(ground_union), "siteTiles": (SITE[2] - SITE[0] + 1) * (SITE[3] - SITE[1] + 1), "blocks": info["blocks"], "steps": info["steps"],
            "tallest": info["tallest"] - 1, "items": dict(info["materials"]), "matBlocks": dict(mat_blocks), "plinth": plinth,
            "nodesUnder": dict(Counter(nodes[t] for t in under)), "problems": len(problems), "tubes": len(design.get("tubes") or []),
            "streetTiles": sum((s["tiles"][2] - s["tiles"][0] + 1) * (s["tiles"][3] - s["tiles"][1] + 1) for s in streets), "signs": len(sections),
        },
        "order": order,
    }
    page = (HERE / "template.html").read_text(encoding="utf-8")
    literal = json.dumps(data, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    out = HERE / "nintendo-land-plan.html"
    out.write_text(page.replace("__DATA__", literal), encoding="utf-8", newline="\n")
    print(f"written {out} ({out.stat().st_size} bytes): {len(sections)} sections, {data['totals']['tiles']} tiles, {info['blocks']} blocks, {len(problems)} problems")


if __name__ == "__main__":
    main()
