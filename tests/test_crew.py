"""The factory crew: the pipeline step a hand runs before anything else."""

import json
from pathlib import Path

from hglab.crew import factory_stores, pipeline_of, plan_crew, shortest_first, stock_levels
from hglab.fixtures import FixtureClient, load_fixture
from hglab.lease import acquire
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team, load_teams
from hglab.planner import WorldView
from hglab.wake import persona_wake

ROOT = Path(__file__).parents[1]
FIX = ROOT / "tests/fixtures"
SITE = (89, 99)
ROWS = ["g" * 128] * 128
GRASSY = ["g" * 128] * 95 + ["s" * 128] * 10 + ["g" * 128] * 23  # sand rows 95..104: a farm wants grass, the rest does not care


def _crew(slug):
    personas = load_personas(ROOT)
    return personas[slug], load_team(ROOT, "chocolate-factory"), personas


def _names(personas):
    return {p.name: s for s, p in personas.items()}


def _step(slug, inventory, position, view, observe=None, room=3, energy=80):
    persona, team, personas = _crew(slug)
    observe = observe or {"you": {"x": position[0], "y": position[1], "faction": {"id": 5, "name": "Chocolate Factory"}}, "tick": 100}
    return plan_crew(
        persona, team, PersonaState(mood="busy"), observe, view, dict(inventory), position, energy, persona.energy_reserve, room,
        {p.name for p in personas.values()}, _names(personas), None,
    )


def test_the_team_file_carries_the_pipeline_and_every_hand_its_role():
    teams = load_teams(ROOT)
    cfg = pipeline_of(teams["chocolate-factory"])
    assert cfg["site"] == {"x": 89, "y": 99} and [p["type"] for p in cfg["plan"]][:2] == ["storehouse", "farm"] and cfg["plan"][0]["count"] == 2
    personas = load_personas(ROOT)
    roles = {personas[s].knobs["crew"]["role"] for s in teams["chocolate-factory"].members if "crew" in personas[s].knobs}
    assert roles == {"woodcutter", "quarrier", "provisioner", "hauler", "mason"}
    assert all(personas[s].team == "chocolate-factory" for s in personas if "crew" in personas[s].knobs)
    assert pipeline_of(teams["neverland"]) is None


def test_a_woodcutter_clears_the_forest_nearest_the_works_first():
    nodes = [
        {"x": 80, "y": 99, "kind": "wood", "amount": 30},  # nearer to the hand, farther from the works
        {"x": 87, "y": 98, "kind": "wood", "amount": 30},
        {"x": 86, "y": 97, "kind": "wood", "amount": 4},  # at the floor: left alone
        {"x": 90, "y": 96, "kind": "berries", "amount": 12},
    ]
    view = WorldView(x0=70, y0=90, rows=ROWS, resources=nodes, full_map=ROWS)
    step = _step("loompa-woodcutter", {"wood": 5}, (79, 99), view)
    assert step is not None and step[2] == "crew"
    kinds = [a["action"] for a in step[0]]
    assert kinds == ["move", "gather"] and step[0][1]["kind"] == "wood"
    stand = (step[0][0]["x"], step[0][0]["y"])
    assert max(abs(stand[0] - 87), abs(stand[1] - 98)) <= 1  # the node at (87,98), two tiles from the works, before the one beside the hand
    beside = _step("loompa-woodcutter", {"wood": 5}, (88, 99), view)
    assert beside[0] == [{"action": "gather", "kind": "wood"}]
    assert _step("loompa-woodcutter", {"wood": 5}, (79, 99), view, room=1) is None or step[0][0]["action"] == "move"  # one slot: no trip without its gather


def test_a_heavy_pack_is_unloaded_into_the_nearest_factory_store_with_room():
    store = {"id": 1, "type": "storehouse", "x": 90, "y": 98, "owner": "Toffeetrowel", "policy": "faction", "faction": "Chocolate Factory", "storage": {"wood": 40}}
    view = WorldView(x0=80, y0=90, rows=ROWS, structures=[store], full_map=ROWS)
    step = _step("loompa-woodcutter", {"wood": 34, "berries": 10}, (89, 99), view)
    assert step[0] == [{"action": "give", "x": 90, "y": 98, "item": "wood", "qty": 34}] and "unload" in step[1]
    far = _step("loompa-woodcutter", {"wood": 34, "berries": 10}, (84, 99), view)
    assert far[0][0]["action"] == "move" and "carry it to the store at (90, 98)" in far[1]
    full = {**store, "storage": {"wood": 498}}
    state = PersonaState(mood="busy")
    persona, team, personas = _crew("loompa-woodcutter")
    none = plan_crew(persona, team, state, {"you": {"x": 89, "y": 99}, "tick": 500}, WorldView(x0=80, y0=90, rows=ROWS, structures=[full], full_map=ROWS), {"wood": 34, "berries": 10}, (89, 99), 80, 20, 3, set(), _names(personas), None)
    assert (none is None or none[0][0]["action"] != "give") and "90,98" in state.flags["full_stores"]  # a full store is remembered, not hammered


