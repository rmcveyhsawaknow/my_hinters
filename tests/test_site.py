import random
from pathlib import Path

from hglab.land import board, load_ledger, paid_deeds, plan_round, surveys_due
from hglab.lots import (
    adjacent_lots,
    lot_price,
    lot_value,
    site_search,
    stake_text,
    terrain_lookup,
)
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView, _house_shortfall, _house_site, _plan_site_trade

ROOT = Path(__file__).resolve().parents[1]


def _world():
    rows = []
    for y in range(128):
        row = []
        for x in range(128):
            if y >= 110:
                row.append("W")  # the sea to the south
            elif 60 <= x <= 63 and 70 <= y <= 80:
                row.append("m")  # a mountain ridge
            elif 64 <= x <= 68 and 70 <= y <= 80:
                row.append("h")  # hills beside it
            elif 100 <= x <= 103 and 40 <= y <= 60:
                row.append("w")  # a river
            else:
                row.append("g")
        rows.append("".join(row))
    resources = [
        {"x": 60, "y": 74, "kind": "ore", "amount": 12}, {"x": 60, "y": 76, "kind": "ore", "amount": 10},
        {"x": 66, "y": 75, "kind": "stone", "amount": 20}, {"x": 20, "y": 20, "kind": "berries", "amount": 10},
    ]
    structures = [
        {"type": "hut", "x": 72, "y": 76, "owner": "Stoutheart"}, {"type": "storehouse", "x": 73, "y": 77, "owner": "Stoutheart"},
        {"type": "storehouse", "x": 65, "y": 54, "owner": "LandBroker", "policy": "public"},
    ]
    residents = [{"name": "Stoutheart", "x": 72, "y": 76, "last_seen_tick": 46000}, {"name": "Quill", "x": 66, "y": 74, "last_seen_tick": 100}]
    return {"terrain": "".join(rows), "width": 128, "height": 128, "resources": resources, "structures": structures, "agents": residents, "tick": 46000}


def test_ore_rich_land_by_the_mountains_is_worth_more_than_plain_grass():
    w = _world()
    terrain = terrain_lookup(w)
    rich = lot_value("F07-SE", terrain, w["resources"], w["structures"], w["agents"], 46000)  # x 55-59, y 75-79: ore one tile east, the ridge beside it
    hills = lot_value("G07-NE", terrain, w["resources"], w["structures"], w["agents"], 46000)  # x 65-69, y 70-74: hills inside, mountains three tiles west
    plain = lot_value("C04-NW", terrain, w["resources"], w["structures"], w["agents"], 46000)
    assert rich["score"] > plain["score"] and "ore-rich" in rich["tags"] and "mountain view" in rich["tags"]
    assert "high ground" in hills["tags"] and "stone near" in hills["tags"] and "mountain view" in hills["tags"]
    assert plain["tags"] == [] and plain["score"] == 0
    river = lot_value("J05-NE", terrain, w["resources"], w["structures"], w["agents"], 46000)  # x 95-99, y 50-54: the river runs along its east edge
    assert "river view" in river["tags"]
    sea = lot_value("A12-NW", terrain, w["resources"], w["structures"], w["agents"], 46000)
    assert sea["tags"] == ["unbuildable"] and sea["score"] == 0
    share = 0.78
    assert lot_price(share) == 6 and lot_price(share, value=rich["score"]) > 2 * lot_price(share) and lot_price(share, value=plain["score"]) == 6
    assert lot_price(0.05, value=10) == 50  # the cap: what one give carries
    text = stake_text("F07-SE", "LandBroker", lot_price(share, value=rich["score"]), rich["tags"])
    assert text.startswith("Lot F07-SE: staked by LandBroker") and "Ore-rich" in text and "wood." in text and len(text) <= 200


