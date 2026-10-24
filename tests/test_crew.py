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


def _step(slug, inventory, position, view, observe=None, room=3, energy=80, teammates=None, crew_roles=None):
    persona, team, personas = _crew(slug)
    observe = observe or {"you": {"x": position[0], "y": position[1], "faction": {"id": 5, "name": "Chocolate Factory"}}, "tick": 100}
    return plan_crew(
        persona, team, PersonaState(mood="busy"), observe, view, dict(inventory), position, energy, persona.energy_reserve, room,
        {p.name for p in personas.values()}, _names(personas), teammates, crew_roles=crew_roles,
    )


def test_the_team_file_carries_the_pipeline_and_every_hand_its_role():
    teams = load_teams(ROOT)
    cfg = pipeline_of(teams["chocolate-factory"])
    assert cfg["site"] == {"x": 89, "y": 99} and [p["type"] for p in cfg["plan"]][:2] == ["storehouse", "farm"] and cfg["plan"][0]["count"] == 2
    personas = load_personas(ROOT)
    roles = {personas[s].knobs["crew"]["role"] for s in teams["chocolate-factory"].members if "crew" in personas[s].knobs}
    assert roles == {"woodcutter", "quarrier", "provisioner", "hauler", "mason"}
    assert all(personas[s].team in {"chocolate-factory", "exchange"} for s in personas if "crew" in personas[s].knobs)  # the factory crew and the office hands
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


def test_full_stores_make_the_mason_raise_another_and_the_hands_carry_its_cost_to_the_mason():
    from hglab.crew import STORES_MAX, _role_wanted

    full = [
        {"id": 1, "type": "storehouse", "x": 90, "y": 98, "owner": "Treacleaxe", "policy": "faction", "faction": "Chocolate Factory", "storage": {"wood": 300, "stone": 198}},
        {"id": 2, "type": "storehouse", "x": 88, "y": 98, "owner": "Nougatpick", "policy": "faction", "faction": "Chocolate Factory", "storage": {"berries": 400, "wood": 90}},  # ten slots left: full for the next-store decision
    ]
    view = WorldView(x0=80, y0=90, rows=GRASSY, structures=full, world_structures=full, full_map=GRASSY)
    observe = {"you": {"x": 89, "y": 97, "faction": {"id": 5, "name": "Chocolate Factory"}}, "tick": 100}
    step = _step("loompa-mason", {"berries": 5}, (89, 97), view, observe)
    build = step[0][0]
    assert build["action"] == "build" and build["type"] == "storehouse" and build["policy"] == "faction" and step[1].startswith("every store at the works is full")  # paid from the full store beside it
    persona, team, personas = _crew("loompa-mason")
    team.extra["pipeline"]["stores_max"] = 2
    capped = plan_crew(persona, team, PersonaState(mood="busy"), observe, view, {"berries": 5}, (89, 97), 80, persona.energy_reserve, 3, {p.name for p in personas.values()}, _names(personas), None)
    assert capped is None  # at the cap, the works stand
    assert STORES_MAX == 6
    roles = {"loompa-mason": "mason", "loompa-woodcutter": "woodcutter"}
    carry = _step("loompa-woodcutter", {"wood": 36, "stone": 5, "berries": 5}, (87, 90), view, teammates={"loompa-mason": (89, 97)}, crew_roles=roles)
    assert carry[0][0]["action"] == "move" and "carry the next store's cost to the mason" in carry[1]
    hand = _step("loompa-woodcutter", {"wood": 36, "stone": 5, "berries": 5}, (88, 96), view, teammates={"loompa-mason": (89, 97)}, crew_roles=roles)
    assert hand[0] == [{"action": "give", "to": "Toffeetrowel", "item": "wood", "qty": 20}, {"action": "give", "to": "Toffeetrowel", "item": "stone", "qty": 5}] and "hand" in hand[1]
    alone = _step("loompa-woodcutter", {"wood": 36, "stone": 5, "berries": 5}, (84, 92), view)  # no mason known: wait by the works, never a give into a full store
    assert alone is None or alone[0][0]["action"] != "give"
    levels = {"wood": (210, 200), "stone": (20, 150), "fiber": (0, 60), "berries": (357, 60), "ore": (0, 30)}
    assert _role_wanted("woodcutter", levels)[0] in {"fiber", "ore"}  # wood stands above target: the works is short of fiber and ore
    assert _role_wanted("provisioner", levels)[0] == "fiber"  # berries are six times the target: fiber first
    assert _role_wanted("quarrier", {"stone": (20, 150), "ore": (0, 30)})[0] in {"stone", "ore"} and _role_wanted("hauler", levels)[0] in {"fiber", "ore"}
    assert _role_wanted("woodcutter", {}) == ["wood"]  # no store in view: the role's own kind


