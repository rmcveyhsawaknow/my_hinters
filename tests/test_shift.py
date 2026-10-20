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