def test_the_site_search_finds_an_expandable_lot_near_the_brief_s_marks():
    w = _world()
    terrain = terrain_lookup(w)
    request = {"id": "factory", "client": "Fudgewright", "expandable": 2, "min_buildable": 20, "wants": ["ore", "stone"], "near": [{"label": "Neverland", "x": 74, "y": 100, "weight": 3, "max": 45}], "prefer": {"y_min": 60}}
    found = site_search(request, terrain, w["resources"], w["structures"], w["agents"], 46000, registrar="LandBroker")
    assert found and found[0]["lot"] in {"F07-SE", "F07-NE", "G07-NE", "G07-SE"} and len(found[0]["expandable"]) >= 2
    assert any("Neverland" in r for r in found[0]["reasons"]) and "in the south" in found[0]["reasons"]
    assert all(n in adjacent_lots(found[0]["lot"]) for n in found[0]["expandable"])
    none = site_search({**request, "expandable": 4, "min_buildable": 25, "near": [{"x": 5, "y": 5, "weight": 1, "max": 3}]}, terrain, w["resources"], w["structures"], w["agents"], 46000, registrar="LandBroker")
    assert isinstance(none, list)


def test_the_office_surveys_whispers_says_and_deeds_once_paid():
    w = _world()
    ledger = load_ledger(ROOT)
    assert ledger["site_requests"][0]["client"] == "Fudgewright"
    broker = load_personas(ROOT)["land-broker"]
    due = surveys_due(ledger, broker.name, {}, w, w["structures"], w["agents"], 46000)
    assert due and due[0]["client"] == "Fudgewright" and due[0]["price"] >= 6
    observe = {"tick": 46000, "you": {"name": "LandBroker", "x": 65, "y": 55, "energy": 90, "inventory": {"berries": 10, "wood": 5}}, "your_goals": {"posted": []}, "inbox": [], "notebook": {}}
    b = board(ledger, w["structures"], w["agents"], [], broker.name, {}, world=w, tick=46000)
    actions, _reasons, update = plan_round(broker, ledger, observe, b, public_events=[], structures=w["structures"], agents=w["agents"], state={}, collective_names={"Fudgewright", "LandBroker"}, world=w)
    kinds = [a["action"] for a in actions]
    assert kinds[:2] == ["whisper", "say"] and actions[0]["to"] == "Fudgewright" and actions[0]["text"].startswith("SITE for factory: lot ")
    assert "price" in actions[0]["text"] and "storehouse at (65,54)" in actions[0]["text"] and actions[1]["text"].startswith("Survey for Fudgewright")
    assert update["surveys"]["factory"]["lot"] == due[0]["lot"]
    state = {"surveys": update["surveys"]}
    price = state["surveys"]["factory"]["price"]
    events = [{"type": "give", "tick": 46100, "actor": "Fudgewright", "text": f"Fudgewright put {price} wood into the storehouse at (65, 54)."}]
    deeds = paid_deeds(state, events, w["structures"], broker.name)
    assert deeds and deeds[0]["plot"] == due[0]["lot"] and deeds[0]["holder"] == "Fudgewright"
    assert paid_deeds(state, [{**events[0], "tick": 45000}], w["structures"], broker.name) == []  # paid before the survey does not count
    b2 = board(ledger, w["structures"], w["agents"], [], broker.name, state, world=w, tick=46200)
    actions2, _, update2 = plan_round(broker, ledger, {**observe, "tick": 46200}, b2, public_events=events, structures=w["structures"], agents=w["agents"], state=state, collective_names={"Fudgewright", "LandBroker"}, world=w)
    assert actions2[0]["action"] == "say" and actions2[0]["text"].startswith("Deed: lot ") and update2["surveys"]["factory"]["deeded"] == 46200
    assert any(row.startswith(f"{due[0]['lot']}:Fudgewright:") for row in update2["registered"])


