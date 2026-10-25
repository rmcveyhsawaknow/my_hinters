"""Builders shed berries before fetching, farms stop feeding a berry glut, and GrandadPail holds court from the hut."""

import json
import random
import re
from pathlib import Path

from hglab import factory, quips
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView, _berry_glut, _plan_harvest, _plan_lounge

ROOT = Path(__file__).parents[1]
GRASS = ["g" * 128] * 128


def test_a_builder_clears_its_berries_before_it_fetches_materials(tmp_path, monkeypatch):
    monkeypatch.setattr(factory, "ledger_path", lambda root, name: tmp_path / f"{name}.json")
    personas = load_personas(ROOT)
    mason = personas["loompa-mason"]
    team = load_team(ROOT, "chocolate-factory")
    _design, steps, _ = factory.blueprint(ROOT, "chocolate-factory")
    factory.mark_done(ROOT, "chocolate-factory", [s["id"] for s in steps if s["section"] == "depots" or s["id"] == "elevator:00"], 1, "test")
    store = {"type": "storehouse", "x": 84, "y": 89, "owner": "Treacleaxe", "policy": "faction", "faction": "Chocolate Factory", "storage": {"stone": 200, "wood": 100}}  # beside the builder, too far from the elevator to pay for it there
    view = WorldView(x0=79, y0=82, rows=GRASS, full_map=GRASS, structures=[store], world_structures=[store], tick=70000)
    observe = {"tick": 70000, "you": {"name": mason.name, "x": 84, "y": 88, "energy": 100, "faction": {"id": 5, "name": "Chocolate Factory"}, "blocks_owned": 0}}
    clogged = {"berries": 29, "wood": 15, "fiber": 5}
    step = factory.plan_step(mason, team, PersonaState(mood="busy"), observe, view, dict(clogged), (84, 88), 3, mates={"Treacleaxe"})
    assert step is not None and step[0][0] == {"action": "give", "x": 84, "y": 89, "item": "berries", "qty": 24}  # five kept, the rest put away
    take = next(a for a in step[0] if a["action"] == "take")
    assert take["qty"] >= 20 and "clutter" in step[1]  # the fetch now carries a real load, not one to five items
    full = {**store, "storage": {"stone": 300, "wood": 200}}
    tired = {**observe, "you": {**observe["you"], "energy": 60}}
    jammed = factory.plan_step(mason, team, PersonaState(mood="busy"), tired, WorldView(x0=79, y0=82, rows=GRASS, full_map=GRASS, structures=[full], world_structures=[full], tick=70000), dict(clogged), (84, 88), 3, mates={"Treacleaxe"})
    assert jammed is not None and jammed[0][0]["action"] == "eat" and jammed[0][0]["qty"] == 2  # no room in the store: eat what energy allows


def test_farms_are_left_full_when_the_stores_already_hold_a_berry_glut():
    personas = load_personas(ROOT)
    bucket = personas["mrs-bucket"]
    team = load_team(ROOT, "chocolate-factory")
    farm = {"type": "farm", "x": 61, "y": 60, "owner": bucket.name, "storage": {"berries": 30}}
    glut_store = {"type": "storehouse", "x": 59, "y": 60, "owner": bucket.name, "storage": {"berries": 357}}
    view = WorldView(x0=54, y0=54, rows=GRASS, structures=[farm, glut_store])
    assert _berry_glut(team, view) is True
    assert _plan_harvest(bucket, team, {"wood": 5, "berries": 15}, (60, 60), view, None) is None  # a full farm stops growing, which is the point
    topped = _plan_harvest(bucket, team, {"wood": 5, "berries": 4}, (60, 60), view, None)
    assert topped is not None and topped[0][-1]["qty"] == 11  # only up to the keep of fifteen
    lean = WorldView(x0=54, y0=54, rows=GRASS, structures=[farm, {**glut_store, "storage": {"berries": 20}}])
    assert _berry_glut(team, lean) is False and _plan_harvest(bucket, team, {"wood": 5, "berries": 15}, (60, 60), lean, None)[0][-1]["qty"] == 15


def test_the_bedside_material_is_original_fresh_and_never_aimed_at_a_peer():
    lines = [line for group in quips.BANK.values() for line in group]
    assert len(lines) >= 40 and len(set(lines)) == len(lines)
    for line in lines:
        filled = line.format(day=186, tick=67000, gathered=40, kind="stone", done=12, total=129, blocks=480, season="autumn", weather="rain", to_winter="one day")
        assert len(filled) <= 240, line
        assert not quips.banned(filled), line
        assert not re.search(r"\b(Clarion|LandBroker|Plumbline|Stoutheart|Tinkerglow|Strayling|Lagalong|Nodkin)\b", filled), line  # residents beyond his family are never the joke
    memory: dict = {}
    known = quips.facts({"tick": 67000, "events": [{"type": "gather", "actor": "Treacleaxe", "tick": 66900, "data": {"kind": "stone"}} for _ in range(8)]}, team_names={"Treacleaxe"}, season="autumn", weather="rain", progress={"done": 12, "total": 129, "blocks": 480})
    assert known["gathered"] == 40 and known["kind"] == "stone" and known["to_winter"] == "one day"
    rng = random.Random("grandad")
    said = []
    for _ in range(30):
        text, _key, riff, memory = quips.compose(memory, known, rng)
        said.append((text, riff))
    texts = [s[0] for s in said]
    assert len(set(texts)) == 30 and not any(s[1] for s in said)  # thirty fresh lines before anything repeats
    assert any("40 stone" in t for t in texts) and any("129" in t for t in texts)  # real numbers from the crew and the ledger
    for _ in range(40):
        last = quips.compose(memory, known, rng)
        memory = last[3]
    assert last[2] is True  # the bank is spent: the local model is asked for a fresh line
    assert len(json.dumps(memory, separators=(",", ":"))) < 1200  # its own notebook key, well inside the 2000-character limit
    later = {**known, "tick": known["tick"] + 8700}
    assert quips.compose(memory, later, rng)[2] is False  # a real day on, the bank is fresh again


