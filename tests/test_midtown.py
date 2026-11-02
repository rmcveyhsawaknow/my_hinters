"""Midtown Manhattan: the Atelier's larger replica north of Lower Manhattan, every building with a sign beside it (owner, 2026-11-02)."""

from pathlib import Path

from hglab import factory
from hglab.lots import lot_anchor, lot_id

ROOT = Path(__file__).resolve().parents[1]
LOTS = ["D06-NW", "D06-NE", "E06-NW", "E06-NE", "D06-SE", "E06-SW", "E06-SE", "E07-NW", "E07-NE"]
SEGMENTS = {"nyc-midtown-south": ["E07-NW", "E07-NE", "E06-SW", "E06-SE"], "nyc-midtown-north": ["D06-NW", "D06-NE", "E06-NW", "E06-NE", "D06-SE"]}


def _bp():
    return factory.blueprint(ROOT, "midtown")


def test_midtown_keeps_every_rule_a_pack_can_pay_and_the_empire_state_is_tallest():
    design, steps, _ = _bp()
    assert factory.check(design, steps) == []  # boxes within a builder's reach, supported in order, every sign beside its building
    assert all(s["items"] <= factory.PACK_LIMIT and s["box_cells"] <= factory.PACK_CELLS for s in steps)
    info = factory.summary(design, steps)
    assert info["materials"].get("ore", 0) == 0  # ore is scarce: no metal anywhere
    assert {"empire-state", "chrysler", "rockefeller", "grand-central", "nypl", "st-patricks", "flatiron", "msg", "bryant-park", "streets"} <= set(info["sections"])
    tops = {sec: v["top"] for sec, v in info["sections"].items()}
    assert tops["empire-state"] == factory.TOP_LEVEL and all(v < tops["empire-state"] for sec, v in tops.items() if sec != "empire-state")  # the tallest, a mast to the ceiling
    assert tops["chrysler"] >= tops["rockefeller"] and tops["grand-central"] < 8
    lots = {lid for s in steps for lid in factory.step_lots(s)}
    assert lots == set(design["land"]["lots"]) == set(LOTS) == {lid for seg in SEGMENTS.values() for lid in seg}  # every step on the nine lots bought, every lot built on
    streets = [s for s in steps if s["section"] == "streets"]
    assert streets and all(s["action"]["shape"] == "slab" and s["action"]["bz"] == 0 for s in streets)  # streets close no tile


def test_every_building_has_a_sign_beside_it_and_none_stands_on_a_claim_sign():
    design, steps, _ = _bp()
    signs = {s["section"]: s for s in steps if s["kind"] == "build" and s["action"].get("type") == "sign"}
    sections = {str(s["id"]): s for s in design["sections"]}
    assert set(signs) == set(sections)  # one sign per building and monument, the section's last step
    anchors = {lot_anchor(lid) for lid in LOTS}
    for sid, section in sections.items():
        x0, y0, x1, y1 = (int(v) for v in section["tiles"])
        sx, sy = signs[sid]["action"]["x"], signs[sid]["action"]["y"]
        assert x0 - 1 <= sx <= x1 + 1 and y0 - 1 <= sy <= y1 + 1 and not (x0 <= sx <= x1 and y0 <= sy <= y1)  # beside, not inside
        assert 3 <= len(signs[sid]["action"]["text"]) <= 200 and signs[sid]["costs"] == {"wood": 1}
        assert not any((x, y) in anchors for x in range(x0, x1 + 1) for y in range(y0, y1 + 1))  # the office's claim sign keeps its tile
        assert (sx, sy) not in anchors and all(lot_id(x, y) in LOTS for x in range(x0, x1 + 1) for y in range(y0, y1 + 1))
    assert steps[[s["id"] for s in steps].index(signs["empire-state"]["id"]) - 1]["section"] == "empire-state"  # the sign follows its building's last box


def test_the_segments_are_requested_of_the_office_after_lower_manhattan():
    from hglab.land import load_ledger

    requests = {r["id"]: r for r in load_ledger(ROOT).get("site_requests") or []}
    assert requests["nyc-midtown-south"]["after"] == "nyc-wtc" and requests["nyc-midtown-north"]["after"] == "nyc-midtown-south"
    for rid, lots in SEGMENTS.items():
        assert requests[rid]["client"] == "Plumbline" and requests[rid]["lots"] == lots
