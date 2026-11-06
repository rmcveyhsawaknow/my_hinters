"""Idle builders of 2026-11-06: Fudgewright walled in for 22 hours on the one open tile inside the Gobstopper Foundry,
Stoutheart's every crew wake refused for a walk out of Neverland, and the factory's hands gathering on while MotherPail
alone raised the East Works."""

import random
from pathlib import Path

import yaml

from hglab import factory
from hglab.blocks import escape_door
from hglab.crew import plan_crew
from hglab.mood import PersonaState
from hglab.persona import leaves_territory, load_personas, load_team
from hglab.planner import WorldView, _plan_crew, plan_wake

ROOT = Path(__file__).resolve().parents[1]
GRASS = ["g" * 128] * 128
FOUNDRY = (105, 62)  # the open tile the foundry's plinth and courses wall in


def _foundry_root(tmp_path):
    """A design holding the Gobstopper Foundry alone, as the factory draws it."""
    gob = next(s for s in factory.load_design(ROOT, "chocolate-factory")["sections"] if s["id"] == "gobstopper")
    (tmp_path / "teams" / "blueprints").mkdir(parents=True)
    design = {"name": "Foundry", "title": "the foundry blueprint", "team": "chocolate-factory", "version": 1, "sections": [gob]}
    (tmp_path / "teams" / "blueprints" / "foundry.yaml").write_text(yaml.safe_dump(design), encoding="utf-8")
    return tmp_path


def test_the_open_tiles_a_design_walls_in_are_traps_and_only_the_factory_has_any():
    _design, steps, _ = factory.blueprint(ROOT, "chocolate-factory")
    traps = factory.trap_tiles(steps)
    assert {FOUNDRY, (105, 68)} <= traps  # the Gobstopper Foundry's and the Toffee Works' walled-in tiles
    assert (104, 64) not in traps  # the foundry's door opens its tile, plinth and all
    assert (107, 62) not in traps and (102, 62) not in traps  # the ground round it
    assert factory.trap_tiles(steps) is traps  # cached per design version
    assert _pockets(steps) == {FOUNDRY, (105, 68)}
    for name in ("nintendo-land", "halloween", "signposts", "midtown", "central-park", "uptown", "lower-manhattan", "treetop-hideaway"):
        assert _pockets(factory.blueprint(ROOT, name)[1]) == set(), name  # no other design walls anyone in
    assert factory.trap_tiles([]) == set()


