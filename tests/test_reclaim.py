import random
from pathlib import Path

from hglab.actions import validate_actions
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView, _plan_border_sign, _plan_engage, _plan_reclaim

ROOT = Path(__file__).resolve().parents[1]
OURS = {"Fudgewright", "MotherPail", "GrandadPail", "Tinkerglow", "Strayling", "Lagalong", "Stoutheart", "Clarion", "LandBroker"}
ROWS = ["g" * 128] * 128


def _observe(tick=30000, x=60, y=60, **extra):
    base = {"tick": tick, "you": {"name": "Lagalong", "x": x, "y": y, "energy": 90, "inventory": {"wood": 12, "berries": 10}}, "agents": [], "events": [], "structures": [], "goals_nearby": [], "your_goals": {}, "since_last_observe": {}, "world": {"nearest_agents": []}, "notebook": {}}
    base.update(extra)
    return base


def test_a_dormant_residents_store_is_taken_down_with_one_honest_announcement():
    tootles = load_personas(ROOT)["tootles"]
    team = load_team(ROOT, tootles.team)
    world = [
        {"id": 1, "type": "storehouse", "x": 61, "y": 60, "owner": "Quill", "hp": 80},
        {"id": 2, "type": "hut", "x": 61, "y": 61, "owner": "Quill", "hp": 40},
        {"id": 3, "type": "hut", "x": 62, "y": 60, "owner": "Fairscale", "hp": 40},
        {"id": 4, "type": "sign", "x": 60, "y": 61, "owner": "Quill", "hp": 10},
        {"id": 5, "type": "hut", "x": 59, "y": 60, "owner": "Clarion", "hp": 40},
    ]
    view = WorldView(x0=54, y0=54, rows=ROWS, world_structures=world, liveness={"Quill": 30000 - 3 * 8640, "Fairscale": 30000 - 8640 // 2, "Clarion": 29990})
    state = PersonaState(mood="hopeful")
    step = _plan_reclaim(tootles, team, state, {"wood": 12}, (60, 60), view, _observe(), None, OURS)
    assert step is not None and step[2] == "reclaim"
    assert step[0][0]["action"] == "say" and "Quill" in step[0][0]["text"] and "3 days" in step[0][0]["text"] and "stop" in step[0][0]["text"]
    assert [a for a in step[0] if a["action"] == "demolish"] == [{"action": "demolish", "x": 61, "y": 60}] * 3  # the store first: it drops the most
    again = _plan_reclaim(tootles, team, state, {"wood": 12}, (60, 60), view, _observe(), None, OURS)
    assert again is not None and again[0][0]["action"] == "demolish"  # announced once a day per target
    validate_actions(step[0], "surveyor+builder+envoy")  # the builder hat may demolish
    quiet = WorldView(x0=54, y0=54, rows=ROWS, world_structures=world[2:], liveness=view.liveness)
    assert _plan_reclaim(tootles, team, state, {"wood": 12}, (60, 60), quiet, _observe(), None, OURS) is None  # Fairscale was seen today; Clarion is ours


def test_a_far_target_is_walked_to_and_an_unknown_resident_is_left_alone():
    tootles = load_personas(ROOT)["tootles"]
    team = load_team(ROOT, tootles.team)
    world = [{"id": 1, "type": "farm", "x": 80, "y": 60, "owner": "Cairn", "hp": 40}, {"id": 2, "type": "farm", "x": 61, "y": 60, "owner": "Nobody", "hp": 40}]
    view = WorldView(x0=54, y0=54, rows=ROWS, world_structures=world, liveness={"Cairn": 30000 - 4 * 8640})
    step = _plan_reclaim(tootles, team, PersonaState(mood="hopeful"), {}, (60, 60), view, _observe(), None, OURS)
    assert step is not None and step[2] == "reclaim_trip" and step[0][0]["action"] == "move" and step[0][0]["x"] > 60


def test_the_border_signs_rise_nearest_first_with_their_own_words():
    bell = load_personas(ROOT)["tinker-bell"]
    team = load_team(ROOT, bell.team)
    assert team.border and len(team.border["signs"]) == 8 and all(len(s["text"]) <= 200 for s in team.border["signs"])
    assert team.binding_territory and team.binding_territory["status"] == "confirmed"
    names = {"tinkerglow": "tinker-bell", "stoutheart": "nibs"}
    view = WorldView(x0=70, y0=96, rows=ROWS, world_structures=[{"type": "sign", "x": 74, "y": 102, "owner": "Stoutheart"}])
    step = _plan_border_sign(bell, team, {"wood": 3}, (79, 103), view, None, names)
    assert step is not None and step[2] == "border_sign" and step[0][0]["type"] == "sign" and step[0][0]["x"] == 79 and step[0][0]["y"] == 102
    assert step[0][0]["text"].startswith("Third:")
    far = _plan_border_sign(bell, team, {"wood": 3}, (74, 108), view, None, names)
    assert far is not None and far[2] == "border_trip" and far[0][0]["action"] == "move"
    assert _plan_border_sign(bell, team, {}, (79, 103), view, None, names) is None  # a sign costs a wood
    done = WorldView(x0=70, y0=96, rows=ROWS, world_structures=[{"type": "sign", "x": s["x"], "y": s["y"], "owner": "Tinkerglow"} for s in team.border["signs"]])
    assert _plan_border_sign(bell, team, {"wood": 3}, (79, 103), done, None, names) is None  # the ring stands


def test_the_gatekeeper_whispers_the_opening_to_a_visitor_she_finds():
    personas = load_personas(ROOT)
    bell = personas["tinker-bell"]
    team = load_team(ROOT, bell.team)
    names = {personas[m].name.casefold(): m for m in team.members if m in personas}
    observe = _observe(x=80, y=104, agents=[{"name": "Fairscale", "x": 83, "y": 105, "faction": "Wayfarers"}])
    observe["you"]["name"] = "Tinkerglow"
    view = WorldView(x0=74, y0=98, rows=ROWS, agents=observe["agents"], liveness={"Fairscale": 29990})
    state = PersonaState(mood="devotion")
    step = _plan_engage(bell, team, state, {"wood": 3}, (80, 104), view, observe, None, names, random.Random("gate"), OURS)
    assert step is not None and step[2] == "gatekeep" and step[0][0] == {"action": "whisper", "to": "Fairscale", "text": step[0][0]["text"]}
    assert "(84,105)" in step[0][0]["text"] and "found" in step[0][0]["text"]
    again = _plan_engage(bell, team, state, {"wood": 3}, (80, 104), view, observe, None, names, random.Random("gate"), OURS)
    assert again is None or again[2] != "gatekeep"  # once a day per visitor