def test_the_client_asks_reads_the_answer_pays_and_builds_on_the_bought_lot():
    personas = load_personas(ROOT)
    wonka = personas["wonka"]
    knob = wonka.knobs["house"]
    assert knob["site_from"] == "land_office" and knob["requests"] == ["works", "grounds"] and "site" not in knob and knob["style"] == "blueprint"
    state = PersonaState(mood="mercurial")
    assert _house_site(knob, {"x": 65, "y": 71}, state) is None  # never the old hearth
    rows = ["g" * 128] * 128
    view = WorldView(x0=60, y0=66, rows=rows, full_map=rows, world_structures=[{"type": "storehouse", "x": 65, "y": 54, "owner": "LandBroker"}])
    observe = {"tick": 46000, "you": {"x": 66, "y": 72}, "inbox": []}
    ask = _plan_site_trade(wonka, state, {"wood": 12}, (66, 72), view, observe, "LandBroker")
    assert ask is not None and ask[2] == "site_request" and ask[0][0]["to"] == "LandBroker" and ask[0][0]["text"].startswith("SURVEY REQUEST works")
    assert _plan_site_trade(wonka, state, {"wood": 12}, (66, 72), view, observe, "LandBroker") is None  # asked once a day
    assert _house_shortfall(wonka, {}, view, state) == []  # no ground yet: nothing to gather for the house
    answer = {"from": "LandBroker", "text": "SITE for works: lot G07-NE, anchor (67,72), 2 free lots beside it to grow into; ore-rich, mountain view; price 18 wood. Put the wood into my storehouse at (65,54); the deed follows."}
    trip = _plan_site_trade(wonka, state, {"wood": 20}, (66, 72), view, {**observe, "inbox": [answer]}, "LandBroker")
    assert state.flags["house_site"]["lot"] == "G07-NE" and state.flags["house_site"]["price"] == 18 and _house_site(knob, None, state) == (67, 72)
    assert trip is not None and trip[2] == "deed_trip" and trip[0][0]["action"] == "move"
    pay = _plan_site_trade(wonka, state, {"wood": 20}, (65, 55), view, {**observe, "inbox": []}, "LandBroker")
    assert pay is not None and pay[0] == [{"action": "give", "x": 65, "y": 54, "item": "wood", "qty": 18}] and state.flags["house_site"]["paid"] == 18
    assert _plan_site_trade(wonka, state, {"wood": 20}, (65, 55), view, observe, "LandBroker") is None  # paid in full
    assert _house_shortfall(wonka, {}, view, state) == []  # the house is the team's blueprint: its builders fetch each step's material
    assert _plan_site_trade(wonka, state, {"wood": 20}, (65, 55), view, {**observe, "inbox": []}, "LandBroker") is not None  # paid in full: the grounds brief follows
    assert state.flags["sites_paid"] == ["works"] and state.flags["site_asked_for"] == "grounds"
    team = load_team(ROOT, wonka.team)
    assert team.members and random.Random  # the module imports hold


