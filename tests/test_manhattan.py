"""Lower Manhattan: the Atelier's replica on the south-west shore, built on land bought from the office (owner, 2026-10-27)."""

from pathlib import Path

from hglab import factory
from hglab.lots import lot_id
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView, _draw_price, _plan_site_trade

ROOT = Path(__file__).resolve().parents[1]
GRASS = ["g" * 128] * 128
SEGMENTS = {"nyc-wall-street": ["D08-NE", "E08-NW"], "nyc-battery": ["D08-SE", "E08-SW", "D08-SW", "C08-SE"], "nyc-trinity": ["D08-NW", "C08-NE"], "nyc-wtc": ["D07-SW", "D07-SE", "C07-SE", "E07-SW"]}


def _bp():
    return factory.blueprint(ROOT, "lower-manhattan")


def _deeds(*lots, holder="Plumbline"):
    return [{"type": "sign", "x": 0, "y": i, "owner": "LandBroker", "text": f"Deed {lid}: holder {holder}, registered tick 1 by LandBroker. A public record, not a wall."} for i, lid in enumerate(lots)]


def test_the_replica_keeps_every_rule_a_pack_can_pay_and_one_wtc_is_tallest():
    design, steps, _ = _bp()
    assert factory.check(design, steps) == []  # boxes of at most 256 cells within a builder's reach, supported in order
    assert all(s["items"] <= factory.PACK_LIMIT and s["box_cells"] <= factory.PACK_CELLS for s in steps)
    info = factory.summary(design, steps)
    assert info["materials"].get("ore", 0) == 0  # ore is scarce: no metal anywhere
    assert {"federal-hall", "nyse", "trinity-church", "one-wtc", "woolworth", "battery-park", "castle-clinton", "charging-bull", "streets"} <= set(info["sections"])
    assert info["sections"]["one-wtc"]["top"] == factory.TOP_LEVEL and info["sections"]["federal-hall"]["top"] < 8
    lots = {lid for s in steps for lid in factory.step_lots(s)}
    assert lots == set(design["land"]["lots"]) == {lid for seg in SEGMENTS.values() for lid in seg}  # every step on the twelve lots bought
    streets = [s for s in steps if s["section"] == "streets"]
    assert streets and all(s["action"]["shape"] == "slab" and s["action"]["bz"] == 0 for s in streets)  # streets close no tile


def test_the_four_segments_are_requested_of_the_office_in_order_by_plumbline():
    from hglab.land import load_ledger

    requests = {r["id"]: r for r in load_ledger(ROOT).get("site_requests") or []}
    for rid, lots in SEGMENTS.items():
        assert requests[rid]["client"] == "Plumbline" and requests[rid]["lots"] == lots
    plumbline = load_personas(ROOT)["plumbline"]
    assert plumbline.knobs["house"]["requests"] == list(SEGMENTS) and plumbline.knobs["house"]["style"] == "blueprint"
    claims = load_team(ROOT, "exchange").extra["pipeline"]["claims"]
    assert set(design_lots := _bp()[0]["land"]["lots"]) <= set(claims["exclude"]) and len(design_lots) == 12  # never walled, policed or worked by the office
    state = PersonaState(mood="measuring")
    view = WorldView(x0=20, y0=70, rows=GRASS, full_map=GRASS)
    ask = _plan_site_trade(plumbline, state, {"wood": 5}, (35, 82), view, {"tick": 1000, "you": {"x": 35, "y": 82}, "inbox": []}, "LandBroker")
    assert ask is not None and ask[0][0]["action"] == "whisper" and ask[0][0]["to"] == "LandBroker" and ask[0][0]["text"].startswith("SURVEY REQUEST nyc-wall-street")


def _plumbline_step(structures, position=(35, 80), inventory=None, state=None):
    personas = load_personas(ROOT)
    plumbline = personas["plumbline"]
    team = load_team(ROOT, "atelier")
    observe = {"tick": 90000, "you": {"name": "Plumbline", "x": position[0], "y": position[1], "faction": {"id": 5, "name": "Chocolate Factory"}, "blocks_owned": 0}}
    view = WorldView(x0=position[0] - 6, y0=position[1] - 6, rows=GRASS, full_map=GRASS, structures=[s for s in structures if s.get("type") == "storehouse"], world_structures=list(structures), tick=90000)
    state = state or PersonaState(mood="measuring")
    return factory.plan_step(plumbline, team, state, observe, view, dict(inventory or {"stone": 40, "wood": 20}), position, 3), state


