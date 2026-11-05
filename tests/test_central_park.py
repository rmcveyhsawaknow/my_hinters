"""Central Park: the larger replica's park round the inland lake, every building with a sign beside it (the owner, 2026-11-02)."""

from pathlib import Path

from hglab import factory
from hglab.lots import lot_anchor, lot_bounds
from hglab.persona import load_team

ROOT = Path(__file__).resolve().parents[1]
SEGMENTS = {"nyc-park-south": ["D05-SW", "D05-SE", "E05-SW", "E05-SE"], "nyc-park-north": ["D05-NE", "E05-NW", "D04-NE", "E04-NW", "E04-SE"]}
LAKE = {(45, 48), (45, 49), (46, 49), (47, 49), (48, 49), (49, 49), (43, 50), (43, 51), (44, 50), (44, 51)}  # the lots' water tiles (tick 143104)


def _bp():
    return factory.blueprint(ROOT, "central-park")


def test_the_park_keeps_every_rule_a_pack_can_pay_and_the_obelisk_is_tallest():
    design, steps, _ = _bp()
    assert factory.check(design, steps) == []  # boxes within a builder's reach, supported in order, every sign beside its building
    assert all(s["items"] <= factory.PACK_LIMIT and s["box_cells"] <= factory.PACK_CELLS for s in steps)
    info = factory.summary(design, steps)
    assert info["materials"].get("ore", 0) == 0  # ore is scarce: no metal anywhere
    assert {"sheep-meadow", "dairy", "carousel", "wollman-rink", "zoo", "bethesda-terrace", "angel-of-the-waters", "alice", "belvedere", "boathouse", "strawberry-fields", "imagine-mosaic", "balto", "great-lawn", "obelisk", "met", "streets"} <= set(info["sections"])
    assert info["sections"]["obelisk"]["top"] == max(v["top"] for k, v in info["sections"].items() if k != "obelisk") + 1 or info["sections"]["obelisk"]["top"] >= 12
    assert info["sections"]["belvedere"]["top"] < 8 and info["sections"]["sheep-meadow"]["top"] <= 5


def test_every_building_has_a_sign_beside_it_off_the_claim_signs_and_the_water():
    design, steps, _ = _bp()
    signs = [s for s in steps if s["kind"] == "build" and s["action"]["type"] == "sign"]
    assert len(signs) == len(design["sections"]) and all(s["beside"] for s in signs)
    assert all(0 < len(s["action"]["text"]) <= 200 for s in signs) and len({s["action"]["text"] for s in signs}) == len(signs)
    anchors = {lot_anchor(lid) for lid in design["land"]["lots"]}
    assert not {(s["action"]["x"], s["action"]["y"]) for s in signs} & (anchors | LAKE)
    for step in steps:
        x0, y0, x1, y1 = step["tiles"]
        tiles = {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
        assert not tiles & LAKE, step["id"]  # no block on water
        floor = step["kind"] == "place" and str(step["action"].get("shape")) == "slab" and int(step["action"]["bz"]) == 0
        if step["kind"] == "place" and int(step["action"]["bz"]) < 6 and not floor:
            assert not tiles & anchors, step["id"]  # only a lawn's slab or a path lies over the office's claim sign


def test_every_step_stands_on_the_nine_lots_and_lawns_close_no_tile():
    design, steps, _ = _bp()
    lots = {lid for s in steps for lid in factory.step_lots(s)}
    assert lots == set(design["land"]["lots"]) == {lid for seg in SEGMENTS.values() for lid in seg}
    for s in steps:
        x0, y0, x1, y1 = s["tiles"]
        assert any(lot_bounds(lid)[0] <= x0 and x1 <= lot_bounds(lid)[2] and lot_bounds(lid)[1] <= y0 and y1 <= lot_bounds(lid)[3] for lid in design["land"]["lots"]) or s["section"] in ("great-lawn", "streets"), s["id"]
    for s in steps:
        if s["section"] in ("sheep-meadow", "great-lawn", "strawberry-fields") and s["kind"] == "place" and "tree" not in s["name"] and "support" not in s["name"]:
            assert str(s["action"].get("shape")) == "slab" and int(s["action"]["bz"]) == 0, s["id"]  # a lawn, a hedge or a path: a floor
    streets = [s for s in steps if s["section"] == "streets"]
    assert streets and all(s["action"]["shape"] == "slab" and s["action"]["bz"] == 0 for s in streets)


def test_the_atelier_takes_the_park_up_after_midtown_on_the_office_s_ground():
    from hglab.land import load_ledger

    requests = {r["id"]: r for r in load_ledger(ROOT).get("site_requests") or []}
    for rid, lots in SEGMENTS.items():
        assert requests[rid]["client"] == "Plumbline" and requests[rid]["lots"] == lots
    assert factory.team_designs(load_team(ROOT, "atelier")) == ["lower-manhattan", "midtown", "central-park", "uptown", "nintendo-land", "signposts", "halloween"]  # Uptown and Nintendo Land follow (2026-11-03), the signposts and Halloween last (2026-11-05)
    assert set(_bp()[0]["land"]["lots"]) <= set(load_team(ROOT, "exchange").extra["pipeline"]["claims"]["exclude"])