def test_the_works_ground_is_surveyed_as_fixed_lots_and_paid_into_any_office_store_or_in_person():
    from hglab.land import pay_store

    w = _world()
    ledger = load_ledger(ROOT)
    broker = load_personas(ROOT)["land-broker"]
    done = {"surveys": {"factory": {"client": "Fudgewright", "lot": "I08-SE", "price": 45, "currency": "wood", "tick": 46000, "deeded": 1}}}
    due = {d["id"]: d for d in surveys_due(ledger, broker.name, done["surveys"], w, w["structures"], w["agents"], 58000)}
    works = due["works"]
    assert works["client"] == "Fudgewright" and works["lot"] == "I09-SE" and works["lots"] == ["I09-SE", "I09-NE"] and works["price"] >= 10
    assert tuple(works["anchor"]) == (87, 97) and works["reasons"][0].startswith("the ground under Fudgewright's works: I09-SE, I09-NE")
    stores = [*w["structures"], {"type": "storehouse", "x": 86, "y": 86, "owner": "Lintelstave", "faction": "Land Office"}]
    assert pay_store(stores, broker.name, {"Lintelstave"}, (87, 97))["owner"] == "Lintelstave"  # the office store nearest the ground
    state = {"surveys": {**done["surveys"], "works": {"client": "Fudgewright", "lot": "I09-SE", "lots": ["I09-SE", "I09-NE"], "price": 40, "currency": "wood", "tick": 58000}}}
    events = [
        {"type": "give", "tick": 58100, "actor": "Fudgewright", "text": "Fudgewright put 25 wood into the storehouse at (86, 86)."},
        {"type": "give", "tick": 58200, "actor": "Fudgewright", "text": "Fudgewright gave 15 wood to LandBroker."},
    ]
    assert paid_deeds(state, events, stores, broker.name) == []  # a hand's store counts only when the office names its hands
    deeds = paid_deeds(state, events, stores, broker.name, office_names={"Lintelstave"})
    assert deeds and deeds[0]["plots"] == ["I09-SE", "I09-NE"] and deeds[0]["paid"] == 40  # the depot and the registrar's hands together
    observe = {"tick": 58000, "you": {"name": "LandBroker", "x": 65, "y": 55, "energy": 90, "inventory": {"berries": 10, "wood": 5}}, "your_goals": {"posted": []}, "inbox": [], "notebook": {}}
    b = board(ledger, stores, w["agents"], [], broker.name, done, world=w, tick=58000)
    actions, _reasons, update = plan_round(broker, ledger, observe, b, public_events=[], structures=stores, agents=w["agents"], state=done, collective_names={"Fudgewright", "LandBroker", "Lintelstave"}, world=w, office_names={"Lintelstave"})
    whisper = next(a for a in actions if a["action"] == "whisper")
    assert whisper["to"] == "Fudgewright" and whisper["text"].startswith("SITE for works: lot I09-SE, anchor (87,97)") and "storehouse at (86,86)" in whisper["text"] and "into my hands" in whisper["text"]
    assert update["surveys"]["works"]["lots"] == ["I09-SE", "I09-NE"]
    # the client: a changed brief drops the old answer and asks at once; the payment goes into any office store with room
    wonka = load_personas(ROOT)["wonka"]
    pstate = PersonaState(mood="mercurial")
    pstate.flags["house_site"] = {"id": "factory", "x": 87, "y": 87, "lot": "I08-SE", "price": 45, "currency": "wood", "paid": 0, "tick": 46000}
    pstate.flags["site_asked"], pstate.flags["site_asked_for"] = 57000, "factory"
    rows = ["g" * 128] * 128
    view = WorldView(x0=80, y0=84, rows=rows, full_map=rows, world_structures=[{"type": "storehouse", "x": 86, "y": 86, "owner": "Lintelstave", "faction": "Land Office"}])
    ask = _plan_site_trade(wonka, pstate, {"wood": 45}, (87, 87), view, {"tick": 57100, "you": {"x": 87, "y": 87}, "inbox": []}, "LandBroker", office_names={"Lintelstave"})
    assert ask is not None and ask[2] == "site_request" and ask[0][0]["text"].startswith("SURVEY REQUEST works") and "house_site" not in pstate.flags and pstate.flags["site_asked_for"] == "works"
    answer = {"from": "LandBroker", "text": whisper["text"].replace("price", "price").replace(f"price {works['price']}", "price 40")}
    pay = _plan_site_trade(wonka, pstate, {"wood": 45}, (87, 87), view, {"tick": 57100, "you": {"x": 87, "y": 87}, "inbox": [answer]}, "LandBroker", office_names={"Lintelstave"})
    assert pstate.flags["house_site"]["id"] == "works" and pstate.flags["house_site"]["lot"] == "I09-SE"
    assert pay is not None and pay[0][0]["action"] == "give" and (pay[0][0]["x"], pay[0][0]["y"]) == (86, 86) and pay[0][0]["qty"] == pstate.flags["house_site"]["price"]
    assert pstate.flags["house_site"]["pending"] == pay[0][0]["qty"] and pstate.flags["house_site"]["paid"] == pay[0][0]["qty"]
    # every office store full and the registrar near: the price goes into the registrar's hands
    owing = PersonaState(mood="mercurial")
    owing.flags["house_site"] = {"id": "works", "x": 87, "y": 97, "lot": "I09-SE", "price": 40, "currency": "wood", "paid": 0, "tick": 57000}
    owing.flags["full_stores"] = {"86,86": 57050}
    residents = [{"name": "LandBroker", "x": 84, "y": 90, "last_seen_tick": 57090}]
    crowded = WorldView(x0=80, y0=84, rows=rows, full_map=rows, world_structures=view.world_structures, residents=residents, tick=57100)
    walk = _plan_site_trade(wonka, owing, {"wood": 45}, (87, 87), crowded, {"tick": 57100, "you": {"x": 87, "y": 87}, "inbox": []}, "LandBroker", office_names={"Lintelstave"})
    assert walk is not None and walk[2] == "deed_trip" and walk[0][0]["action"] == "move" and "LandBroker" in walk[1]
    hand = _plan_site_trade(wonka, owing, {"wood": 45}, (85, 89), crowded, {"tick": 57100, "you": {"x": 85, "y": 89}, "inbox": []}, "LandBroker", office_names={"Lintelstave"})
    assert hand is not None and hand[0] == [{"action": "give", "to": "LandBroker", "item": "wood", "qty": 40}] and owing.flags["house_site"]["pending"] == 40
    assert _plan_site_trade(wonka, owing, {"wood": 5}, (85, 89), crowded, {"tick": 57200, "you": {"x": 85, "y": 89}, "inbox": []}, "LandBroker", office_names={"Lintelstave"}) is None  # paid in full
    assert "pending" not in owing.flags["house_site"]  # the next wake found no refusal: settled
    assert _plan_site_trade(wonka, pstate, {"wood": 45}, (87, 87), view, {"tick": 57100, "you": {"x": 87, "y": 87}, "inbox": []}, "LandBroker") is None  # without the hands' names the only office store is unknown here


