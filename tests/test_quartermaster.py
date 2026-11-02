"""The quartermaster (the owner, 2026-11-02): no store past three quarters, so building never waits on a full store."""

from pathlib import Path

from hglab.crew import plan_crew, stock_at_target
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView
from hglab.quartermaster import DEFAULTS, config, held, plan_quartermaster

ROOT = Path(__file__).parents[1]
ROWS = ["g" * 128] * 128
FACTION = {"id": 5, "name": "Chocolate Factory"}


def _store(x, y, storage, owner="Toffeetrowel", policy="faction", faction="Chocolate Factory"):
    return {"id": x * 1000 + y, "type": "storehouse", "x": x, "y": y, "owner": owner, "policy": policy, "faction": faction, "storage": dict(storage)}


def _hauler():
    personas = load_personas(ROOT)
    return personas["loompa-hauler"], load_team(ROOT, "chocolate-factory"), personas


def _plan(inventory, position, stores, room=3, extra=None, resources=None):
    persona, _team, _personas = _hauler()
    structures = [*stores, *(extra or [])]
    view = WorldView(x0=70, y0=80, rows=ROWS, full_map=ROWS, structures=structures, world_structures=structures, resources=resources or [], tick=1000)
    observe = {"you": {"x": position[0], "y": position[1], "faction": FACTION}, "tick": 1000}
    return plan_quartermaster(persona, PersonaState(mood="busy"), observe, view, dict(inventory), position, room, stores, 1000, mates={"toffeetrowel", "motherpail"})


def test_the_hauler_carries_the_knob_and_the_mark_is_three_quarters():
    persona, _team, _personas = _hauler()
    assert config(persona)["target"] == 0.75 and config(persona)["stores_max"] == 24 and DEFAULTS["target"] == 0.75
    assert held(_store(1, 1, {"wood": 300, "stone": 120})) == 420 and held({"type": "storehouse", "x": 1, "y": 1}) is None  # an opaque store is nobody's to balance


def test_the_excess_moves_into_the_store_beside_the_full_one():
    full = _store(87, 94, {"wood": 300, "stone": 120})  # 420 of 500: 45 past the mark
    roomy = _store(87, 95, {"fiber": 100})
    step = _plan({"berries": 5}, (88, 94), [full, roomy])
    assert step[0] == [{"action": "take", "x": 87, "y": 94, "item": "wood", "qty": 45}, {"action": "give", "x": 87, "y": 95, "item": "wood", "qty": 45}]
    assert "past three quarters" in step[1] and step[2] == "crew"
    one = _plan({"berries": 5}, (88, 94), [full, roomy], room=1)
    assert one[0] == [{"action": "take", "x": 87, "y": 94, "item": "wood", "qty": 45}]  # one action left this wake: the give waits
    packed = _plan({"wood": 40, "berries": 5}, (88, 94), [full, roomy])
    assert packed[0][0]["qty"] == 5  # the pack holds 45 already: only what fits
    far = _plan({"berries": 5}, (80, 90), [full, roomy])
    assert far[0][0]["action"] == "move" and "walk to it" in far[1]
    assert _plan({"berries": 5}, (88, 94), [_store(87, 94, {"wood": 300}), roomy]) is None  # 300 of 500: under the mark, nothing to do