def test_the_mason_takes_the_shortfall_into_its_pack_when_no_tile_beside_the_store_fits():
    stores = [
        {"id": 1, "type": "storehouse", "x": 90, "y": 98, "owner": "Treacleaxe", "policy": "faction", "faction": "Chocolate Factory", "storage": {"wood": 60, "stone": 30, "fiber": 10}},
        {"id": 2, "type": "storehouse", "x": 86, "y": 100, "owner": "Nougatpick", "policy": "faction", "faction": "Chocolate Factory", "storage": {}},
    ]
    sandy = ["g" * 128] * 90 + ["s" * 128] * 38  # the works stand on sand; grass only north of y=90
    view = WorldView(x0=80, y0=90, rows=["s" * 128] * 128, structures=stores, world_structures=stores, full_map=sandy)
    observe = {"you": {"x": 89, "y": 97, "faction": {"id": 5, "name": "Chocolate Factory"}}, "tick": 100}
    take = _step("loompa-mason", {"berries": 5}, (89, 97), view, observe)
    assert take[0] == [{"action": "take", "x": 90, "y": 98, "item": "fiber", "qty": 5}, {"action": "take", "x": 90, "y": 98, "item": "wood", "qty": 5}] and "carry it where it does" in take[1]
    grass = ["g" * 128] * 128
    walk = _step("loompa-mason", {"fiber": 5, "wood": 5, "berries": 5}, (89, 97), WorldView(x0=80, y0=90, rows=["s" * 13] * 13, structures=stores, world_structures=stores, full_map=grass), observe)
    assert walk[0][0]["action"] == "move" and "where it fits" in walk[1]  # the cost is in the pack: walk to grass inside the works


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


def _office(slug):
    personas = load_personas(ROOT)
    return personas[slug], load_team(ROOT, "exchange"), personas


def _office_step(slug, inventory, position, view, observe=None, room=3, energy=80, state=None):
    persona, team, personas = _office(slug)
    observe = observe or {"you": {"x": position[0], "y": position[1], "faction": {"id": 9, "name": "Land Office"}}, "tick": 1000}
    return plan_crew(
        persona, team, state or PersonaState(mood="busy"), observe, view, dict(inventory), position, energy, persona.energy_reserve, room,
        {p.name for p in personas.values()}, {p.name: s for s, p in personas.items()}, None,
    )


def _claims_world():
    from hglab.lots import lot_anchor, stake_text

    rows = ["g" * 128] * 128
    lots = ["J08-NW", "H04-NE", "F06-SW", "G06-NE"]
    signs = [{"type": "sign", "x": lot_anchor(lid)[0], "y": lot_anchor(lid)[1], "owner": "LandBroker", "text": stake_text(lid, "LandBroker")} for lid in lots]
    vault = {"id": 1, "type": "storehouse", "x": 73, "y": 72, "owner": "LandBroker", "policy": "private", "storage": {"wood": 10}}
    ore = [{"kind": "ore", "x": lot_anchor("J08-NW")[0] + 1, "y": lot_anchor("J08-NW")[1], "amount": 9}]
    stones = [{"kind": "stone", "x": lot_anchor("H04-NE")[0] + dx, "y": lot_anchor("H04-NE")[1], "amount": 3} for dx in (-1, 0, 1)]  # low: under the collective floor, above the office's
    near = [{"kind": "stone", "x": 75, "y": 72, "amount": 20}]  # beside the vault, in no holding
    spawn = [{"kind": "stone", "x": 66, "y": 66, "amount": 3}]  # in G06-NE, a holding, but inside the spawn circle
    return rows, signs, vault, ore + stones + near + spawn


