import json
from pathlib import Path

from typer.testing import CliRunner

from hglab.cli import app
from hglab.fixtures import FixtureClient, load_fixture
from hglab.lease import acquire
from hglab.persona import load_personas, load_team
from hglab.pulse import scheduled_wakes
from hglab.wake import persona_wake
from hglab.workflows import caller_text

ROOT = Path(__file__).parents[1]
FIX = ROOT / "tests/fixtures"


def _wake(slug: str, observe: dict, tmp_path: Path, **overrides):
    personas = load_personas(ROOT)
    persona = personas[slug]
    client = FixtureClient(observe)
    lease = acquire(client, persona.name)
    return persona_wake(persona=persona, team=load_team(ROOT, persona.team), personas=personas, client=client, lease=lease, root=ROOT, output_dir=tmp_path, dry_run=True, work=True, seed="shift", **overrides), client


def test_work_wake_builds_first_when_materials_are_in_hand(tmp_path):
    observe = load_fixture(FIX / "observe/nibs.json")
    observe["you"]["inventory"] = {"wood": 20, "stone": 10, "fiber": 6, "berries": 4}
    observe["you"]["home"] = None
    record, _ = _wake("nibs", observe, tmp_path)
    assert record["work"] is True and record["planner"] == "heuristic"
    assert record["actions"][0]["action"] == "build" and record["actions"][0]["type"] == "hut"
    assert "inbox" not in json.dumps(record) and record["observe"].keys() == {"tick", "you"}


def test_work_wake_deposits_surplus_and_can_raise_a_monument(tmp_path):
    observe = load_fixture(FIX / "observe/wonka.json")
    you = observe["you"]
    you["inventory"] = {"stone": 30, "ore": 10, "wood": 6}
    observe["structures"] = [{"id": 1, "type": "storehouse", "x": you["x"] + 1, "y": you["y"], "owner": "Peregrine", "faction": None, "hp": 80, "text": None, "policy": "public", "storage": {"stone": 25}}]
    record, _ = _wake("wonka", observe, tmp_path)
    kinds = [a["action"] for a in record["actions"]]
    assert record["approach"] == "build_monument"  # a public storehouse beside the builder pays the rest, per the guide
    assert record["actions"][0]["type"] == "monument"
    assert "remember" in kinds


def test_work_wake_migrates_toward_the_team_site_when_far(tmp_path):
    observe = load_fixture(FIX / "observe/mrs-bucket.json")
    observe["you"].update({"x": 62, "y": 56})
    observe["you"]["inventory"] = {"berries": 5}
    observe["resources"] = []
    observe["structures"] = []
    observe["view"]["x0"], observe["view"]["y0"] = 56, 50
    record, _ = _wake("mrs-bucket", observe, tmp_path)
    moves = [a for a in record["actions"] if a["action"] == "move"]
    assert record["approach"] in {"migrate", "explore"}
    if record["approach"] == "migrate":
        assert moves and (moves[0]["x"] > 62 or moves[0]["y"] > 56)