def test_a_client_who_asks_again_gets_the_answer_again():
    w = _world()
    ledger = load_ledger(ROOT)
    broker = load_personas(ROOT)["land-broker"]
    state = {"surveys": {"factory": {"client": "Fudgewright", "lot": "F07-SE", "anchor": [57, 77], "price": 20, "currency": "wood", "tick": 46000, "reasons": ["ore-rich"]}, "works": {"client": "Fudgewright", "deeded": 1}, "grounds": {"client": "Fudgewright", "deeded": 1}}}
    observe = {"tick": 46400, "you": {"name": "LandBroker", "x": 65, "y": 55, "energy": 90, "inventory": {"berries": 10, "wood": 5}}, "your_goals": {"posted": []}, "inbox": [{"from": "Fudgewright", "text": "SURVEY REQUEST factory: LandBroker, the factory needs ground.", "tick": 46390}], "notebook": {}}
    b = board(ledger, w["structures"], w["agents"], [], broker.name, state, world=w, tick=46400)
    actions, _reasons, update = plan_round(broker, ledger, observe, b, public_events=[], structures=w["structures"], agents=w["agents"], state=state, collective_names={"Fudgewright", "LandBroker"}, world=w)
    whispers = [a for a in actions if a["action"] == "whisper"]
    assert whispers and whispers[0]["to"] == "Fudgewright" and whispers[0]["text"].startswith("SITE for factory: lot F07-SE, anchor (57,77)") and "price 20 wood" in whispers[0]["text"]
    assert update["surveys"]["factory"]["answered"] == 46400 and len([a for a in actions if a["action"] == "whisper"]) == 1  # answered once more, not surveyed anew


def test_an_unpaid_survey_is_reminded_every_two_hours_three_times():
    w = _world()
    ledger = load_ledger(ROOT)
    broker = load_personas(ROOT)["land-broker"]
    survey = {"client": "Fudgewright", "lot": "F07-SE", "anchor": [57, 77], "price": 20, "currency": "wood", "tick": 46000, "reasons": ["ore-rich"]}
    observe = {"you": {"name": "LandBroker", "x": 65, "y": 55, "energy": 90, "inventory": {"berries": 10, "wood": 5}}, "your_goals": {"posted": []}, "inbox": [], "notebook": {}}
    state = {"surveys": {"factory": dict(survey), "works": {"client": "Fudgewright", "deeded": 1}, "grounds": {"client": "Fudgewright", "deeded": 1}}}
    for n, tick in enumerate((46800, 47600, 48400, 49200), start=1):
        b = board(ledger, w["structures"], w["agents"], [], broker.name, state, world=w, tick=tick)
        actions, _r, update = plan_round(broker, ledger, {**observe, "tick": tick}, b, public_events=[], structures=w["structures"], agents=w["agents"], state=state, collective_names={"Fudgewright"}, world=w)
        whispers = [a for a in actions if a["action"] == "whisper" and a["to"] == "Fudgewright"]
        if n <= 3:
            assert whispers and whispers[0]["text"].startswith("SITE for factory"), (n, actions)
            state = {"surveys": update["surveys"]}
            assert state["surveys"]["factory"]["reminders"] == n
        else:
            assert not whispers  # three reminders, then the office waits for the client
    quiet = {"surveys": {"factory": {**survey, "answered": 46400}, "works": {"client": "Fudgewright", "deeded": 1}, "grounds": {"client": "Fudgewright", "deeded": 1}}}
    early = board(ledger, w["structures"], w["agents"], [], broker.name, quiet, world=w, tick=46500)
    actions, _r, _u = plan_round(broker, ledger, {**observe, "tick": 46500}, early, public_events=[], structures=w["structures"], agents=w["agents"], state=quiet, collective_names={"Fudgewright"}, world=w)
    assert not [a for a in actions if a["action"] == "whisper"]  # answered a hundred ticks ago: not yet
