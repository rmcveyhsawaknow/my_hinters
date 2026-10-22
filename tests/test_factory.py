import random
from pathlib import Path

from hglab.blocks import factory_plan, footprint, house_plan, next_step, tile_cells
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView, _house_site, _plan_engage, _plan_hearth, _plan_house

ROOT = Path(__file__).resolve().parents[1]
OURS = {"Fudgewright", "MotherPail", "GrandadPail", "Tinkerglow", "Strayling", "Lagalong", "Stoutheart", "Clarion", "LandBroker"}
ROWS = ["g" * 128] * 128


def test_the_factory_plan_is_metal_and_glass_over_coloured_stone_with_support_at_every_step():
    plan = factory_plan(89, 98, "purple")
    names = [s["name"] for s in plan]
    assert names[:2] == ["door", "elevator pillar"] and names[-1] == "ridge" and names.index("lower walls") < names.index("west windows") < names.index("upper walls")
    totals = {}
    for s in plan:
        totals[s["item"]] = totals.get(s["item"], 0) + s["items"]
    assert totals == {"ore": 17, "stone": 50, "wood": 8, "fiber": 30}, totals  # about three trips of ore, a storehouse's worth of stone
    assert plan[0]["action"]["material"] == "metal" and plan[0]["action"]["shape"] == "door" and plan[0]["cells"] == 8
    assert plan[1]["action"]["bz2"] == 9 and plan[1]["cells"] == 10  # the glass elevator
    assert all(s["action"]["shape"] == "window" for s in plan if "windows" in s["name"]) and sum(s["cells"] for s in plan if "windows" in s["name"]) == 32
    assert plan[-1]["action"]["material"] == "metal" and plan[-1]["action"]["shape"] == "slab" and plan[-1]["action"]["bz"] == 6
    assert all(s["action"].get("color") == "pink" for s in plan if s["name"].startswith("roof")) and all(s["action"].get("color") == "purple" for s in plan if "walls" in s["name"])
    cumulative = [s["cumulative"] for s in plan]
    assert cumulative == sorted(cumulative) and cumulative[-1] == sum(s["cells"] for s in plan)
    x0, y0, x1, y1 = footprint(89, 98, 3)
    bx0, by0, _, _ = tile_cells(x0, y0)
    _, _, bx1, by1 = tile_cells(x1, y1)
    for s in plan:  # every box within the footprint
        a = s["action"]
        assert bx0 <= a["bx"] <= bx1 and bx0 <= a.get("bx2", a["bx"]) <= bx1 and by0 <= a["by"] <= by1 and by0 <= a.get("by2", a["by"]) <= by1
    assert house_plan(89, 98, 3, "purple", style="factory") == plan
    assert next_step(plan, plan[5]["cumulative"])["name"] == "west windows"


def test_the_house_follows_the_chosen_site_and_the_hearth_is_raised_there_first():
    wonka = load_personas(ROOT)["wonka"]
    knob = wonka.knobs["house"]
    state = PersonaState(mood="mercurial")
    assert knob["style"] == "factory" and _house_site(knob, {"x": 65, "y": 71}, state) is None  # the ground is bought from the land office, never the old hearth
    state.flags["house_site"] = {"x": 89, "y": 98, "lot": "R19-NE", "price": 18, "paid": 18}
    assert _house_site(knob, {"x": 65, "y": 71}, state) == (89, 98)
    assert _house_site({"size": 1}, {"x": 65, "y": 71}) == (65, 71) and _house_site({"size": 1}, None) is None
    view = WorldView(x0=82, y0=92, rows=ROWS, full_map=ROWS, world_structures=[{"type": "hut", "x": 65, "y": 71, "owner": "Fudgewright"}])
    far = _plan_hearth(wonka, {"wood": 12, "fiber": 6}, (86, 92), view, {"x": 65, "y": 71}, state)
    assert far is not None and far[2] == "hearth_trip" and far[0][0]["action"] == "move"
    near = _plan_hearth(wonka, {"wood": 12, "fiber": 6}, (89, 97), view, {"x": 65, "y": 71}, state)
    assert near is not None and near[0] == [{"action": "build", "type": "hut", "x": 89, "y": 98}] and near[2] == "hearth"
    assert _plan_hearth(wonka, {"wood": 3}, (89, 97), view, {"x": 65, "y": 71}, state) is None  # no wood for the hearth yet
    settled = WorldView(x0=82, y0=92, rows=ROWS, full_map=ROWS, world_structures=[{"type": "hut", "x": 89, "y": 98, "owner": "Fudgewright"}])
    assert _plan_hearth(wonka, {"wood": 12, "fiber": 6}, (89, 97), settled, {"x": 89, "y": 98}, state) is None
    observe = {"you": {"x": 89, "y": 97, "blocks_owned": 0}, "blocks": [], "tick": 46000}
    step = _plan_house(wonka, {"ore": 4, "stone": 2}, (89, 97), settled, {"x": 89, "y": 98}, observe, state=state)
    assert step is not None and step[0][0]["material"] == "metal" and step[0][0]["shape"] == "door"  # the factory starts with its gold door
    assert _plan_house(wonka, {"stone": 20}, (89, 97), settled, {"x": 89, "y": 98}, observe, state=state) is None  # the door wants ore first


def test_a_newcomer_is_welcomed_once_in_the_factory_s_words():
    personas = load_personas(ROOT)
    wonka = personas["wonka"]
    team = load_team(ROOT, wonka.team)
    names = {personas[m].name.casefold(): m for m in team.members if m in personas}
    observe = {"tick": 46000, "you": {"name": "Fudgewright", "x": 86, "y": 92, "inventory": {"wood": 12}}, "agents": [], "events": [], "structures": [], "goals_nearby": [], "your_goals": {}, "since_last_observe": {}, "world": {"nearest_agents": []}, "notebook": {}}
    view = WorldView(x0=80, y0=86, rows=ROWS, liveness={"JoshuaTreeStagehand": 45900, "Quill": 100}, arrivals={"JoshuaTreeStagehand": 42053, "Quill": 175})
    state = PersonaState(mood="mercurial")
    step = _plan_engage(wonka, team, state, {"wood": 12}, (86, 92), view, observe, None, names, random.Random("w"), OURS)
    assert step is not None and step[2] == "welcome" and step[0][0]["to"] == "JoshuaTreeStagehand"
    text = step[0][0]["text"]
    assert "JoshuaTreeStagehand" in text and "(89,98)" in text and "(86,92)" in text and len(text) <= 500
    again = _plan_engage(wonka, team, state, {"wood": 12}, (86, 92), view, observe, None, names, random.Random("w"), OURS)
    assert again is None or again[2] != "welcome"  # once
    from hglab.engage import board, render_board

    b = board(wonka, observe, OURS, set(), newcomers=["JoshuaTreeStagehand", "MotherPail"])
    assert b["newcomers"] == ["JoshuaTreeStagehand"] and "newcomers through the glass" in render_board(b)