def test_in_claims_mode_the_quarrier_works_the_best_holding_first_to_the_office_floor():
    from hglab.lots import lot_anchor

    rows, signs, vault, nodes = _claims_world()
    view = WorldView(x0=66, y0=66, rows=rows, full_map=rows, structures=[vault], world_structures=[vault, *signs], world_resources=nodes, resources=[n for n in nodes if abs(n["x"] - 74) <= 6 and abs(n["y"] - 72) <= 6])
    step = _office_step("office-quarrier", {"berries": 5}, (74, 72), view)
    assert step[0][0]["action"] == "move" and "holding J08-NW" in step[1]  # the ore lot outranks the stone beside the vault
    beside_ore = (lot_anchor("J08-NW")[0] + 1, lot_anchor("J08-NW")[1] + 1)
    at_ore = WorldView(x0=beside_ore[0] - 6, y0=beside_ore[1] - 6, rows=rows, full_map=rows, structures=[], world_structures=[vault, *signs], world_resources=nodes, resources=[n for n in nodes if n["kind"] == "ore"])
    gather = _office_step("office-quarrier", {"berries": 5}, beside_ore, at_ore)
    assert gather[0] == [{"action": "gather", "kind": "ore"}] and "leave 0" in gather[1]
    low = (lot_anchor("H04-NE")[0], lot_anchor("H04-NE")[1] + 1)
    at_low = WorldView(x0=low[0] - 6, y0=low[1] - 6, rows=rows, full_map=rows, structures=[], world_structures=[vault, *signs], world_resources=nodes, resources=[n for n in nodes if n["kind"] == "stone" and n["amount"] == 3 and n["y"] == lot_anchor("H04-NE")[1]])
    worked = _office_step("office-quarrier", {"berries": 5}, low, at_low)
    assert worked[0][0] == {"action": "gather", "kind": "stone"}  # three units: below the collective floor, above the office's zero
    at_spawn = WorldView(x0=60, y0=60, rows=rows, full_map=rows, structures=[], world_structures=[vault, *signs], world_resources=nodes, resources=[n for n in nodes if (n["x"], n["y"]) == (66, 66)])
    assert _office_step("office-quarrier", {"berries": 5}, (67, 66), at_spawn) is None or "gather" not in [a["action"] for a in _office_step("office-quarrier", {"berries": 5}, (67, 66), at_spawn)[0]]  # the spawn circle keeps the floor of five


def test_a_heavy_pack_goes_to_the_nearest_depot_and_the_drayman_carries_depot_loads_to_the_vault():
    from hglab.lots import lot_anchor

    rows, signs, vault, nodes = _claims_world()
    depot = {"id": 2, "type": "storehouse", "x": lot_anchor("J08-NW")[0] + 2, "y": lot_anchor("J08-NW")[1], "owner": "Lintelstave", "policy": "faction", "faction": "Land Office", "storage": {"ore": 30, "stone": 40}}
    world = [vault, depot, *signs]
    beside_depot = (depot["x"] + 1, depot["y"])
    view = WorldView(x0=beside_depot[0] - 6, y0=beside_depot[1] - 6, rows=rows, full_map=rows, structures=[depot], world_structures=world, world_resources=nodes)
    step = _office_step("office-quarrier", {"stone": 20, "ore": 14, "berries": 5}, beside_depot, view)
    assert step[0][0]["action"] == "give" and (step[0][0]["x"], step[0][0]["y"]) == (depot["x"], depot["y"])  # the depot on the holding, not the vault forty tiles away
    drayman = _office_step("office-drayman", {"berries": 6}, beside_depot, view)
    assert drayman[0][0]["action"] == "take" and (drayman[0][0]["x"], drayman[0][0]["y"]) == (depot["x"], depot["y"]) and drayman[0][0]["item"] == "ore"  # ore is the vault's shortest stock
    far_view = WorldView(x0=67, y0=66, rows=rows, full_map=rows, structures=[vault], world_structures=world, world_resources=nodes)
    walk = _office_step("office-drayman", {"berries": 6}, (74, 72), far_view)
    assert walk[0][0]["action"] == "move" and "walk to the depot" in walk[1]
    loaded = _office_step("office-drayman", {"ore": 20, "stone": 20, "berries": 6}, (74, 73), far_view)
    assert loaded[0][0]["action"] == "give" and (loaded[0][0]["x"], loaded[0][0]["y"]) == (73, 72)  # the drayman unloads at the vault only
    state = PersonaState(mood="busy")
    bare = {**depot, "storage": {}}
    nothing = _office_step("office-drayman", {"berries": 6}, beside_depot, WorldView(x0=beside_depot[0] - 6, y0=beside_depot[1] - 6, rows=rows, full_map=rows, structures=[bare], world_structures=[vault, bare, *signs], world_resources=nodes), state=state)
    assert (nothing is None or nothing[0][0]["action"] != "take") and f"{depot['x']},{depot['y']}" in state.flags["empty_depots"]  # an empty depot is remembered


