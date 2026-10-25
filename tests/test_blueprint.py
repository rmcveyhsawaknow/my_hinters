"""The Chocolate Factory blueprint: the world's limits, the order of its steps, its builders and its ledger."""

from pathlib import Path

from hglab import factory
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView

ROOT = Path(__file__).parents[1]
GRASS = ["g" * 128] * 128


def _bp():
    return factory.blueprint(ROOT, "chocolate-factory")


def test_the_blueprint_keeps_every_rule_of_the_world_and_reaches_the_ceiling():
    design, steps, index = _bp()
    assert factory.check(design, steps) == []  # boxes of at most 256 cells within reach, supported in order, no empty step
    info = factory.summary(design, steps)
    assert info["tallest"] == 16 and info["blocks"] > 4000
    assert {"elevator", "lookout", "mill", "terrace", "candy", "packing", "river-west", "river-east", "river-terrace", "depots"} <= set(info["sections"])
    assert info["sections"]["elevator"]["top"] == 15 and info["sections"]["lookout"]["top"] == 15 and info["sections"]["candy"]["top"] == 15
    colours = {str(s["action"].get("color")) for s in steps if s["kind"] == "place"}
    assert len(colours) >= 12  # many-coloured
    needs = factory.materials(steps)
    assert set(needs) == {"wood", "stone", "fiber", "ore"} and needs["ore"] <= 40  # ore is scarce: doors and one crown
    assert len(index) == sum(1 for s in steps if s["kind"] in ("place", "remove"))  # every placement and removal has its own signature
    plots = {str(p) for p in design["plots"]}
    assert plots == {"I08", "J08", "I09", "J09"}
    from hglab.lots import lot_id

    touched = {lot_id(x, y)[:3] for s in steps for x in range(s["tiles"][0], s["tiles"][2] + 1) for y in range(s["tiles"][1], s["tiles"][3] + 1)}
    assert touched == plots  # the factory spans all four plots and no other