def test_nothing_rises_on_a_lot_the_client_does_not_hold():
    step, state = _plumbline_step([])
    assert step is None and set(state._bp_land) <= set(_bp()[0]["land"]["lots"])  # no deed: the builder waits for the ground
    others, _ = _plumbline_step(_deeds("D08-NE", "E08-NW", holder="Mara"))
    assert others is None  # someone else's deed is not ours
    held, _ = _plumbline_step(_deeds("D08-NE", "E08-NW"))
    assert held is not None and held[2] == "blueprint"
    placed = [a for a in held[0] if a.get("action") == "place"]
    assert placed and all(lot_id(a["bx"] // 4, a["by"] // 4) in ("D08-NE", "E08-NW") for a in placed)  # Wall Street's ground only


def test_a_far_builder_carries_its_material_from_a_faction_store_then_walks_to_the_site():
    deeds = _deeds("D08-NE", "E08-NW")
    store = {"type": "storehouse", "x": 86, "y": 93, "owner": "Toffeetrowel", "policy": "faction", "faction": "Chocolate Factory", "storage": {"stone": 300, "wood": 100}}
    take, _ = _plumbline_step([*deeds, store], position=(86, 92), inventory={"berries": 5})
    assert take is not None and take[0][0]["action"] == "take" and take[0][0]["item"] in ("stone", "wood") and take[0][0]["qty"] <= factory.PACK_LIMIT
    walk, _ = _plumbline_step([*deeds, store], position=(86, 92), inventory={"stone": 40, "wood": 20, "berries": 5})
    assert walk is not None and walk[0][0]["action"] == "move" and walk[0][0]["x"] < 86 and "carrying" in walk[1]  # west toward Wall Street
    unseen = {**store, "storage": None, "policy": None}
    trip, _ = _plumbline_step([*deeds, unseen], position=(40, 82), inventory={"berries": 5})
    assert trip is not None and trip[0][0]["action"] == "move" and trip[0][0]["x"] > 40 and "faction's store" in trip[1]  # at the site, short of stone: to the factory's stores


def test_the_factory_takes_up_lower_manhattan_only_once_the_factory_stands():
    team = load_team(ROOT, "chocolate-factory")
    assert factory.team_designs(team) == ["chocolate-factory", "lower-manhattan"]
    personas = load_personas(ROOT)
    observe = {"tick": 90000, "you": {"name": "MotherPail", "x": 38, "y": 82, "faction": {"id": 5, "name": "Chocolate Factory"}, "blocks_owned": 0}}
    view = WorldView(x0=32, y0=76, rows=GRASS, full_map=GRASS, world_structures=_deeds("D08-NE", "E08-NW"), tick=90000)
    before = factory.plan_step(personas["mrs-bucket"], team, PersonaState(mood="warm"), observe, view, {"stone": 40, "berries": 5}, (38, 82), 3)
    assert before is None or "factory" in before[1]  # the factory is not done: its own design first
    design, steps, _ = factory.blueprint(ROOT, "chocolate-factory")
    factory.mark_done(ROOT, factory.ledger_name(design, "chocolate-factory"), [s["id"] for s in steps], 1, "test")
    after = factory.plan_step(personas["mrs-bucket"], team, PersonaState(mood="warm"), observe, view, {"stone": 40, "berries": 5}, (38, 82), 3)
    assert after is not None and after[2] == "blueprint" and any(a.get("action") == "place" for a in after[0])


def test_the_price_is_fetched_from_a_faction_store_out_of_view():
    plumbline = load_personas(ROOT)["plumbline"]
    store = {"type": "storehouse", "x": 86, "y": 93, "owner": "Toffeetrowel", "faction": "Chocolate Factory"}
    view = WorldView(x0=30, y0=76, rows=GRASS, full_map=GRASS, world_structures=[store], tick=90000)
    bought = {"id": "nyc-wall-street", "lot": "D08-NE", "price": 61, "paid": 0, "currency": "wood"}
    trip = _draw_price(plumbline, PersonaState(mood="measuring"), {"berries": 5}, (40, 82), view, {"you": {"faction": {"name": "Chocolate Factory"}}}, {"Toffeetrowel", "Plumbline"}, "wood", 61, bought)
    assert trip is not None and trip[0][0]["action"] == "move" and "faction's store" in trip[1]