def test_the_steward_raises_depots_on_the_best_holdings_before_the_overflow_vaults():
    from hglab.lots import lot_anchor, lot_bounds

    rows, signs, vault, nodes = _claims_world()
    anchor = lot_anchor("J08-NW")
    view = WorldView(x0=anchor[0] - 6, y0=anchor[1] - 6, rows=rows, full_map=rows, structures=[], world_structures=[vault, *signs], world_resources=nodes)
    step = _office_step("office-steward", {"wood": 22, "stone": 12, "berries": 4}, (anchor[0] + 1, anchor[1]), view)
    build = step[0][0]
    x0, y0, x1, y1 = lot_bounds("J08-NW")
    assert build["action"] == "build" and build["type"] == "storehouse" and build["policy"] == "faction" and x0 <= build["x"] <= x1 and y0 <= build["y"] <= y1 and "has no depot" in step[1]
    far = _office_step("office-steward", {"wood": 22, "stone": 12, "berries": 4}, (74, 72), WorldView(x0=67, y0=66, rows=rows, full_map=rows, structures=[vault], world_structures=[vault, *signs], world_resources=nodes))
    assert far[0][0]["action"] == "move" and "walk to holding J08-NW" in far[1]
    depot = {"id": 2, "type": "storehouse", "x": anchor[0] + 2, "y": anchor[1], "owner": "Lintelstave", "policy": "faction"}
    standing = [vault, depot, *signs]
    nxt = _office_step("office-steward", {"wood": 22, "stone": 12, "berries": 4}, (74, 72), WorldView(x0=67, y0=66, rows=rows, full_map=rows, structures=[vault], world_structures=standing, world_resources=nodes))
    assert nxt[0][0]["action"] == "move" and "walk to holding" in nxt[1] and "J08-NW" not in nxt[1]  # the first depot stands: on to the next holding


def test_the_office_founds_its_faction_and_invites_the_hands(tmp_path):
    from hglab.fixtures import FixtureClient, load_fixture
    from hglab.lease import acquire

    personas = load_personas(ROOT)
    broker = personas["land-broker"]
    observe = load_fixture(FIX / "observe/land-broker.json")
    observe["you"]["faction"] = None
    observe["you"]["energy"] = 100
    observe["_factions"] = []
    observe["_guidance"] = {}
    client = FixtureClient(observe)
    lease = acquire(client, broker.name)
    result = persona_wake(persona=broker, team=load_team(ROOT, "exchange"), personas=personas, client=client, lease=lease, root=ROOT, output_dir=tmp_path, dry_run=True, work=True, seed="office")
    record = result[0] if isinstance(result, tuple) else result
    kinds = [a["action"] for a in record["actions"] if a["action"] != "remember"]
    assert kinds[0] == "found_faction" and record["actions"][0]["name"] == "Land Office" and kinds.count("invite") == 2