def test_the_river_joins_every_section_and_closes_no_tile():
    design, steps, _ = _bp()
    river = {(x, y) for path in design["river"]["branches"].values() for x, y in path}
    for section in design["sections"]:
        x0, y0, x1, y1 = section["tiles"]
        ring = {(x, y) for x in range(x0 - 1, x1 + 2) for y in range(y0 - 1, y1 + 2)} - {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
        assert ring & river, section["id"]  # the river runs along every building
    for step in steps:
        if step["section"].startswith("river-"):
            assert step["action"]["shape"] == "slab" and step["action"]["bz"] == 0 and step["action"]["color"] == "brown"  # a floor at level 0 closes nothing


def test_a_section_rises_in_order_and_sections_rise_in_parallel():
    _design, steps, _ = _bp()
    ready = factory.ready_steps(steps, set())
    assert len({s["section"] for s in ready}) == len(ready) and all(s["id"].endswith(":00") for s in ready)
    first = next(s for s in steps if s["section"] == "elevator")
    after = factory.ready_steps(steps, {first["id"]})
    assert any(s["id"] == "elevator:01" for s in after)
    elevator = [s for s in steps if s["section"] == "elevator"]
    kinds = [("clear" if s["kind"] == "remove" else "plinth" if "foundation" in s["name"] else "door" if "door" in s["name"] else "rest") for s in elevator]
    assert kinds[:4] == ["clear"] * 4 and kinds[4:7] == ["plinth"] * 3 and kinds[7] == "door"  # the stepped version down, the plinth, then the door; the walls skip its cells


def test_the_ledger_marks_what_the_world_accepted_or_found_already_filled(tmp_path, monkeypatch):
    monkeypatch.setattr(factory, "ledger_path", lambda root, name: tmp_path / f"{name}.json")
    design, steps, _ = _bp()
    a, b, c = [s for s in steps if s["kind"] == "place" and s["section"] == "elevator"][:3]
    d, e, f = [s for s in steps if s["kind"] == "remove" and s["section"] == "elevator"][:3]
    done = factory.settle(
        ROOT, "chocolate-factory",
        [a["action"], b["action"], c["action"], d["action"], e["action"], f["action"]],
        [{"ok": True}, {"ok": False, "error": "not_allowed", "message": "every cell already filled"}, {"ok": False, "error": "insufficient_materials"}, {"ok": True}, {"ok": False, "error": "not_found"}, {"ok": False, "error": "too_far"}],
        70000, "Toffeetrowel",
    )
    assert done == [a["id"], b["id"], d["id"], e["id"]]  # a removal is done when it ran, or found nothing left to take
    assert factory.ledger_name(design, "chocolate-factory") == "chocolate-factory.v2"
    ledger = factory.load_ledger(ROOT, factory.ledger_name(design, "chocolate-factory"))
    assert set(ledger["done"]) == {a["id"], b["id"], d["id"], e["id"]} and ledger["done"][a["id"]]["by"] == "Toffeetrowel"


def test_a_builder_places_from_its_pack_or_carries_the_material_from_a_store(tmp_path, monkeypatch):
    monkeypatch.setattr(factory, "ledger_path", lambda root, name: tmp_path / f"{name}.json")
    personas = load_personas(ROOT)
    mason = personas["loompa-mason"]
    team = load_team(ROOT, "chocolate-factory")
    assert factory.builder_sections(team, "loompa-mason")[:2] == ["depots", "elevator"] and factory.builder_sections(team, "loompa-woodcutter") is None
    design, steps, _ = _bp()
    led = factory.ledger_name(design, "chocolate-factory")
    clears = [s for s in steps if s["kind"] == "remove"]
    observe = {"tick": 70000, "you": {"name": mason.name, "x": 88, "y": 86, "faction": {"id": 5, "name": "Chocolate Factory"}, "blocks_owned": 0}}
    view = WorldView(x0=82, y0=80, rows=GRASS, full_map=GRASS, tick=70000)
    factory.mark_done(ROOT, led, sorted(s["id"] for s in steps if s["section"] == "depots"), 1, "test")
    first = factory.plan_step(mason, team, PersonaState(mood="busy"), observe, view, {"berries": 5}, (88, 86), 3, mates={"Treacleaxe"})
    assert first is not None and first[0][-1]["action"] == "remove" and "(the level rebuild)" in first[1]  # his own stepped blocks come down first
    as_wonka = {**observe, "you": {**observe["you"], "name": "Fudgewright"}}
    other = factory.plan_step(personas["wonka"], team, PersonaState(mood="busy"), as_wonka, view, {"berries": 5}, (88, 86), 3, mates={"Treacleaxe"})
    assert other is None or all(a.get("action") != "remove" or a["bx"] // 4 >= 93 for a in other[0])  # never the mason's clears: only his own blocks come out whole
    factory.mark_done(ROOT, led, sorted(s["id"] for s in clears if s["only"] == "loompa-mason"), 1, "test")
    plinth = next(s for s in steps if s["section"] == "elevator" and "foundation" in s["name"])
    state = PersonaState(mood="busy")
    step = factory.plan_step(mason, team, state, observe, view, {"ore": 4, "stone": 10}, (88, 86), 3, mates={"Treacleaxe"})
    assert step is not None and step[2] == "blueprint" and step[0][-1] == plinth["action"]  # then the plinth, paid from the pack
    assert step[0][0]["action"] in ("move", "place")
    state2 = PersonaState(mood="busy")
    store = {"type": "storehouse", "x": 87, "y": 86, "owner": "Treacleaxe", "policy": "faction", "faction": "Chocolate Factory", "storage": {"ore": 12, "stone": 100}}
    beside = WorldView(x0=82, y0=80, rows=GRASS, full_map=GRASS, structures=[store], world_structures=[store], tick=70000)
    fetch = factory.plan_step(mason, team, state2, observe, beside, {"berries": 5}, (88, 86), 3, mates={"Treacleaxe"})
    assert fetch is not None and fetch[0][0]["action"] in ("take", "place")  # the store beside pays, or the ore is taken into the pack
    far = WorldView(x0=82, y0=80, rows=GRASS, full_map=GRASS, world_structures=[{**store, "x": 95, "y": 95, "storage": None}], tick=70000)
    walk = factory.plan_step(mason, team, PersonaState(mood="busy"), observe, far, {"berries": 5}, (88, 86), 3, mates={"Treacleaxe"})
    assert walk is not None and walk[0][0]["action"] == "move" and "store" in walk[1]


def test_every_member_of_the_factory_works_on_the_blueprint():
    team = load_team(ROOT, "chocolate-factory")
    personas = load_personas(ROOT)
    builders = team.extra["pipeline"]["builders"]
    assert set(builders) == {"loompa-mason", "wonka", "mrs-bucket"}  # GrandadPail rests by the hut and holds court (2026-10-24)
    _design, steps, _ = _bp()
    sections = {s["section"] for s in steps}
    assert sections <= {sec for secs in builders.values() for sec in secs}  # every section has a builder who raises it first
    gatherers = [m for m in team.members if m not in builders and m != "grandpa-joe"]
    assert all(personas[m].knobs.get("crew") for m in gatherers)  # the rest gather and carry its materials
    assert personas["grandpa-joe"].knobs["lounge"] == {"x": 88, "y": 95}
    stock = team.extra["pipeline"]["stock"]
    needs = factory.materials(steps)
    assert all(stock[item] >= min(needs[item], 800) for item in needs)  # the stock targets follow the blueprint's cost
    assert personas["wonka"].knobs["house"]["style"] == "blueprint" and personas["wonka"].knobs["house"]["requests"] == ["works", "grounds"]


def test_the_four_plots_leave_the_office_holdings_and_are_sold_as_one_ground():
    from hglab.land import load_ledger

    ledger = load_ledger(ROOT)
    requests = {r["id"]: r for r in ledger["site_requests"]}
    lots = set(requests["works"]["lots"]) | set(requests["grounds"]["lots"])
    assert len(lots) == 16 and {lid[:3] for lid in lots} == {"I08", "J08", "I09", "J09"}
    exchange = load_team(ROOT, "exchange")
    assert set(exchange.extra["pipeline"]["claims"]["exclude"]) == lots
    from hglab.lots import holdings, lot_anchor, stake_text

    signs = [{"type": "sign", "x": lot_anchor(lid)[0], "y": lot_anchor(lid)[1], "owner": "LandBroker", "text": stake_text(lid, "LandBroker")} for lid in ("I08-SE", "K04-NW")]
    held = holdings(exchange.extra["pipeline"]["claims"], signs, lambda x, y: "h", [], [], 1000, "LandBroker")
    assert [h["lot"] for h in held] == ["K04-NW"]  # the factory's lot is under contract: not the office's to work
