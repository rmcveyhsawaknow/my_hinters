import random
from pathlib import Path

import pytest

from hglab.mood import PersonaState
from hglab.patrol import ahead, distance_to, nearest_index, oriented, perimeter_loop
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView, _plan_patrol, plan_wake

ROOT = Path(__file__).resolve().parents[1]
OURS = {"Fudgewright", "MotherPail", "GrandadPail", "Tinkerglow", "Strayling", "Lagalong", "Stoutheart", "Clarion", "LandBroker"}


def _island(x0=20, y0=20, x1=100, y1=90, lake=True):
    rows = []
    for y in range(128):
        row = []
        for x in range(128):
            inside = x0 <= x <= x1 and y0 <= y <= y1
            if lake and 50 <= x <= 60 and 50 <= y <= 60:
                inside = False  # a lake inside the island is not the edge of the world
            row.append("g" if inside else "W")
        rows.append("".join(row))
    rows[10] = rows[10][:5] + "ggg" + rows[10][8:]  # an islet off the coast is not the main landmass
    return rows


def test_the_loop_is_the_outer_coast_traced_clockwise_and_closed():
    rows = _island()
    loop = perimeter_loop(tuple(rows))
    assert len(loop) == 2 * (81 + 71) - 4  # the rectangle's edge, every tile once
    assert loop[0] == (20, 20) and loop[1] == (21, 20)  # east along the top: clockwise on screen
    assert all(max(abs(a[0] - b[0]), abs(a[1] - b[1])) == 1 for a, b in zip(loop, loop[1:] + loop[:1]))  # closed, 8-adjacent
    assert all(rows[y][x] == "g" for x, y in loop)
    assert not any(50 <= x <= 60 and 50 <= y <= 60 for x, y in loop) and (6, 10) not in loop  # no lake shore, no islet
    assert oriented(loop, "counterclockwise")[0] == loop[-1] and oriented(loop, "counterclockwise")[1] == loop[-2]
    assert nearest_index(loop, (60, 10)) == loop.index((60, 20)) and distance_to(loop, (60, 25)) == 5
    assert ahead(loop, (20, 20), None, (12,)) == [(32, 20)]


def _lagalong():
    persona = load_personas(ROOT)["tootles"]
    assert persona.knobs["patrol"] == {"route": "perimeter", "direction": "clockwise", "hops": 2}
    return persona


def test_the_patrol_walks_ahead_two_hops_and_counts_the_laps():
    persona = _lagalong()
    rows = _island(lake=False)
    view = WorldView(x0=0, y0=0, rows=rows, full_map=rows)
    state = PersonaState(mood="wistful")
    step = _plan_patrol(persona, state, (20, 20), view)
    assert step is not None and step[2] == "patrol" and [a["action"] for a in step[0]] == ["move", "move"]
    assert step[0][0] == {"action": "move", "x": 32, "y": 20} and step[0][1] == {"action": "move", "x": 44, "y": 20}
    assert state.flags["patrol"]["i"] == 24 and state.flags["patrol"]["walked"] == 24 and "lap 1, 24 of 300" in step[1]
    loop = perimeter_loop(tuple(rows))
    state.flags["patrol"].update(i=len(loop) - 5, walked=len(loop) - 5)  # five tiles short of a full lap
    step = _plan_patrol(persona, state, loop[len(loop) - 5], view, room=1)
    assert step is not None and len(step[0]) == 1 and state.flags["patrol"]["walked"] >= len(loop) and "lap 2" in step[1]
    fresh = PersonaState(mood="wistful")
    first = _plan_patrol(persona, fresh, loop[-2], view, room=1)  # starting just before the loop's origin is not a lap
    assert first is not None and "lap 1" in first[1]
    inland = _plan_patrol(persona, PersonaState(mood="wistful"), (60, 55), view, room=1)
    assert inland is not None and "toward the coast" in inland[1]  # far inland: route out to the edge first


@pytest.mark.parametrize("work", [True, False])
def test_lagalong_keeps_to_the_edge_in_shifts_and_wakes(work):
    personas = load_personas(ROOT)
    persona = personas["tootles"]
    team = load_team(ROOT, persona.team)
    rows = _island(lake=False)
    observe = {
        "tick": 30000, "you": {"name": "Lagalong", "x": 40, "y": 20, "energy": 100, "inventory": {"wood": 5, "berries": 10}},
        "view": {"x0": 34, "y0": 14, "rows": [r[34:47] for r in rows[14:27]]}, "agents": [], "events": [], "structures": [],
        "resources": [{"x": 41, "y": 21, "kind": "wood", "amount": 30}], "goals_nearby": [], "your_goals": {}, "since_last_observe": {},
        "world": {"nearest_agents": []}, "notebook": {},
    }
    names = {personas[m].name.casefold(): m for m in team.members if m in personas}
    plan = plan_wake(persona, team, PersonaState(mood="wistful"), observe, "act", random.Random("p"), teammates=None, terrain_rows=rows, allowed=None, team_names=names, work=work, collective_names=OURS)
    moves = [a for a in plan["actions"] if a["action"] == "move"]
    assert moves and all(a["y"] == 20 and a["x"] > 40 for a in moves), plan  # east along the north coast, never inland
    assert plan["approach"] in {"patrol", "gather_near"}


def test_the_models_inland_moves_are_refused():
    from hglab.wake import _keep_to_edge

    rows = _island(lake=False)
    loop = perimeter_loop(tuple(rows))
    observe = {"you": {"x": 40, "y": 20}}
    _keep_to_edge("Lagalong", [{"action": "move", "x": 52, "y": 21}], observe, loop)
    with pytest.raises(ValueError, match="outermost edge"):
        _keep_to_edge("Lagalong", [{"action": "move", "x": 45, "y": 30}], observe, loop)
    _keep_to_edge("Lagalong", [{"action": "move", "x": 50, "y": 45}], {"you": {"x": 55, "y": 55}}, loop)  # inland and heading out: allowed