def test_the_first_store_is_raised_at_the_works_by_whoever_can_pay():
    view = WorldView(x0=80, y0=90, rows=ROWS, full_map=ROWS)
    step = _step("loompa-quarrier", {"wood": 20, "stone": 10, "berries": 4}, (89, 99), view)
    build = step[0][0]
    assert build["action"] == "build" and build["type"] == "storehouse" and build["policy"] == "faction"
    assert max(abs(build["x"] - 89), abs(build["y"] - 99)) == 1
    walking = _step("loompa-quarrier", {"wood": 20, "stone": 10}, (80, 99), view)
    assert walking[0][0]["action"] == "move" and "first store" in walking[1]
    short = _step("loompa-quarrier", {"wood": 20, "stone": 2}, (89, 99), WorldView(x0=80, y0=90, rows=ROWS, full_map=ROWS, resources=[{"x": 82, "y": 93, "kind": "stone", "amount": 17}]))
    assert short[0][-1] == {"action": "gather", "kind": "stone"}  # stone is the shortfall for the store: fetch it before ore


def test_the_mason_raises_the_plan_in_order_beside_the_store_that_pays():
    stores = [
        {"id": 1, "type": "storehouse", "x": 90, "y": 98, "owner": "Treacleaxe", "policy": "faction", "faction": "Chocolate Factory", "storage": {"wood": 60, "stone": 30, "fiber": 10}},
        {"id": 2, "type": "storehouse", "x": 88, "y": 98, "owner": "Nougatpick", "policy": "faction", "faction": "Chocolate Factory", "storage": {}},
    ]
    view = WorldView(x0=80, y0=90, rows=GRASSY, structures=stores, world_structures=stores, full_map=GRASSY)
    observe = {"you": {"x": 89, "y": 97, "faction": {"id": 5, "name": "Chocolate Factory"}}, "tick": 100}
    step = _step("loompa-mason", {"berries": 5}, (89, 97), view, observe)
    build = step[0][0]
    assert build["action"] == "build" and build["type"] == "farm" and view.terrain(build["x"], build["y"]) == "g" and "paid from the pack and the store beside me" in step[1]
    away = _step("loompa-mason", {"berries": 5}, (84, 94), view, {"you": {"x": 84, "y": 94}, "tick": 100})
    assert away[0][0]["action"] == "move" and "stand by the store" in away[1]
    empty = [{**stores[0], "storage": {"wood": 2}}, stores[1]]
    poor = WorldView(x0=80, y0=90, rows=GRASSY, structures=empty, world_structures=empty, full_map=GRASSY, resources=[{"x": 91, "y": 94, "kind": "fiber", "amount": 16}])
    by_hand = _step("loompa-mason", {"berries": 5}, (89, 97), poor, observe)
    assert by_hand[0][-1] == {"action": "gather", "kind": "fiber"} and "for the farm" in by_hand[1]
    done = stores + [
        {"id": 3, "type": "farm", "x": 90, "y": 94, "owner": "Toffeetrowel"}, {"id": 4, "type": "farm", "x": 91, "y": 94, "owner": "Toffeetrowel"},
        {"id": 5, "type": "hut", "x": 88, "y": 100, "owner": "Toffeetrowel"}, {"id": 6, "type": "tower", "x": 91, "y": 98, "owner": "Toffeetrowel"},
        {"id": 7, "type": "sign", "x": 89, "y": 100, "owner": "Toffeetrowel"},
    ]
    assert _step("loompa-mason", {"berries": 5}, (89, 97), WorldView(x0=80, y0=90, rows=GRASSY, structures=done, world_structures=done, full_map=GRASSY), observe) is None  # the works stand