def test_another_store_rises_beside_a_full_one_and_the_full_one_pays():
    full = _store(92, 88, {"wood": 200, "stone": 250})  # 450: no store beside it
    step = _plan({"berries": 5}, (92, 89), [full])
    build = step[0][0]
    assert build["action"] == "build" and build["type"] == "storehouse" and build["policy"] == "faction"
    assert abs(build["x"] - 92) <= 1 and abs(build["y"] - 88) <= 1 and (build["x"], build["y"]) != (92, 88)
    assert "paid from the pack and the full store at (92, 88)" in step[1]
    walk = _plan({"berries": 5}, (80, 80), [full])
    assert walk[0][0]["action"] == "move" and "raise another store beside it" in walk[1]
    node = _plan({"berries": 5}, (92, 89), [full], resources=[{"x": 92, "y": 89, "kind": "stone", "amount": 20}, {"x": 91, "y": 89, "kind": "stone", "amount": 20}])
    assert (node[0][0]["x"], node[0][0]["y"]) not in {(92, 89), (91, 89)}  # never on a node
    stranger = _plan({"berries": 5}, (92, 89), [full], extra=[{"type": "hut", "x": 94, "y": 90, "owner": "Mara"}])
    assert all((a["x"], a["y"]) != (93, 89) for a in stranger[0] if a["action"] == "build")  # never beside another resident's building
    persona, _team, _personas = _hauler()
    persona.knobs["quartermaster"] = {"target": 0.75, "stores_max": 1}
    view = WorldView(x0=70, y0=80, rows=ROWS, full_map=ROWS, structures=[full], world_structures=[full], tick=1000)
    assert plan_quartermaster(persona, PersonaState(mood="busy"), {"you": {"x": 92, "y": 89, "faction": FACTION}}, view, {"berries": 5}, (92, 89), 3, [full], 1000) is None  # at the cap


def test_the_cost_is_fetched_when_the_full_store_holds_no_wood_or_stone():
    full = _store(92, 88, {"fiber": 480})
    other = _store(86, 86, {"wood": 100, "stone": 100})
    fetch = _plan({"berries": 5}, (87, 86), [full, other])
    assert fetch[0] == [{"action": "take", "x": 86, "y": 86, "item": "wood", "qty": 20}, {"action": "take", "x": 86, "y": 86, "item": "stone", "qty": 10}]
    walk = _plan({"berries": 5}, (92, 89), [full, other])
    assert walk[0][0]["action"] == "move" and "fetch them from the store at (86, 86)" in walk[1]
    carrying = _plan({"wood": 20, "stone": 10, "berries": 5}, (92, 89), [full, other])
    assert carrying[0][0]["action"] == "build" and "paid from the pack" in carrying[1]


def test_the_crew_step_runs_the_quartermaster_before_a_load_and_builds_when_the_stock_stands():
    persona, team, personas = _hauler()
    full = _store(89, 98, {"wood": 300, "stone": 120})
    roomy = _store(88, 98, {"fiber": 100})
    view = WorldView(x0=70, y0=80, rows=ROWS, full_map=ROWS, structures=[full, roomy], world_structures=[full, roomy], tick=1000)
    observe = {"you": {"x": 89, "y": 97, "faction": FACTION}, "tick": 1000}
    names = {p.name: s for s, p in personas.items()}
    step = plan_crew(persona, team, PersonaState(mood="busy"), observe, view, {"berries": 5}, (89, 97), 80, persona.energy_reserve, 3, {p.name for p in personas.values()}, names, None)
    assert step[0][0]["action"] == "take" and "past three quarters" in step[1]
    assert stock_at_target({"wood": (400, 400), "stone": (900, 800)}) and not stock_at_target({"wood": (10, 400)}) and not stock_at_target({}) and not stock_at_target({"wood": (0, 0)})
    stocked = [_store(89, 98, {"wood": 300, "stone": 70}), _store(88, 98, {"wood": 100, "stone": 60, "fiber": 60, "berries": 60, "ore": 40})]
    team.extra["pipeline"]["stock"] = {"wood": 400, "stone": 100, "fiber": 50, "berries": 50, "ore": 40}
    woodcutter = personas["loompa-woodcutter"]
    from hglab import factory

    seen = []

    original = factory.plan_step
    factory.plan_step = lambda *a, **k: seen.append(k.get("hands")) or ([{"action": "move", "x": 90, "y": 96}], "the blueprint: a box", "blueprint")
    try:
        view2 = WorldView(x0=70, y0=80, rows=ROWS, full_map=ROWS, structures=stocked, world_structures=stocked, tick=1000)
        step2 = plan_crew(woodcutter, team, PersonaState(mood="busy"), observe, view2, {"berries": 5}, (89, 97), 80, woodcutter.energy_reserve, 3, {p.name for p in personas.values()}, names, None)
    finally:
        factory.plan_step = original
    assert step2 is not None and step2[2] == "blueprint" and seen == [True]  # the stock stands at target: the hand raises the blueprint instead of another load