def test_shift_command_runs_several_fixture_wakes_without_a_key(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr("hglab.cli_personas.persona_wake", lambda **kw: persona_wake(**{**kw, "output_dir": tmp_path}))
    result = CliRunner().invoke(app, ["shift", "--agent", "nibs", "--fixture", str(FIX / "observe/nibs.json"), "--max-wakes", "3", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "shift over: 3 wake(s)" in result.output
    assert len(list(tmp_path.glob("*.json"))) == 3


def test_callers_carry_the_work_cron_and_scheduled_wakes_count_shifts():
    personas = load_personas(ROOT)
    wonka = personas["wonka"]
    text = caller_text(wonka)
    assert wonka.knobs["work"]["cron"] in text and "'shift'" in text and "shift]" in text
    assert scheduled_wakes(wonka, [{"tick": 99000, "work": True}], 100000, 7 * 8640) > scheduled_wakes(wonka, [{"tick": 99000}], 100000, 7 * 8640)


def test_far_settlers_migrate_before_building(tmp_path):
    observe = load_fixture(FIX / "observe/mrs-bucket.json")
    observe["you"].update({"x": 62, "y": 56, "home": None})
    observe["you"]["inventory"] = {"wood": 20, "fiber": 10, "berries": 5}
    observe["structures"] = []
    observe["view"]["x0"], observe["view"]["y0"] = 56, 50
    record, _ = _wake("mrs-bucket", observe, tmp_path)
    assert record["approach"] == "migrate"
    assert record["actions"][0]["action"] == "move"
    assert all(a["action"] != "build" for a in record["actions"])


def test_roads_only_extend_existing_structures(tmp_path):
    observe = load_fixture(FIX / "observe/nibs.json")
    observe["you"]["inventory"] = {"stone": 6, "berries": 5}
    observe["structures"] = []
    record, _ = _wake("nibs", observe, tmp_path)
    assert all(not (a["action"] == "build" and a.get("type") == "road") for a in record["actions"])


def test_no_fourth_farm_when_three_stand_elsewhere():
    from hglab.planner import WorldView, _plan_build

    persona = load_personas(ROOT)["mrs-bucket"]
    inventory = {"fiber": 10, "wood": 10, "berries": 5}
    rows = ["ggg", "ggg", "ggg"]
    home = {"x": 1, "y": 1}
    open_view = WorldView(x0=0, y0=0, rows=rows)
    capped_view = WorldView(x0=0, y0=0, rows=rows, owned_counts={"farm": 3})
    before = _plan_build(persona, None, dict(inventory), (1, 1), open_view, home)
    after = _plan_build(persona, None, dict(inventory), (1, 1), capped_view, home)
    assert before is not None and before[0][0]["type"] == "farm"
    assert after is None or after[0][0]["type"] != "farm"


def test_upkeep_mends_damaged_structures_collects_full_farms_and_takes_salvage():
    from hglab.planner import WorldView, _estimate, _plan_harvest, _plan_repair, _plan_salvage

    nibs = load_personas(ROOT)["nibs"]
    rows = ["g" * 8] * 8
    road = {"type": "road", "x": 2, "y": 1, "owner": nibs.name, "hp": 5, "hp_max": 20}
    far_hut = {"type": "hut", "x": 6, "y": 6, "owner": nibs.name, "hp": 10, "hp_max": 40}
    other = {"type": "hut", "x": 1, "y": 2, "owner": "Quill", "hp": 1, "hp_max": 40}
    view = WorldView(x0=0, y0=0, rows=rows, structures=[road, far_hut, other])
    plan = _plan_repair(nibs, None, {"stone": 2, "wood": 3}, (1, 1), view, None)
    assert plan is not None and plan[0] == [{"action": "repair", "x": 2, "y": 1}] and "1 stone" in plan[1]
    scratch = {"type": "road", "x": 2, "y": 1, "owner": nibs.name, "hp": 15, "hp_max": 20}
    unknown = {"type": "road", "x": 2, "y": 1, "owner": nibs.name}
    assert _plan_repair(nibs, None, {"stone": 2}, (1, 1), WorldView(x0=0, y0=0, rows=rows, structures=[scratch]), None) is None  # 5 hp missing: not worth a stone
    assert _plan_repair(nibs, None, {"stone": 2}, (1, 1), WorldView(x0=0, y0=0, rows=rows, structures=[unknown]), None) is None  # no hp in the snapshot
    assert _plan_repair(nibs, None, {"wood": 3}, (1, 1), WorldView(x0=0, y0=0, rows=rows, structures=[road]), None) is None  # no stone, no mending
    trip = _plan_repair(nibs, None, {"wood": 3}, (1, 1), WorldView(x0=0, y0=0, rows=rows, structures=[far_hut, other]), None)
    assert trip is not None and [a["action"] for a in trip[0]] == ["move", "repair"] and trip[0][1] == {"action": "repair", "x": 6, "y": 6}
    farm = {"type": "farm", "x": 2, "y": 2, "owner": nibs.name, "hp": 30, "hp_max": 30, "storage": {"berries": 24}}
    harvest = _plan_harvest(nibs, None, {"wood": 10}, (1, 1), WorldView(x0=0, y0=0, rows=rows, structures=[farm]), None)
    assert harvest is not None and harvest[0] == [{"action": "take", "x": 2, "y": 2, "item": "berries", "qty": 24}]
    assert _plan_harvest(nibs, None, {"wood": 48}, (1, 1), WorldView(x0=0, y0=0, rows=rows, structures=[farm]), None) is None  # no room in the pack
    ruin = {"type": "cache", "x": 1, "y": 0, "owner": None, "storage": {"stone": 7, "wood": 3}, "ruin": {"type": "hut", "owner": "Quill"}}
    salvage = _plan_salvage({"wood": 5}, (1, 1), WorldView(x0=0, y0=0, rows=rows, structures=[ruin]))
    assert salvage is not None and salvage[0] == [{"action": "take", "x": 1, "y": 0, "item": "stone", "qty": 7}] and "ruin of Quill's hut" in salvage[1]
    assert _estimate([{"action": "move", "x": 5, "y": 1}, {"action": "repair", "x": 5, "y": 2}], (1, 1)) == 7
    assert _estimate([{"action": "move", "x": 5, "y": 1}, {"action": "repair", "x": 5, "y": 2}], (1, 1), storm=True) == 11
    observe = load_fixture(FIX / "observe/nibs.json")
    observe["weather"], observe["season"] = "storm", "winter"
    stormy = WorldView.from_observe(observe, None)
    assert stormy.weather == "storm" and stormy.season == "winter"


def test_move_targets_are_reachable_along_walkable_tiles_not_as_the_crow_flies():
    from hglab.planner import (
        WorldView,
        _adjacent_stand,
        _walkable_ring,
        reachable_tiles,
    )

    # a river of deep water splits the map: the far bank is 4 tiles away in a straight line but unreachable
    rows = ["gggWWggg"] * 8
    view = WorldView(x0=0, y0=0, rows=rows)
    reach = reachable_tiles(view, (1, 1))
    assert (2, 1) in reach and (5, 1) not in reach and all(x < 3 for x, _ in reach)
    assert all(x < 3 for x, _ in _walkable_ring((1, 1), view, 1, 12))
    nibs = load_personas(ROOT)["nibs"]
    assert _adjacent_stand((6, 1), (1, 1), view, nibs, None, None) is None
    assert _adjacent_stand((2, 3), (1, 1), view, nibs, None, None) is not None



def test_upkeep_in_reach_comes_before_the_walk_to_the_team_site(tmp_path):
    observe = load_fixture(FIX / "observe/mrs-bucket.json")
    observe["you"].update({"x": 62, "y": 56, "home": None})
    observe["you"]["inventory"] = {"wood": 20, "fiber": 10, "berries": 5}
    observe["structures"] = [{"id": 5, "type": "farm", "x": 63, "y": 56, "owner": observe["you"]["name"], "hp": 30, "hp_max": 30, "storage": {"berries": 27}}]
    observe["view"]["x0"], observe["view"]["y0"] = 56, 50
    record, _ = _wake("mrs-bucket", observe, tmp_path)
    assert record["approach"] == "harvest"
    assert record["actions"][0] == {"action": "take", "x": 63, "y": 56, "item": "berries", "qty": 15}


def test_the_public_map_becomes_terrain_rows():
    from hglab.cli_personas import terrain_rows_from_world

    rows = terrain_rows_from_world({"width": 128, "terrain": "g" * (128 * 128)})
    assert rows is not None and len(rows) == 128 and len(rows[0]) == 128
    assert terrain_rows_from_world({"width": 128, "terrain": ["ggg", "ggg"]}) == ["ggg", "ggg"]
    assert terrain_rows_from_world({"terrain": "short"}) is None and terrain_rows_from_world({}) is None


def test_the_land_office_stakes_the_nearest_free_lots_and_spares_homesteads():
    from hglab.lots import homestead_ring
    from hglab.planner import WorldView, _plan_stake

    broker = load_personas(ROOT)["land-broker"]
    rows = ["g" * 128] * 128
    far_hut = {"type": "hut", "x": 97, "y": 36, "owner": "Quill"}
    view = WorldView(x0=60, y0=60, rows=rows, structures=[], world_structures=[far_hut])
    first = _plan_stake(broker, {"wood": 3}, (62, 62), view)
    assert first is not None and first[0][-1]["action"] == "build" and first[0][-1]["type"] == "sign"
    lid = first[2].split(":", 1)[1]
    assert lid == "G06-NW" and (first[0][-1]["x"], first[0][-1]["y"]) == (62, 62) and len(first[0]) == 1  # standing on the anchor
    second = _plan_stake(broker, {"wood": 3}, (62, 62), view, exclude={lid})
    assert second is not None and second[2] != first[2] and [a["action"] for a in second[0]] == ["move", "build"]
    near_hut = {"type": "hut", "x": 67, "y": 56, "owner": "Quill"}
    ringed = _plan_stake(broker, {"wood": 3}, (62, 62), WorldView(x0=60, y0=60, rows=rows, structures=[], world_structures=[near_hut]))
    assert ringed is not None and ringed[2].split(":", 1)[1] not in homestead_ring([near_hut], "LandBroker")  # a ring of lots around the homestead stays open
    assert _plan_stake(broker, {"stone": 3}, (62, 62), view) is None  # no wood, no sign
    assert _plan_stake(load_personas(ROOT)["wonka"], {"wood": 3}, (62, 62), view) is None  # only the office stakes
    occupied = WorldView(x0=60, y0=60, rows=rows, structures=[], world_structures=[far_hut, {"type": "sign", "x": 62, "y": 62, "owner": "LandBroker", "text": "Lot G06-NW: staked"}])
    assert _plan_stake(broker, {"wood": 3}, (62, 62), occupied)[2] != "stake:G06-NW"


def test_the_house_rises_step_by_step_from_the_pack():
    from hglab.planner import WorldView, _house_shortfall, _plan_house

    clarion = load_personas(ROOT)["town-crier"]
    rows = ["g" * 128] * 128
    hut = {"type": "hut", "x": 63, "y": 71, "owner": clarion.name, "hp": 40, "hp_max": 40}
    view = WorldView(x0=57, y0=65, rows=rows, structures=[hut])
    home = {"x": 63, "y": 71}
    observe = {"you": {"x": 64, "y": 71, "blocks_owned": 0}, "blocks": []}  # observed beside the hut: the footprint is in view
    door = _plan_house(clarion, {"wood": 3, "stone": 2}, (64, 71), view, home, observe)
    assert door is not None and door[0][0]["action"] == "place" and door[0][0]["shape"] == "door" and door[2] == "house"
    assert _plan_house(clarion, {"stone": 20}, (64, 71), view, home, observe) is None  # the door wants wood first
    observe["blocks"] = [{"x": 63, "y": 71, "count": 9, "owner": clarion.name}]  # door and window stand
    walls = _plan_house(clarion, {"stone": 9}, (64, 71), view, home, observe)
    assert walls is not None and walls[0][0]["fill"] == "walls" and _house_shortfall(clarion, {"wood": 2}, view) == ["stone"]
    from hglab.mood import PersonaState

    state = PersonaState(mood="warm")
    seen = {"you": {"x": 64, "y": 71, "blocks_owned": 9}, "blocks": observe["blocks"], "tick": 100}
    assert _plan_house(clarion, {"stone": 9}, (64, 71), view, home, seen, state=state)[0][0]["fill"] == "walls"
    assert state.flags["house"] == {"hut": [63, 71], "done": 9, "tick": 100}  # progress noted while the hut is in view
    afar = {"you": {"x": 75, "y": 71, "blocks_owned": 9}, "tick": 160}  # the hut is out of view: no blocks field at all
    far = _plan_house(clarion, {"wood": 3, "stone": 9}, (70, 71), view, home, afar, state=state)
    assert far is not None and [a["action"] for a in far[0]] == ["move", "place"] and far[0][1]["fill"] == "walls"  # remembered, not the door again
    fresh = _plan_house(clarion, {"wood": 3, "stone": 9}, (70, 71), view, home, afar)  # nothing remembered: starts from the door
    assert fresh is not None and fresh[0][1]["shape"] == "door" and abs(fresh[0][0]["x"] - 63) <= 2
    observe["blocks"] = [{"x": 63, "y": 71, "count": 52, "owner": clarion.name}]
    assert _plan_house(clarion, {"stone": 9, "fiber": 9, "wood": 9}, (64, 71), view, home, observe) is None  # the house stands
    assert _plan_house(load_personas(ROOT)["wonka"], {"wood": 9}, (64, 71), view, None, observe) is None  # no hut, no house


def test_a_builder_carries_house_materials_home_before_wandering():
    from hglab.planner import WorldView, _plan_homing

    clarion = load_personas(ROOT)["town-crier"]
    rows = ["g" * 128] * 128
    view = WorldView(x0=84, y0=65, rows=rows, structures=[])
    home = {"x": 63, "y": 71}
    step = _plan_homing(clarion, {"wood": 3}, (90, 71), view, home, {"you": {}, "blocks": []})
    assert step is not None and step[0][0]["action"] == "move" and step[0][0]["x"] < 90 and step[2] == "homing"
    assert _plan_homing(clarion, {"stone": 3}, (90, 71), view, home, {"you": {}, "blocks": []}) is None  # the door wants wood
    assert _plan_homing(clarion, {"wood": 3}, (70, 71), view, home, {"you": {}, "blocks": []}) is None  # within one move: the house step walks it


def test_a_pack_heavy_with_berries_is_lightened_not_topped_up():
    import random

    from hglab.planner import (
        WorldView,
        _plan_deposit,
        _plan_forage,
        _plan_gather,
        _plan_harvest,
        _plan_lighten,
    )

    bucket = load_personas(ROOT)["mrs-bucket"]
    rows = ["g" * 128] * 128
    hoard = {"wood": 5, "fiber": 6, "berries": 37}
    assert _plan_lighten(hoard, 100) is None  # the world refuses a meal at full energy
    eat = _plan_lighten(hoard, 70)
    assert eat is not None and eat[0] == [{"action": "eat", "qty": 2}] and eat[2] == "lighten"
    assert _plan_lighten({"wood": 5, "berries": 12}, 70) is None  # a dozen berries is food, not ballast
    berries_only = WorldView(x0=54, y0=54, rows=rows, resources=[{"x": 61, "y": 60, "kind": "berries", "amount": 30}, {"x": 62, "y": 60, "kind": "wood", "amount": 30}])
    trip = _plan_gather(bucket, None, {"wood": 2, "berries": 20}, (60, 60), berries_only, None, random.Random(1))
    assert trip is not None and all(a.get("kind") != "berries" for a in trip[0])  # berries at the keep: the pack fills with wood
    store = WorldView(x0=54, y0=54, rows=rows, structures=[{"type": "storehouse", "x": 61, "y": 60, "owner": bucket.name, "policy": "private"}])
    deposit = _plan_deposit(bucket, hoard, (60, 60), store)
    assert deposit is not None and deposit[0][0] == {"action": "give", "x": 61, "y": 60, "item": "berries", "qty": 22}  # keeps fifteen
    farm = WorldView(x0=54, y0=54, rows=rows, structures=[{"type": "farm", "x": 61, "y": 60, "owner": bucket.name, "storage": {"berries": 20}}])
    assert _plan_harvest(bucket, None, hoard, (60, 60), farm, None) is None  # the farm holds the berries for now
    known = WorldView(x0=54, y0=54, rows=rows, resources=[], world_resources=[{"x": 80, "y": 60, "kind": "wood", "amount": 30}, {"x": 90, "y": 90, "kind": "stone", "amount": 9}])
    forage = _plan_forage(bucket, None, {"wood": 2, "berries": 15}, (60, 60), known, None)
    assert forage is not None and forage[0][0]["action"] == "move" and forage[0][0]["x"] > 60 and forage[2] == "forage"
    assert _plan_forage(bucket, None, {"wood": 2, "berries": 15}, (60, 60), berries_only, None) is None  # wood is in view: the gather step takes it


def test_a_full_pack_eats_even_at_full_energy_and_walks_to_a_collective_storehouse():
    from hglab.planner import WorldView, _plan_deposit, _plan_deposit_trip, _plan_lighten

    joe = load_personas(ROOT)["grandpa-joe"]
    rows = ["g" * 128] * 128
    assert _plan_lighten({"wood": 10, "berries": 40}, 100) is None  # the world refuses a meal at full energy
    assert _plan_lighten({"wood": 10, "berries": 40}, 60) == ([{"action": "eat", "qty": 2}], "pack 50/50 with 40 berries: eat 2 to make room for materials", "lighten")
    world = [{"type": "storehouse", "x": 85, "y": 92, "owner": "MotherPail"}, {"type": "storehouse", "x": 76, "y": 62, "owner": "Bishop"}]
    view = WorldView(x0=91, y0=93, rows=rows, structures=[], world_structures=world)
    mates = {"motherpail", "fudgewright", "grandadpail"}
    trip = _plan_deposit_trip(joe, None, {"wood": 10, "berries": 40}, (97, 99), view, None, mates)
    assert trip is not None and trip[2] == "deposit_trip" and trip[0][0]["x"] < 97 and "MotherPail" in trip[1]
    assert _plan_deposit_trip(joe, None, {"wood": 10, "berries": 40}, (97, 99), view, None, {"grandadpail"}) is None  # a stranger's store is not ours
    beside = WorldView(x0=79, y0=86, rows=rows, structures=[{"type": "storehouse", "x": 85, "y": 92, "owner": "MotherPail", "policy": "private"}])
    deposit = _plan_deposit(joe, {"wood": 10, "berries": 40}, (84, 92), beside, None, mates={"MotherPail"})
    assert deposit is not None and deposit[0][0] == {"action": "give", "x": 85, "y": 92, "item": "berries", "qty": 25}


def test_the_harvest_stops_at_the_keep_and_gifts_are_judged_from_where_we_stand():
    import random

    from hglab.engage import board
    from hglab.mood import PersonaState
    from hglab.planner import WorldView, _plan_engage, _plan_harvest

    bucket = load_personas(ROOT)["mrs-bucket"]
    rows = ["g" * 128] * 128
    farm = WorldView(x0=54, y0=54, rows=rows, structures=[{"type": "farm", "x": 61, "y": 60, "owner": bucket.name, "storage": {"berries": 30}}])
    step = _plan_harvest(bucket, None, {"wood": 5, "berries": 18}, (60, 60), farm, None)
    assert step is not None and step[0][-1]["action"] == "take" and step[0][-1]["qty"] == 12  # up to thirty berries in the pack, no more
    assert _plan_harvest(bucket, None, {"wood": 5, "berries": 27}, (60, 60), farm, None) is None  # three more are not worth the trip
    observe = {"tick": 25000, "you": {"name": bucket.name, "x": 60, "y": 60, "inventory": {"wood": 20}}, "agents": [{"name": "Quill", "x": 61, "y": 60}], "events": [], "structures": [], "goals_nearby": [], "your_goals": {}, "since_last_observe": {}, "world": {}, "notebook": {}}
    assert board(bucket, observe, set(), set(), here=(70, 60))["agents_in_view"][0]["distance"] == 9  # measured from where we will stand
    view = WorldView(x0=54, y0=54, rows=rows, agents=observe["agents"])
    bucket.knobs["stance"] = {"cooperative": 1, "neutral": 0, "competitive": 0}
    far = _plan_engage(bucket, None, PersonaState(mood="warm"), {"wood": 20}, (70, 60), view, observe, None, {}, random.Random("g"), set())
    assert far is None or far[2] != "gift"  # after a move away, no gift that the world would refuse as too_far


def test_reachability_costs_hills_double_and_a_trip_stops_beside_a_structure():
    from hglab.planner import WorldView, _plan_deposit_trip, _step_toward, reachable_tiles

    rows = ["g" * 128] * 128
    hills = ["g" * 128] * 60 + ["g" * 64 + "h" * 64] * 8 + ["g" * 128] * 60  # rows 60..67 are hills east of x=64
    flat = WorldView(x0=0, y0=0, rows=rows, full_map=rows)
    hilly = WorldView(x0=0, y0=0, rows=hills, full_map=hills)
    assert (72, 64) in reachable_tiles(flat, (60, 64))  # twelve grass tiles cost twelve
    assert (72, 64) not in reachable_tiles(hilly, (60, 64)) and (68, 64) in reachable_tiles(hilly, (60, 64))  # eight hill tiles cost sixteen; four cost eight
    road = WorldView(x0=0, y0=0, rows=rows, full_map=rows, world_structures=[{"type": "road", "x": 60 + i, "y": 64, "owner": "Cairn"} for i in range(1, 25)])
    assert (84, 64) in reachable_tiles(road, (60, 64))  # roads halve the cost
    store = WorldView(x0=0, y0=0, rows=rows, full_map=rows, world_structures=[{"type": "storehouse", "x": 70, "y": 64, "owner": "Cairn"}])  # known only from the public snapshot
    step = _step_toward((60, 64), {"x": 70, "y": 64}, store)
    assert step is not None and step != (70, 64) and max(abs(step[0] - 70), abs(step[1] - 64)) == 1  # beside the store, never on it
    bell = load_personas(ROOT)["tinker-bell"]
    team = load_team(ROOT, bell.team)
    far = WorldView(x0=68, y0=106, rows=rows, full_map=rows, world_structures=[{"type": "storehouse", "x": 85, "y": 92, "owner": "MotherPail"}])
    assert _plan_deposit_trip(bell, team, {"wood": 3, "berries": 45}, (74, 112), far, None, {"motherpail", "tinkerglow"}) is None  # twenty tiles out of Neverland: the migration would only walk her back
    near = WorldView(x0=68, y0=106, rows=rows, full_map=rows, world_structures=[{"type": "storehouse", "x": 78, "y": 106, "owner": "Stoutheart"}])
    assert _plan_deposit_trip(bell, team, {"wood": 3, "berries": 45}, (74, 112), near, None, {"stoutheart", "tinkerglow"}) is not None


def test_a_build_spends_the_pack_before_the_deposit_is_sized():
    import json
    import random

    from hglab.mood import PersonaState
    from hglab.planner import plan_wake

    personas = load_personas(ROOT)
    tootles = personas["tootles"]
    team = load_team(ROOT, tootles.team)
    observe = load_fixture(FIX / "observe/tootles.json")
    you = observe["you"]
    you["inventory"] = {"stone": 10, "berries": 36}
    you["energy"] = 100
    observe["resources"] = []
    observe["structures"] = [
        {"id": 1, "type": "road", "x": you["x"] - 1, "y": you["y"], "owner": tootles.name, "hp": 20},
        {"id": 2, "type": "storehouse", "x": you["x"] + 1, "y": you["y"], "owner": "LandBroker", "policy": "public"},
    ]
    names = {personas[m].name.casefold(): m for m in team.members if m in personas}
    plan = plan_wake(tootles, team, PersonaState(mood=tootles.mood_model["initial"]), observe, "act", random.Random("r"), teammates=None, terrain_rows=None, allowed=None, team_names=names, work=True, collective_names={p.name for p in personas.values()}, registrar_name="LandBroker")
    gives = [a for a in plan["actions"] if a["action"] == "give"]
    builds = [a for a in plan["actions"] if a["action"] == "build"]
    stone_given = sum(a["qty"] for a in gives if a["item"] == "stone")
    assert stone_given <= 10 - sum(1 for b in builds if b.get("type") == "road"), json.dumps(plan["actions"])  # the road's stone is not deposited twice


def test_a_full_pack_eats_one_berry_after_its_walk_and_never_gifts_a_collective_member():
    import random

    from hglab.mood import PersonaState
    from hglab.planner import WorldView, _meal_after_move, _plan_engage, plan_wake

    assert _meal_after_move([{"action": "move", "x": 1, "y": 1}], {"wood": 10, "berries": 40}, 100, 3) == {"action": "eat", "qty": 1}
    assert _meal_after_move([{"action": "say", "text": "x"}], {"wood": 10, "berries": 40}, 100, 3) is None  # no walk: the meal would be refused at full energy
    assert _meal_after_move([{"action": "move", "x": 1, "y": 1}], {"wood": 10, "berries": 20}, 100, 3) is None  # twenty berries is not a hoard
    assert _meal_after_move([{"action": "move", "x": 1, "y": 1}], {"wood": 14, "fiber": 7, "berries": 25}, 100, 3) == {"action": "eat", "qty": 1}  # a pack of 46 refuses gathering: shed to the keep
    assert _meal_after_move([{"action": "move", "x": 1, "y": 1}], {"wood": 24, "fiber": 7, "berries": 15}, 100, 3) is None  # at the keep, the berries stay
    assert _meal_after_move([{"action": "move", "x": 1, "y": 1}, {"action": "gather", "kind": "wood"}, {"action": "gather", "kind": "wood"}], {"wood": 10, "berries": 40}, 100, 3) is None  # no room
    personas = load_personas(ROOT)
    nibs = personas["nibs"]
    team = load_team(ROOT, nibs.team)
    observe = load_fixture(FIX / "observe/nibs.json")
    observe["you"].update({"energy": 100, "inventory": {"wood": 22, "berries": 28}})
    observe["resources"] = []
    observe["structures"] = []
    names = {personas[m].name.casefold(): m for m in team.members if m in personas}
    plan = plan_wake(nibs, team, PersonaState(mood=nibs.mood_model["initial"]), observe, "act", random.Random("m"), teammates=None, terrain_rows=None, allowed=None, team_names=names, work=True, collective_names={p.name for p in personas.values()})
    kinds = [a["action"] for a in plan["actions"]]
    assert "move" in kinds and kinds[-1] == "eat" and plan["actions"][-1]["qty"] == 1
    bucket = personas["mrs-bucket"]
    bucket.knobs["stance"] = {"cooperative": 1, "neutral": 0, "competitive": 0}
    obs = {"tick": 30000, "you": {"name": bucket.name, "x": 60, "y": 60, "inventory": {"wood": 20}}, "agents": [{"name": "Clarion", "x": 61, "y": 60}], "events": [], "structures": [], "goals_nearby": [], "your_goals": {}, "since_last_observe": {}, "world": {}, "notebook": {}}
    view = WorldView(x0=54, y0=54, rows=["g" * 128] * 128, agents=obs["agents"], liveness={"Clarion": 29990})
    step = _plan_engage(bucket, load_team(ROOT, bucket.team), PersonaState(mood="warm"), {"wood": 20}, (60, 60), view, obs, None, {}, random.Random("c"), {"Clarion", "MotherPail"})
    assert step is None or step[2] != "gift"  # a collective member on another team gets a word, never a gift that their full pack refuses


def test_a_trip_follows_a_route_around_a_ridge_instead_of_bouncing():
    from hglab.planner import WorldView, _route_step, _step_toward

    rows = ["g" * 128] * 128
    ridge = [("g" * 70 + "m" * 2 + "g" * 56) if 60 <= y <= 100 else "g" * 128 for y in range(128)]  # a mountain wall at x=70..71 from y=60 to y=100
    view = WorldView(x0=0, y0=0, rows=ridge, full_map=ridge)
    start, target = (85, 84), (60, 84)
    step = _step_toward(start, {"x": target[0], "y": target[1]}, view)
    assert step is not None and step != start and step[1] > 84  # the route turns south, round the nearer end of the ridge, instead of walking at the wall
    assert abs(step[0] - start[0]) <= 12 and abs(step[1] - start[1]) <= 12
    sealed = [("g" * 60 + "m" + "g" * 67) if y == 84 else ("g" * 60 + "m" * 68) if y in (83, 85) else "g" * 128 for y in range(128)]
    pocket = WorldView(x0=0, y0=0, rows=sealed, full_map=sealed)
    assert _route_step((85, 84), (40, 84), pocket) is None  # walled in on every side: no route at all
    flat = WorldView(x0=0, y0=0, rows=rows, full_map=rows)
    assert _route_step((60, 60), (90, 60), flat) == (72, 60)  # twelve tiles along the straight route
    assert _step_toward((60, 60), {"x": 61, "y": 60}, flat) == (60, 60)  # beside already


def test_tiles_that_blocks_close_are_not_walkable():
    from hglab.planner import WorldView, reachable_tiles

    rows = ["g" * 13] * 13
    observe = {"view": {"x0": 54, "y0": 54, "rows": rows}, "blocks": [{"x": 61, "y": 60, "count": 29, "top": 3, "owner": "Cairn", "closed": True, "door": False}, {"x": 60, "y": 61, "count": 7, "top": 3, "owner": "Lagalong", "closed": False, "door": True}]}
    view = WorldView.from_observe(observe)
    assert (61, 60) in view.closed and not view.walkable(61, 60)
    assert view.walkable(60, 61)  # a door one may use leaves the tile open
    assert (61, 60) not in reachable_tiles(view, (60, 60))
