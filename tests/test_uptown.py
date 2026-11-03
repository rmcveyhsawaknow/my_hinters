"""Uptown Manhattan: the Atelier's third New York replica, north of Central Park, every building with a sign beside it (the owner, 2026-11-03)."""

import json
from pathlib import Path

from hglab import factory
from hglab.lots import lot_anchor, lot_id

ROOT = Path(__file__).resolve().parents[1]
SEGMENTS = {
    "nyc-uptown-west": ["D03-NW", "D03-NE", "D03-SW", "D03-SE"],
    "nyc-uptown-east": ["E03-NW", "E03-NE", "E03-SW", "E03-SE", "F03-NW", "F03-SW"],
}
LOTS = [lid for seg in SEGMENTS.values() for lid in seg]
WATER = {(43, 29), (44, 29), (43, 30), (44, 30)}  # the pocket of shallow water at the site's north edge
NODES = {  # the site's nodes in the survey of tick 153228 (no stone, no ore)
    (37, 30): "berries", (52, 30): "fiber", (30, 32): "wood", (34, 32): "wood", (37, 32): "berries", (35, 33): "wood",
    (30, 34): "wood", (34, 34): "wood", (39, 34): "berries", (40, 34): "fiber", (35, 35): "wood", (40, 35): "berries",
    (37, 36): "berries", (38, 36): "fiber", (34, 37): "wood", (39, 37): "berries", (35, 38): "berries", (36, 38): "fiber",
    (37, 38): "berries", (39, 38): "fiber", (52, 38): "fiber", (54, 38): "berries", (31, 39): "wood", (33, 39): "wood",
    (37, 39): "fiber", (38, 39): "berries", (54, 39): "fiber",
}


def _bp():
    return factory.blueprint(ROOT, "uptown")


def _fixture_world():
    rows = (ROOT / "tests/fixtures/world/terrain.txt").read_text(encoding="utf-8").splitlines()
    structures = json.loads((ROOT / "tests/fixtures/world/structures.json").read_text(encoding="utf-8"))
    return {"terrain": rows, "structures": structures}


def _tiles(rect):
    x0, y0, x1, y1 = (int(v) for v in rect)
    return {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}


def test_uptown_keeps_every_rule_a_pack_can_pay_and_riverside_church_is_tallest():
    design, steps, _ = _bp()
    assert factory.check(design, steps) == [] and factory.check(design, steps, _fixture_world()) == []  # reach, support, ceiling, terrain, plots
    assert all(s["items"] <= factory.PACK_LIMIT and s["box_cells"] <= factory.PACK_CELLS for s in steps)  # a pack pays for any step
    assert design["name"] == "Uptown Manhattan" and design["title"] == "the Uptown blueprint" and design["team"] == "atelier"
    assert design["commute"] is True and design["foundation_block"] == ["stone", "grey"] and design["plots"] == ["D03", "E03", "F03"]
    info = factory.summary(design, steps)
    assert info["materials"].get("ore", 0) == 0  # ore is scarce: no metal anywhere, the doors are wood
    assert 12 <= len(design["sections"]) <= 16
    assert {"cloisters", "riverside-church", "grants-tomb", "low-library", "st-john-the-divine", "amnh", "rose-center", "apollo", "guggenheim", "harlem-meer", "streets"} <= set(info["sections"])
    tops = {sec: v["top"] for sec, v in info["sections"].items()}
    assert tops["riverside-church"] == max(tops.values()) < factory.TOP_LEVEL  # the tallest here, and under the Empire State's mast
    assert tops["riverside-church"] > tops["st-john-the-divine"] > tops["low-library"] >= tops["apollo"]
    midtown = factory.summary(*factory.blueprint(ROOT, "midtown")[:2])["sections"]
    assert all(top < midtown["empire-state"]["top"] for top in tops.values())  # nothing taller than Midtown's Empire State Building


def test_every_building_has_a_sign_beside_it_off_the_nodes_the_claim_signs_and_the_streets():
    design, steps, _ = _bp()
    signs = {s["section"]: s for s in steps if s["kind"] == "build" and s["action"].get("type") == "sign"}
    sections = {str(s["id"]): s for s in design["sections"]}
    assert set(signs) == set(sections) and all(s["beside"] for s in signs.values())  # one sign per building, the section's last step
    assert len({s["action"]["text"] for s in signs.values()}) == len(signs) and all(3 <= len(s["action"]["text"]) <= 200 for s in signs.values())
    anchors = {lot_anchor(lid) for lid in LOTS}
    streets = set().union(*(_tiles(st["tiles"]) for st in design["streets"]))
    footprints = set().union(*(_tiles(s["tiles"]) for s in design["sections"]))
    for sid, sign in signs.items():
        where = (sign["action"]["x"], sign["action"]["y"])
        assert where not in anchors | streets | footprints | WATER and where not in NODES, sid
        assert lot_id(*where) in LOTS, sid
        assert steps[[s["id"] for s in steps].index(sign["id"]) - 1]["section"] == sid  # the sign follows its building's last box


