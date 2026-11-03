"""The factory's East Works (the owner, 2026-11-03): the factory grows by twice what stood, in buildings and in area."""

from pathlib import Path

from hglab import factory
from hglab.lots import lot_id
from hglab.persona import load_team

ROOT = Path(__file__).resolve().parents[1]
OLD = {"elevator", "lookout", "mill", "terrace", "candy", "packing", "silo", "boiler", "mast"}


def _area(sections):
    return sum((s["tiles"][2] - s["tiles"][0] + 1) * (s["tiles"][3] - s["tiles"][1] + 1) for s in sections)


def test_the_factory_holds_three_times_the_buildings_and_three_times_their_ground():
    design, steps, _ = factory.blueprint(ROOT, "chocolate-factory")
    old = [s for s in design["sections"] if s["id"] in OLD]
    east = [s for s in design["sections"] if s["id"] not in OLD]
    assert len(old) == 9 and len(east) == 18 and len(design["sections"]) >= 3 * len(old)  # 9 buildings, and twice as many again
    assert _area(old) == 67 and _area(design["sections"]) >= 3 * _area(old)  # 67 tiles under buildings, now 243
    assert {lot_id(x, y)[:3] for s in east for x in range(s["tiles"][0], s["tiles"][2] + 1) for y in range(s["tiles"][1], s["tiles"][3] + 1)} <= {"K06", "K07", "K08", "K09"}
    assert design["commute"] is True  # a builder far from every ready step carries the next one's material there
    signs = [s for s in steps if s["kind"] == "build" and s["action"]["type"] == "sign"]
    assert len(signs) == 27 and all(s["beside"] for s in signs)  # every building, old and new, has a sign beside it (the owner, 2026-11-02)
    new_steps = [s for s in steps if s["section"] not in OLD and not s["section"].startswith(("campus", "river-west", "river-east", "river-terrace", "tubes-candy", "tubes-packing", "tubes-spine", "tubes-fudge", "tubes-haul", "tubes-sky", "tubes-bay", "tubes-crossing", "depots"))]
    assert factory.materials(new_steps).get("ore", 0) == 0  # ore stays scarce: the new doors are wood
    river = {(x, y) for name, path in design["river"]["branches"].items() if name.startswith("annex") for x, y in path}
    assert design["river"]["widths"] == {"annex-west": 2, "annex-east": 2, "annex-link": 2}
    for s in east:
        x0, y0, x1, y1 = s["tiles"]
        ring = {(x, y) for x in range(x0 - 1, x1 + 2) for y in range(y0 - 1, y1 + 2)} - {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
        assert ring & river, s["id"]  # the river runs along every new building, two cells wide
    assert [(d["x"], d["y"]) for d in design["depots"][3:]] == [(100, 70), (108, 80), (105, 96)]  # materials beside the new works


def test_a_river_branch_may_be_narrower_than_the_rest():
    design = {"sections": [], "river": {"width_cells": 4, "widths": {"narrow": 2}, "branches": {"wide": [[10, 10], [10, 12]], "narrow": [[20, 10], [20, 12]]}}}
    steps = factory.expand(design)
    wide = next(s for s in steps if s["section"] == "river-wide")["action"]
    narrow = next(s for s in steps if s["section"] == "river-narrow")["action"]
    assert (wide["bx"], wide["bx2"]) == (40, 43) and (narrow["bx"], narrow["bx2"]) == (81, 82)  # the band sits in the middle of the tile


def test_the_crew_reaches_the_east_works_and_the_office_keeps_off_them():
    team = load_team(ROOT, "chocolate-factory")
    cfg = team.extra["pipeline"]
    assert cfg["range"] == 40  # a hand at the East Works (up to 38 tiles out) is at the works, not walking back
    _design, steps, _ = factory.blueprint(ROOT, "chocolate-factory")
    covered = {sec for secs in cfg["builders"].values() for sec in secs}
    assert {s["section"] for s in steps} <= covered  # every section, the new ones included, has a builder who raises it first
    exclude = set(load_team(ROOT, "exchange").extra["pipeline"]["claims"]["exclude"])
    assert {f"K{n:02d}-{q}" for n in (6, 7, 8, 9) for q in ("NW", "NE", "SW", "SE")} <= exclude  # never walled, worked or policed by the office


def test_the_east_works_rise_once_the_old_works_stand():
    _design, steps, _ = factory.blueprint(ROOT, "chocolate-factory")
    old_done = {s["id"] for s in steps if s["section"] in OLD and s["action"].get("type") != "sign" or s["section"].startswith(("campus", "tubes-candy", "tubes-packing"))}
    ready = {s["section"] for s in factory.ready_steps(steps, old_done)}
    assert {"gobstopper", "toffee", "nougat", "cocoa-store", "lighthouse", "river-annex-west"} <= ready  # every new building begins at once, in parallel
    assert "tubes-annex-north" not in ready  # a tube waits for the wall it leaves (rests_on)