def test_a_fresh_line_from_the_local_model_keeps_the_numbers_or_the_bank_line_stands():
    grandad = load_personas(ROOT)["grandpa-joe"]
    seed = "The crew hauled 40 stone this hour. I visualized every unit. Manifesting is labor too."

    class Result:
        def __init__(self, line):
            self.value = {"line": line}
            self.input_tokens, self.output_tokens, self.model, self.provider = 600, 40, "qwen3.5:9b", "ollama"

    plan = {"actions": [{"action": "say", "text": seed}], "approach": "lounge", "riff": True}
    extras = {}
    out = quips.riff(plan, grandad, ROOT, {}, extras, caller=lambda p, s: Result("40 stone hauled while I held a strategy nap. Synergy, but horizontal."))
    assert out["actions"][0]["text"].startswith("40 stone hauled") and extras["quip_line"] == "model"
    plan2 = {"actions": [{"action": "say", "text": seed}], "approach": "lounge", "riff": True}
    out2 = quips.riff(plan2, grandad, ROOT, {}, extras := {}, caller=lambda p, s: Result("The crew hauled some stone."))
    assert out2["actions"][0]["text"] == seed and extras["quip_line"] == "bank"  # the number was lost: the bank's line stands


def test_grandad_rests_beside_the_hut_and_holds_court_from_it():
    personas = load_personas(ROOT)
    grandad = personas["grandpa-joe"]
    team = load_team(ROOT, "chocolate-factory")
    assert grandad.knobs["rest_probability"] >= 0.8 and grandad.social_rate == 3 and team.social_budget["says_per_hour"] >= 12
    names = {p.name.casefold(): slug for slug, p in personas.items() if slug in team.members}
    observe = {"tick": 67000, "you": {"name": grandad.name, "x": 79, "y": 105, "energy": 100}, "events": [], "notebook": {}}
    view = WorldView(x0=73, y0=89, rows=GRASS, full_map=GRASS, tick=67000)
    far = _plan_lounge(grandad, team, PersonaState(mood="in_bed"), observe, view, (79, 105), 100, 40, names, None, random.Random("g"))
    assert far is not None and far[0][0]["action"] == "move" and "back to bed" in far[1]
    assert max(abs(far[0][0]["x"] - 79), abs(far[0][0]["y"] - 105)) <= 12
    home = {**observe, "you": {**observe["you"], "x": 88, "y": 96}}
    court = _plan_lounge(grandad, team, PersonaState(mood="in_bed"), home, view, (88, 96), 100, 40, names, None, random.Random("g"))
    assert court is not None and [a["action"] for a in court[0]] == ["say"] and len(court[0][0]["text"]) <= 240
    assert court[3]["key"] == "quips" and court[3]["text"].startswith("{")  # the line is remembered in its own notebook key
    quiet = {**home, "notebook": {"_limits": {"says": [{"tick": 66990, "text": "a"}, {"tick": 66995, "text": "b"}, {"tick": 66998, "text": "c"}]}}}
    assert _plan_lounge(grandad, team, PersonaState(mood="in_bed"), quiet, view, (88, 96), 100, 40, names, None, random.Random("g")) is None  # three this hour: rest in silence
    assert _plan_lounge(personas["mrs-bucket"], team, PersonaState(mood="warm"), home, view, (88, 96), 100, 40, names, None, random.Random("g")) is None  # only a persona with a lounge


def test_the_walk_back_a_line_and_its_memory_fit_his_two_actions():
    """Live on 2026-10-25 every lounge wake that walked and spoke was refused (three actions against his two) and the shift skipped it silently."""
    from hglab.fixtures import load_fixture
    from hglab.persona import enforce_knobs

    grandad = load_personas(ROOT)["grandpa-joe"]
    team = load_team(ROOT, "chocolate-factory")
    observe = load_fixture(ROOT / "tests/fixtures/observe/grandpa-joe.json")
    observe["you"].update({"x": 82, "y": 109})
    wake = [
        {"action": "move", "x": 86, "y": 100},
        {"action": "say", "text": "Some people have a standing desk. I have a lying desk."},
        {"action": "remember", "key": "quips", "text": "{}"},
        {"action": "remember", "key": "persona_state", "text": "{}"},
    ]
    assert grandad.actions_per_wake == 2
    enforce_knobs(wake, grandad, team, observe, recent_say_count=0)  # the memory note is bookkeeping, like the persona state