def test_footprints_close_no_node_claim_sign_street_or_water_and_a_tube_closes_only_its_piers():
    design, steps, _ = _bp()
    anchors = {lot_anchor(lid) for lid in LOTS}
    streets = set().union(*(_tiles(st["tiles"]) for st in design["streets"]))
    closed: dict[tuple[int, int], str] = {}
    for step in steps:
        if step["kind"] != "place":
            continue
        tiles = _tiles(step["tiles"])
        assert not tiles & WATER, step["id"]  # no block on water: (43,30) and (44,30) stay free
        floor = str(step["action"].get("shape")) == "slab" and int(step["action"]["bz"]) == 0
        if int(step["action"]["bz"]) < 6 and not floor:
            closed.update({t: step["section"] for t in tiles})
    assert not set(closed) & anchors and not set(closed) & streets and not set(closed) & set(NODES)  # every node stays open
    piers = {t for t, sec in closed.items() if sec == "park-avenue-viaduct"}
    assert piers == {(46, 35), (46, 30)}  # the viaduct is at level 6 over 125th Street and the station's roof
    viaduct = [s for s in steps if s["section"] == "park-avenue-viaduct"]
    assert any(r.startswith("harlem-125th-station:") for s in viaduct for r in s["rests_on"])  # it rests on the station's roof
    for s in [s for s in steps if s["section"] == "streets"]:
        assert s["action"]["shape"] == "slab" and s["action"]["bz"] == 0  # streets close no tile
    for s in [s for s in steps if s["section"] in ("morningside-park", "harlem-meer") and s["kind"] == "place"]:
        floor = s["action"].get("shape") == "slab" and s["action"]["bz"] == 0
        assert floor or "tree" in s["name"], s["id"]  # the lawn and the pond are floors; only the trees stand up


def test_every_step_stands_on_the_ten_lots_and_every_section_within_one_segment():
    design, steps, _ = _bp()
    assert design["land"] == {"client": "Plumbline", "registrar": "LandBroker", "lots": LOTS}
    lots = {lid for s in steps for lid in factory.step_lots(s)}
    assert lots == set(LOTS)  # every step on the ten lots bought, every lot built on
    for sec in design["sections"]:
        under = {lot_id(x, y) for x, y in _tiles(sec["tiles"])}
        assert any(under <= set(seg) for seg in SEGMENTS.values()), sec["id"]  # a building is never half bought
    for sec in design["sections"]:
        x0, y0, x1, y1 = sec["tiles"]
        assert x1 - x0 < 5 and y1 - y0 < 5 and sec.get("foundation") is not None, sec["id"]  # within reach, surveyed


def test_the_segments_are_requested_of_the_office_after_central_park():
    from hglab.land import load_ledger

    requests = {r["id"]: r for r in load_ledger(ROOT).get("site_requests") or []}
    assert requests["nyc-uptown-west"]["after"] == "nyc-park-north" and requests["nyc-uptown-east"]["after"] == "nyc-uptown-west"
    for rid, lots in SEGMENTS.items():
        assert requests[rid]["client"] == "Plumbline" and requests[rid]["lots"] == lots and requests[rid]["wants"] == ["stone"]
    taken = {lid for rid, r in requests.items() if not rid.startswith("nyc-uptown") for lid in r.get("lots") or []}
    assert not taken & set(LOTS)  # no other request asks for Uptown's ground


def test_central_park_and_midtown_are_untouched_and_uptown_lies_clear_of_them():
    park, park_steps, _ = factory.blueprint(ROOT, "central-park")
    assert len(park_steps) == 198 and sum(s["cells"] for s in park_steps) == 2339 and factory.check(park, park_steps) == []
    assert park["land"]["lots"] == ["D05-SW", "D05-SE", "E05-SW", "E05-SE", "D05-NE", "E05-NW", "D04-NE", "E04-NW", "E04-SE"]
    _uptown, uptown_steps, _ = _bp()
    ours = set().union(*(_tiles(s["tiles"]) for s in uptown_steps))
    for name in ("central-park", "midtown", "lower-manhattan"):
        _, theirs, _ = factory.blueprint(ROOT, name)
        assert not ours & set().union(*(_tiles(s["tiles"]) for s in theirs)), name