def test_the_hauler_takes_what_the_works_is_shortest_of_from_an_open_store_beside_it():
    factory = {"id": 1, "type": "storehouse", "x": 90, "y": 98, "owner": "Treacleaxe", "policy": "faction", "faction": "Chocolate Factory", "storage": {"wood": 150, "stone": 10}}
    open_store = {"id": 2, "type": "storehouse", "x": 80, "y": 88, "owner": "MotherPail", "policy": "public", "storage": {"stone": 40, "berries": 30, "wood": 50}}  # outside the works' radius: a source, not a factory store
    view = WorldView(x0=74, y0=84, rows=ROWS, structures=[factory, open_store], world_structures=[factory, open_store], full_map=ROWS)
    step = _step("loompa-hauler", {"berries": 6}, (80, 89), view)
    assert step[0][0]["action"] == "take" and (step[0][0]["x"], step[0][0]["y"]) == (80, 88) and step[0][0]["item"] in {"stone", "fiber", "berries"} and step[0][0]["qty"] == 20
    levels = stock_levels([factory], {"wood": 200, "stone": 150, "ore": 30})
    assert shortest_first(levels)[0] in {"ore", "stone"} and levels["wood"] == (150, 200)
    private = {**open_store, "policy": "private"}
    gathering = _step("loompa-hauler", {"berries": 6}, (80, 89), WorldView(x0=74, y0=84, rows=ROWS, structures=[factory, private], world_structures=[factory, private], full_map=ROWS, resources=[{"x": 82, "y": 93, "kind": "stone", "amount": 17}]))
    assert all(a["action"] != "take" for a in gathering[0])  # a private store is never touched


def test_a_hand_far_from_the_works_walks_there_and_a_hungry_one_eats_from_the_store():
    view = WorldView(x0=30, y0=30, rows=ROWS, full_map=ROWS)
    step = _step("loompa-provisioner", {"fiber": 3}, (40, 40), view)
    assert step[0][0]["action"] == "move" and "walk there" in step[1]
    store = {"id": 1, "type": "storehouse", "x": 90, "y": 98, "owner": "Sherbetsack", "policy": "faction", "faction": "Chocolate Factory", "storage": {"berries": 24}}
    near = WorldView(x0=80, y0=90, rows=ROWS, structures=[store], full_map=ROWS)
    hungry = _step("loompa-provisioner", {"fiber": 3, "berries": 1}, (89, 99), near, energy=28)
    assert hungry[0] == [{"action": "take", "x": 90, "y": 98, "item": "berries", "qty": 10}]
    assert factory_stores(near, {"sherbetsack"}, SITE, 7)[0]["id"] == 1 and factory_stores(near, {"someone"}, SITE, 7) == []


def test_a_hand_s_shift_wake_runs_the_pipeline_before_anything_else(tmp_path):
    personas = load_personas(ROOT)
    for slug in ("loompa-woodcutter", "loompa-mason"):
        persona = personas[slug]
        observe = load_fixture(FIX / f"observe/{slug}.json")
        client = FixtureClient(observe)
        lease = acquire(client, persona.name)
        record = persona_wake(
            persona=persona, team=load_team(ROOT, persona.team), personas=personas, client=client, lease=lease, root=ROOT,
            output_dir=tmp_path, dry_run=True, work=True, seed="crew",
        )
        record = record[0] if isinstance(record, tuple) else record
        kinds = [a["action"] for a in record["actions"] if a["action"] != "remember"]
        assert record["approach"] == "crew" and kinds, (slug, record["summary"], record["reasons"])
        assert kinds[0] in {"move", "gather", "give", "build", "take"}
        assert "inbox" not in json.dumps(record)


def test_a_hand_s_character_wake_is_the_pipeline_too_and_never_wanders_back(tmp_path):
    personas = load_personas(ROOT)
    persona = personas["loompa-quarrier"]
    observe = load_fixture(FIX / "observe/loompa-quarrier.json")
    observe["you"].update({"x": 60, "y": 60, "energy": 90})  # far from the works: every slot walks toward them
    observe["you"]["faction"] = {"id": 5, "name": "Chocolate Factory"}
    observe["resources"] = [{"x": 59, "y": 61, "kind": "wood", "amount": 30}]
    observe["view"]["x0"], observe["view"]["y0"] = 54, 54
    client = FixtureClient(observe)
    lease = acquire(client, persona.name)
    record = persona_wake(
        persona=persona, team=load_team(ROOT, persona.team), personas=personas, client=client, lease=lease, root=ROOT,
        output_dir=tmp_path, dry_run=True, work=False, seed="crew",
    )
    record = record[0] if isinstance(record, tuple) else record
    moves = [a for a in record["actions"] if a["action"] == "move"]
    assert record["approach"] == "crew" and moves and all(a["action"] in {"move", "remember"} for a in record["actions"])
    here = (60, 60)
    for a in moves:
        assert max(abs(a["x"] - 89), abs(a["y"] - 99)) < max(abs(here[0] - 89), abs(here[1] - 99))  # each step is closer to the works, none back to the wood node
        here = (a["x"], a["y"])
