"""Found in the first hour of the brief of 2026-11-02: a full pack with no store to unload into, and an office at its cap of stores."""

from pathlib import Path

from hglab import factory
from hglab.crew import plan_crew
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView

ROOT = Path(__file__).parents[1]
ROWS = ["g" * 128] * 128


def test_a_full_pack_with_no_store_at_the_works_raises_the_blueprint_with_what_it_carries(monkeypatch):
    """Strayling stood at 49/50 of wood, fiber and berries by Neverland's works with no store and no stone for one, and explored for an hour."""
    personas = load_personas(ROOT)
    strayling, team = personas["lost-boy"], load_team(ROOT, "neverland")
    calls = []

    def fake_plan_step(persona, team_, state, observe, view, inventory, position, room, **kw):
        calls.append(kw)
        return ([{"action": "place", "bx": 292, "by": 416, "bz": 0, "material": "wood"}], "the hideaway: a trunk", "blueprint") if kw.get("pack_only") == "wood" else None

    monkeypatch.setattr(factory, "plan_step", fake_plan_step)
    view = WorldView(x0=60, y0=95, rows=ROWS, full_map=ROWS, resources=[{"x": 70, "y": 96, "kind": "stone", "amount": 24}], tick=1000)
    observe = {"you": {"x": 73, "y": 104, "faction": {"id": 9, "name": "Neverland"}}, "tick": 1000}
    names = {p.name: s for s, p in personas.items()}
    step = plan_crew(strayling, team, PersonaState(mood="busy"), observe, view, {"wood": 15, "fiber": 16, "stone": 3, "berries": 15}, (73, 104), 80, strayling.energy_reserve, 3, {p.name for p in personas.values()}, names, None)
    assert step is not None and step[2] == "blueprint"
    assert calls and calls[0]["hands"] and [c["pack_only"] for c in calls][:2] == ["fiber", "wood"]  # the pack's loads, heaviest first, until a step takes one (gather=False stays inside _blueprint)
    light = plan_crew(strayling, team, PersonaState(mood="busy"), observe, view, {"wood": 5, "berries": 15}, (73, 104), 80, strayling.energy_reserve, 3, {p.name for p in personas.values()}, names, None)
    assert light is None or light[2] != "blueprint" or "trunk" not in light[1]  # a light pack gathers for the first store instead


def test_the_office_counts_no_relic_inside_the_campus_toward_its_cap_of_stores():
    personas = load_personas(ROOT)
    steward, team = personas["office-steward"], load_team(ROOT, "exchange")
    assert team.extra["pipeline"]["claims"]["stores_max"] == 24
    full = {"ore": 20, "wood": 64, "fiber": 114, "stone": 236, "berries": 66}

    def store(x, y):
        return {"id": x * 1000 + y, "type": "storehouse", "x": x, "y": y, "owner": "Lintelstave", "policy": "faction", "faction": "Land Office", "storage": dict(full)}

    relics = [store(91, 83), store(91, 86), store(86, 86)]  # inside the factory's campus: on lots the office excludes
    outside = [store(81, 76), store(92, 78), store(90, 77)]
    everything = [*relics, *outside, *(store(70 + i, 60) for i in range(16))]  # 22 stores, 19 of them the office's own ground
    team.extra["pipeline"]["claims"]["stores_max"] = 20
    view = WorldView(x0=60, y0=55, rows=ROWS, full_map=ROWS, structures=everything, world_structures=everything, tick=1000)
    observe = {"you": {"x": 82, "y": 76, "faction": {"id": 7, "name": "Land Office"}}, "tick": 1000}
    names = {p.name: s for s, p in personas.items()}
    step = plan_crew(steward, team, PersonaState(mood="busy"), observe, view, {"wood": 45, "berries": 5}, (82, 76), 80, steward.energy_reserve, 3, {p.name for p in personas.values()}, names, None)
    assert step is not None and step[0][0]["action"] == "build" and step[0][0]["type"] == "storehouse" and "(19 of 20 standing)" in step[1]  # the relics do not count