def _pockets(steps):
    """The traps no block of the design closes: open tiles it walls in."""
    shut = set()
    for step in steps:
        act = step["action"]
        if step["kind"] == "place" and act.get("shape") != "door" and int(act["bz"]) <= 5 and not (act.get("shape") in ("slab", "slope") and int(act.get("bz2", act["bz"])) == 0):
            shut |= {(x, y) for x in range(act["bx"] // 4, act.get("bx2", act["bx"]) // 4 + 1) for y in range(act["by"] // 4, act.get("by2", act["by"]) // 4 + 1)}
    return factory.trap_tiles(steps) - shut


def test_a_builder_inside_a_building_steps_out_to_lay_its_courses(tmp_path):
    root = _foundry_root(tmp_path)
    personas = load_personas(ROOT)
    wonka, team = personas["wonka"], load_team(ROOT, "chocolate-factory")
    _design, steps, _ = factory.blueprint(root, "foundry")
    traps = factory.trap_tiles(steps)
    assert FOUNDRY in traps
    observe = {"you": {"x": FOUNDRY[0], "y": FOUNDRY[1], "faction": {"id": 5, "name": "Chocolate Factory"}, "blocks_owned": 0}, "tick": 1000}
    view = WorldView(x0=98, y0=56, rows=GRASS, full_map=GRASS, tick=1000)
    step = factory.plan_step(wonka, team, PersonaState(mood="busy"), observe, view, {"stone": 40, "berries": 5}, FOUNDRY, 3, root=root, hands=True, design_name="foundry")
    assert step is not None and step[2] == "blueprint"
    move, place = step[0][0], step[0][-1]
    assert move["action"] == "move" and (move["x"], move["y"]) not in traps  # he no longer lays the walls from the tile they close round him
    assert place["action"] == "place"
    outside = (102, 62)
    again = factory.plan_step(wonka, team, PersonaState(mood="busy"), {**observe, "you": {**observe["you"], "x": outside[0], "y": outside[1]}}, view, {"stone": 40, "berries": 5}, outside, 3, root=root, hands=True, design_name="foundry")
    assert again is not None and again[0][0]["action"] == "place"  # outside already: no walk at all


def _ring(here, closed):
    def walkable(x, y):
        return (x, y) not in closed and abs(x - here[0]) <= 6 and abs(y - here[1]) <= 6

    def openable(x, y):
        return (x, y) in closed

    return walkable, openable


def test_a_walker_walled_in_puts_a_door_of_its_own_in_a_wall_that_opens_onto_open_ground():
    here = FOUNDRY
    shut = {(104, 61), (105, 61), (106, 61), (104, 62), (106, 62), (104, 63), (105, 63), (106, 63), (103, 61), (103, 62), (103, 63), (103, 64), (104, 64), (105, 64), (106, 64)}
    walkable, openable = _ring(here, shut)
    north_wall = {(bx, 244, bz) for bx in range(412, 428) for bz in range(3)}
    filled = north_wall | {(bx, by, 0) for bx in range(420, 424) for by in range(245, 247)}  # the first two rows of (105,61) taken at the ground
    out = escape_door(here, walkable, openable, filled, {"wood": 4, "fiber": 5, "berries": 25})
    assert out is not None
    actions, reason = out
    assert len(actions) == 1 and "walled in at (105, 62)" in reason
    door = actions[0]
    assert door["action"] == "place" and door["shape"] == "door" and door["material"] == "wood" and door["bz"] == 0 and door["bz2"] == 1
    tile = (door["bx"] // 4, door["by"] // 4)
    assert tile == (105, 61) and door["facing"] == "north"  # beside him, square on, and the ground beyond it is open
    assert (door["bx"], door["by"], 0) not in filled and (door["bx"], door["by"], 1) not in filled
    assert escape_door(here, walkable, openable, filled, {"berries": 25}) is None  # nothing to make a door of
    assert escape_door(here, _ring(here, set())[0], openable, filled, {"wood": 4}) is None  # the way out is open


def test_a_door_into_another_wall_is_no_way_out():
    here = (20, 20)
    shut = {(x, y) for x in range(17, 24) for y in range(17, 24)} - {here}  # walls three deep: no neighbouring wall opens onto open ground
    walkable, openable = _ring(here, shut)
    assert escape_door(here, walkable, openable, set(), {"wood": 4}) is None


def test_the_wake_of_a_walled_in_builder_is_his_way_out_and_the_view_trusts_its_own_door():
    personas = load_personas(ROOT)
    wonka, team = personas["wonka"], load_team(ROOT, "chocolate-factory")
    ring = [(FOUNDRY[0] + dx, FOUNDRY[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
    observe = {
        "tick": 176000, "inbox": [], "events": [], "structures": [], "resources": [],
        "view": {"x0": 99, "y0": 56, "rows": ["g" * 13] * 13},
        "blocks": [{"x": x, "y": y, "count": 8, "top": 2, "owner": "Fudgewright", "closed": True, "door": False} for x, y in ring],
        "_closed_world": [list(t) for t in ring],
        "_cells_near": [[bx, 244, bz] for bx in range(412, 428) for bz in range(3)],
        "you": {"name": "Fudgewright", "x": FOUNDRY[0], "y": FOUNDRY[1], "energy": 100, "inventory": {"wood": 4, "fiber": 5, "berries": 25}, "faction": {"id": 5, "name": "Chocolate Factory"}, "blocks_owned": 900},
    }
    plan = plan_wake(wonka, team, PersonaState(mood="busy"), observe, "work", random.Random(1), terrain_rows=GRASS, work=True)
    assert plan["approach"] == "escape" and plan["actions"][0]["shape"] == "door"
    door_tile = (plan["actions"][0]["bx"] // 4, plan["actions"][0]["by"] // 4)
    after = {**observe, "blocks": [b if (b["x"], b["y"]) != door_tile else {**b, "closed": False, "door": True} for b in observe["blocks"]]}
    view = WorldView.from_observe(after, GRASS)
    assert view.walkable(*door_tile)  # the public file still shows the tile shut; the view's own reading opens it
    again = plan_wake(wonka, team, PersonaState(mood="busy"), after, "work", random.Random(1), terrain_rows=GRASS, work=True)
    assert again["approach"] != "escape"  # one door is enough


def test_stoutheart_never_plans_a_step_out_of_neverland(monkeypatch):
    from hglab import crew
    from hglab import help as helping

    personas = load_personas(ROOT)
    nibs, neverland = personas["nibs"], load_team(ROOT, "neverland")
    assert neverland.binding_territory and nibs.territory_mode == "stay_inside"
    out, home = [{"action": "move", "x": 71, "y": 85}], [{"action": "move", "x": 72, "y": 104}]
    assert leaves_territory(nibs, neverland, out) and not leaves_territory(nibs, neverland, home)
    assert not leaves_territory(personas["tootles"], neverland, out)  # a wanderer may go where he likes
    assert not leaves_territory(nibs, neverland, [{"action": "place", "bx": 284, "by": 340, "bz": 0}])  # a place is no walk

    monkeypatch.setattr(crew, "plan_crew", lambda *a, **k: (out, "carrying wood toward Nintendo Land", "blueprint"))
    monkeypatch.setattr(helping, "plan_help", lambda *a, **k: (out, "a hand lent to the office", "help"))
    monkeypatch.setattr(helping, "plan_roam", lambda *a, **k: (home, "the hideaway's grounds, tree to tree", "roam"))
    here = (73, 109)
    view = WorldView(x0=here[0] - 6, y0=here[1] - 6, rows=GRASS, full_map=GRASS, tick=1000)
    observe = {"you": {"x": here[0], "y": here[1], "faction": {"id": 6, "name": "Neverland"}, "blocks_owned": 0}, "tick": 1000}
    step = _plan_crew(nibs, neverland, PersonaState(mood="busy"), observe, view, {"wood": 10}, here, 90, nibs.energy_reserve, 3, None, None, None)
    assert step is not None and step[0] == home  # the knob check would have refused the whole wake for either walk out


def test_the_next_design_away_is_left_to_hands_who_may_go_there(monkeypatch):
    from hglab import crew

    personas = load_personas(ROOT)
    nibs, neverland = personas["nibs"], load_team(ROOT, "neverland")
    monkeypatch.setattr(factory, "next_design_active", lambda team: True)
    monkeypatch.setattr(crew, "_blueprint", lambda *a, **k: ([{"action": "move", "x": 71, "y": 85}], "carrying wood toward Nintendo Land", "blueprint"))
    here = (73, 109)
    view = WorldView(x0=here[0] - 6, y0=here[1] - 6, rows=GRASS, full_map=GRASS, tick=1000)
    observe = {"you": {"x": here[0], "y": here[1], "faction": {"id": 6, "name": "Neverland"}, "blocks_owned": 0}, "tick": 1000}
    step = plan_crew(nibs, neverland, PersonaState(mood="busy"), observe, view, {"wood": 10}, here, 90, nibs.energy_reserve, 3, {p.name for p in personas.values()}, {p.name: s for s, p in personas.items()}, None)
    assert step is None or not leaves_territory(nibs, neverland, step[0])


def test_the_factory_hands_build_before_they_gather():
    personas = load_personas(ROOT)
    team = load_team(ROOT, "chocolate-factory")
    assert team.extra["pipeline"]["focus"] == "blueprint"
    here = (79, 99)
    woodcutter = personas["loompa-woodcutter"]
    observe = {"you": {"x": here[0], "y": here[1], "faction": {"id": 5, "name": "Chocolate Factory"}}, "tick": 100}
    view = WorldView(x0=70, y0=90, rows=GRASS, full_map=GRASS, tick=100)
    step = plan_crew(woodcutter, team, PersonaState(mood="busy"), observe, view, {"wood": 5}, here, 80, woodcutter.energy_reserve, 3, {p.name for p in personas.values()}, {p.name: s for s, p in personas.items()}, None)
    assert step is not None and step[2] == "blueprint"  # five wood in the pack go into the works, not into a store first


def test_a_builder_who_never_leaves_its_ground_takes_only_the_steps_inside_it():
    personas = load_personas(ROOT)
    nibs, neverland = personas["nibs"], load_team(ROOT, "neverland")
    here = (73, 109)
    observe = {"you": {"x": here[0], "y": here[1], "faction": {"id": 6, "name": "Neverland"}, "blocks_owned": 0}, "tick": 1000}
    view = WorldView(x0=here[0] - 6, y0=here[1] - 6, rows=GRASS, full_map=GRASS, tick=1000)
    pack = {"stone": 30, "wood": 10, "berries": 5}
    nintendo = factory.plan_step(nibs, neverland, PersonaState(mood="busy"), observe, view, dict(pack), here, 3, hands=True, design_name="nintendo-land")
    assert nintendo is None  # every step of Nintendo Land lies outside the ring: no carry toward its edge
    office = load_team(ROOT, "exchange")
    assert factory.plan_step(nibs, office, PersonaState(mood="busy"), observe, view, dict(pack), here, 3, hands=True, design_name="nintendo-land") is None  # nor as a hand lent to the office
    lagalong = personas["tootles"]
    assert factory.plan_step(lagalong, neverland, PersonaState(mood="busy"), {**observe, "you": {**observe["you"]}}, view, dict(pack), here, 3, hands=True, design_name="nintendo-land") is not None  # a wanderer still goes
    signs = factory.plan_step(nibs, neverland, PersonaState(mood="busy"), observe, view, dict(pack), here, 3, hands=True, design_name="signposts")
    assert signs is not None and not leaves_territory(nibs, neverland, signs[0])  # the signposts inside the ring are his
