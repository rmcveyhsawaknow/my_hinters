"""The land office's tills and its extra stores (owner, 2026-10-27).

Every office store held 500, every hand's pack was full of fiber, ore or wood, so nobody could unload,
carry stone to the walls, or pay the factory's deed. The mason raises a store beside a full one, paid
from it; the tills take the price of land and nothing else.
"""

from pathlib import Path

from hglab.crew import plan_crew, team_tills
from hglab.land import pay_store
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView, _plan_site_trade

ROOT = Path(__file__).resolve().parents[1]
ROWS = ["g" * 128] * 128
FULL = {"ore": 20, "wood": 64, "fiber": 114, "stone": 236, "berries": 66}
TILLS = team_tills(load_team(ROOT, "exchange"))


def _store(x, y, owner="Lintelstave", storage=None, policy="faction"):
    return {"type": "storehouse", "x": x, "y": y, "owner": owner, "policy": policy, "faction": "Land Office", "storage": dict(FULL if storage is None else storage)}


def _view(stores):
    vault = _store(73, 72, owner="LandBroker", policy="private")
    return WorldView(x0=60, y0=60, rows=ROWS, full_map=ROWS, structures=[vault, *stores], world_structures=[vault, *stores], tick=1000)


def _step(slug, inventory, position, view, room=3):
    personas = load_personas(ROOT)
    persona = personas[slug]
    observe = {"you": {"x": position[0], "y": position[1], "faction": {"id": 7, "name": "Land Office"}}, "tick": 1000}
    return plan_crew(
        persona, load_team(ROOT, "exchange"), PersonaState(mood="busy"), observe, view, dict(inventory), position, 80, persona.energy_reserve, room,
        {p.name for p in personas.values()}, {p.name: s for s, p in personas.items()}, None,
    )


def test_the_office_keeps_two_tills_and_a_cap_on_its_stores():
    claims = load_team(ROOT, "exchange").extra["pipeline"]["claims"]
    assert TILLS == {(78, 95), (72, 73)} and claims["stores_max"] >= 9 + len(TILLS)


def test_with_every_store_full_the_mason_raises_another_beside_one_paid_from_it():
    tills = [_store(x, y, storage={}) for x, y in sorted(TILLS)]
    step = _step("office-steward", {"wood": 45, "berries": 5}, (80, 76), _view([_store(81, 76), *tills]))
    build = step[0][0]
    assert build["action"] == "build" and build["type"] == "storehouse" and build["policy"] == "faction"
    assert max(abs(build["x"] - 80), abs(build["y"] - 76)) == 1 and (build["x"], build["y"]) not in TILLS
    assert "every store of the office is full" in step[1] and "(81, 76)" in step[1]
    roomy = _step("office-steward", {"wood": 45, "berries": 5}, (80, 76), _view([_store(81, 76, storage={"stone": 100}), *tills]))
    assert roomy is None or all(a.get("type") != "storehouse" for a in roomy[0])  # a store with room: no new one


def test_a_missing_till_is_raised_from_the_pack_where_the_office_put_it():
    till = sorted(TILLS)[1]  # (78, 95), by the factory's west gate
    other = [_store(*t, storage={}) for t in TILLS if t != till]
    beside = _step("office-steward", {"wood": 20, "stone": 10, "berries": 5}, (till[0] - 1, till[1] - 1), _view([_store(81, 76), *other]))
    assert beside[0] == [{"action": "build", "type": "storehouse", "x": till[0], "y": till[1], "policy": "faction"}] and "till" in beside[1]
    away = _step("office-steward", {"wood": 20, "stone": 10, "berries": 5}, (till[0] - 6, till[1] - 6), _view([_store(81, 76), *other]))
    assert away[0][0]["action"] == "move" and "till" in away[1]


def test_no_hand_unloads_into_a_till():
    tills = [_store(x, y, storage={}) for x, y in sorted(TILLS)]
    till = (78, 95)
    step = _step("office-quarrier", {"fiber": 30, "stone": 1, "berries": 15}, (till[0] - 1, till[1]), _view([_store(81, 76), *tills]))
    assert step is None or not any(a.get("action") == "give" and (a.get("x"), a.get("y")) in TILLS for a in step[0])


def test_the_client_pays_into_a_till_and_the_registrar_names_it():
    wonka = load_personas(ROOT)["wonka"]
    owing = PersonaState(mood="mercurial")
    owing.flags["house_site"] = {"id": "works", "x": 87, "y": 97, "lot": "I09-SE", "price": 40, "currency": "wood", "paid": 16, "tick": 57000}
    office = [_store(86, 86), _store(78, 95, storage={})]
    view = WorldView(x0=70, y0=80, rows=ROWS, full_map=ROWS, structures=office, world_structures=office, tick=57100)
    pay = _plan_site_trade(wonka, owing, {"wood": 45}, (79, 94), view, {"tick": 57100, "you": {"x": 79, "y": 94}, "inbox": []}, "LandBroker", office_names={"Lintelstave"}, tills=TILLS)
    assert pay[0] == [{"action": "give", "x": 78, "y": 95, "item": "wood", "qty": 24}]
    walk = _plan_site_trade(wonka, PersonaState(mood="mercurial", flags={"house_site": dict(owing.flags["house_site"], paid=16)}), {"wood": 45}, (88, 90), view, {"tick": 57100, "you": {"x": 88, "y": 90}, "inbox": []}, "LandBroker", office_names={"Lintelstave"}, tills=TILLS)
    assert walk[0][0]["action"] == "move" and "(78, 95)" in walk[1]  # past the full store by the ground, to the till
    assert pay_store(office, "LandBroker", {"Lintelstave"}, (87, 97), TILLS)["x"] == 78
    assert pay_store(office, "LandBroker", {"Lintelstave"}, (86, 88), TILLS)["x"] == 78 and pay_store(office, "LandBroker", {"Lintelstave"}, (86, 88))["x"] == 86  # without tills: the store nearest the ground
