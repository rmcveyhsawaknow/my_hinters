"""Data for the plan page of the northern New York replica (Midtown, Central Park, Uptown), inlined into template.html.

Run with the project venv from anywhere:
    .venv/Scripts/python <this folder>/make_plan.py
Reads (never writes) the repository: the three blueprints (hglab.factory.blueprint), the public world snapshot the
local runtime keeps (runs/local/world.json), the land office's site requests (config/plots.yaml), the teams, and
the blueprint ledgers (hglab.factory.load_ledger) for progress. Writes nyc-expansion-plan.html beside this script.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r"C:\Users\rjmcv\source\repos\my_hinters")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hglab import factory
from hglab.land import load_ledger as load_plots
from hglab.lots import lot_anchor, lot_bounds, lot_id
from hglab.persona import load_personas, load_team

DESIGNS = [("midtown", "Midtown"), ("central-park", "Central Park"), ("uptown", "Uptown")]
BOUNDS = (27, 28, 56, 76)  # x0, y0, x1, y1: Uptown's north edge to Lower Manhattan's
OFFICE = ["land-broker", "office-quarrier", "office-feller", "office-reaper", "office-drayman", "office-steward"]


def _tiles(rect):
    x0, y0, x1, y1 = (int(v) for v in rect)
    return [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]


def main() -> None:
    world = json.loads((ROOT / "runs/local/world.json").read_text(encoding="utf-8"))
    width = int(world.get("width", 128))
    terrain = world["terrain"]
    x0, y0, x1, y1 = BOUNDS
    rows = ["".join(terrain[y * width + x] for x in range(x0, x1 + 1)) for y in range(y0, y1 + 1)]
    inside = lambda x, y: x0 <= x <= x1 and y0 <= y <= y1
    nodes = [[int(r["x"]), int(r["y"]), str(r["kind"])] for r in world.get("resources") or [] if inside(int(r["x"]), int(r["y"]))]
    structures = []
    for s in world.get("structures") or []:
        if not inside(int(s["x"]), int(s["y"])):
            continue
        text = str(s.get("text") or "")
        claim = s.get("type") == "sign" and str(s.get("owner")) == "LandBroker" and text.startswith("Lot ")
        structures.append({"x": int(s["x"]), "y": int(s["y"]), "type": str(s["type"]), "owner": str(s.get("owner") or ""), "claim": claim})

    plots = load_plots(ROOT)
    requests = [r for r in plots.get("site_requests") or [] if str(r.get("id", "")).startswith(("nyc-midtown", "nyc-park", "nyc-uptown"))]
    personas = load_personas(ROOT)
    name_of = lambda slug: personas[slug].name if slug in personas else slug

    designs, sections_out = [], []
    lot_design: dict[str, str] = {}
    for key, label in DESIGNS:
        design, steps, _ = factory.blueprint(ROOT, key)
        ledger = factory.load_ledger(ROOT, factory.ledger_name(design, key))
        done = set(ledger.get("done") or {})
        wanted = factory.land_wanted(ROOT, design, world.get("structures") or [])
        info = factory.summary(design, steps)
        for lid in design["land"]["lots"]:
            lot_design[lid] = key
        seg_of = {lid: r["id"] for r in requests for lid in r["lots"]}
        for n, sec in enumerate(design["sections"], start=1):
            sid = str(sec["id"])
            own = [s for s in steps if s["section"] == sid]
            lots = sorted({lot_id(x, y) for x, y in _tiles(sec["tiles"])})
            mats = factory.materials(own)
            sign = sec.get("sign") or {}
            plinth = max((int(v) for row in sec.get("foundation") or [] for v in row), default=0)
            sections_out.append({
                "design": key, "no": n, "id": sid, "name": str(sec.get("name", sid)), "style": str(sec.get("style")),
                "tiles": [int(v) for v in sec["tiles"]], "top": max((int(s.get("top", 0)) for s in own), default=0),
                "blocks": sum(int(s.get("cells", 0)) for s in own), "steps": len(own), "done": sum(1 for s in own if s["id"] in done),
                "mats": {k: int(v) for k, v in sorted(mats.items())}, "plinth": plinth,
                "sign": [int(sign["x"]), int(sign["y"])] if sign else None, "signText": str(sign.get("text") or ""),
                "lots": lots, "segment": sorted({seg_of.get(lid, "-") for lid in lots}),
                "open": sec.get("style") in ("park", "pool"),
            })
        streets = [{"name": st["name"], "tiles": [int(v) for v in st["tiles"]]} for st in design.get("streets") or []]
        street_steps = [s for s in steps if s["section"] == "streets"]
        tubes = []
        for tb in design.get("tubes") or []:
            pts = [[int(p[0]) // 4, int(p[1]) // 4, int(p[2])] for p in tb["path"]]
            tubes.append({"name": tb["name"], "section": tb.get("section"), "path": pts, "steps": sum(1 for s in steps if s["section"] == tb.get("section"))})
        mats = factory.materials(steps)
        designs.append({
            "key": key, "label": label, "name": design["name"], "plots": design["plots"], "lots": design["land"]["lots"],
            "client": design["land"]["client"], "registrar": design["land"]["registrar"],
            "sections": len(design["sections"]), "area": sum(len(_tiles(s["tiles"])) for s in design["sections"]),
            "steps": len(steps), "blocks": info["blocks"], "tallest": max(int(s.get("top", 0)) for s in steps),
            "done": len(done & {s["id"] for s in steps}), "mats": {k: int(v) for k, v in sorted(mats.items())},
            "need": {k: int(v) for k, v in sorted(factory.materials(steps, done).items())},
            "streets": streets, "streetBlocks": sum(int(s["cells"]) for s in street_steps), "tubes": tubes,
            "problems": len(factory.check(design, steps, world)), "streetTiles": len({t for st in streets for t in _tiles(st["tiles"])}),
            "wanted": sorted(wanted), "ledger": f"runs/local/blueprints/{factory.ledger_name(design, key)}.json",
            "story": str(design.get("story") or ""),
        })

    segments = []
    for order, r in enumerate(requests, start=1):
        lots = [str(l) for l in r["lots"]]
        key = lot_design.get(lots[0], "")
        wanted = next((set(d["wanted"]) for d in designs if d["key"] == key), set())
        segments.append({
            "order": order, "id": r["id"], "design": key, "after": r.get("after"), "lots": lots, "wants": r.get("wants") or [],
            "note": str(r.get("note") or ""), "deeded": sum(1 for l in lots if l not in wanted), "client": r.get("client"),
        })

    lots = []
    for lid, key in lot_design.items():
        bx0, by0, bx1, by1 = lot_bounds(lid)
        lots.append({"id": lid, "design": key, "rect": [bx0, by0, bx1, by1], "anchor": list(lot_anchor(lid)), "segment": next((s["id"] for s in segments if lid in s["lots"]), "")})
    context = []  # Lower Manhattan's lots that show at the foot of the drawing
    lm = factory.load_design(ROOT, "lower-manhattan")
    for lid in lm["land"]["lots"]:
        bx0, by0, bx1, by1 = lot_bounds(lid)
        if by0 <= y1:
            context.append({"id": lid, "rect": [bx0, by0, bx1, min(by1, y1)]})

    def team_info(slug: str) -> dict:
        team = load_team(ROOT, slug)
        pipe = team.extra.get("pipeline") or {}
        return {"designs": factory.team_designs(team), "builders": {name_of(k): v for k, v in (pipe.get("builders") or {}).items()}}

    office, atelier, cf = team_info("exchange"), team_info("atelier"), team_info("chocolate-factory")
    crew_team = load_team(ROOT, "chocolate-factory")
    crew = [name_of(m) for m in crew_team.members if m != "grandpa-joe"]
    data = {
        "bounds": list(BOUNDS), "terrain": rows, "nodes": nodes, "structures": structures, "tick": int(world.get("tick", 0)),
        "designs": designs, "sections": sections_out, "segments": segments, "lots": lots, "context": context,
        "who": {
            "office": {"names": [name_of(m) for m in OFFICE], "designs": office["designs"], "builders": office["builders"]},
            "atelier": {"names": ["Plumbline"], "designs": atelier["designs"]},
            "factory": {"names": crew, "designs": cf["designs"]},
        },
        "totals": {
            "sections": sum(d["sections"] for d in designs), "area": sum(d["area"] for d in designs), "steps": sum(d["steps"] for d in designs),
            "blocks": sum(d["blocks"] for d in designs), "done": sum(d["done"] for d in designs), "lots": len(lots),
            "mats": dict(sum((Counter(d["mats"]) for d in designs), Counter())),
        },
    }
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = (HERE / "template.html").read_text(encoding="utf-8").replace("__DATA__", blob)
    (HERE / "nyc-expansion-plan.html").write_text(html, encoding="utf-8", newline="\n")
    (HERE / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"tick {data['tick']}: {data['totals']['sections']} sections, {data['totals']['blocks']} blocks, {len(segments)} segments, {len(html)} bytes")


if __name__ == "__main__":
    main()
