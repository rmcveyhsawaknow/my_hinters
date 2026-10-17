import json
import random
from pathlib import Path

from hglab.fixtures import load_fixture
from hglab.mood import (
    HEADINGS,
    PERSONA_STATE_KEY,
    PersonaState,
    apply_inputs,
    decide_wake_mode,
    dump_state,
    load_state,
    next_heading,
    step_mood,
)
from hglab.persona import load_persona, load_team

ROOT = Path(__file__).parents[1]
FIX = ROOT / "tests/fixtures"


def test_state_round_trips_through_the_notebook_and_survives_garbage():
    wonka = load_persona(ROOT, "wonka")
    state = load_state(wonka, {PERSONA_STATE_KEY: "not json"})
    assert state.mood == "gentle"
    state.mood = "manic"
    state.visited = [f"{i},{i}" for i in range(500)]
    text = dump_state(state)
    assert len(text) <= 2000
    again = load_state(wonka, {PERSONA_STATE_KEY: text})
    assert again.mood == "manic"
    assert load_state(wonka, {PERSONA_STATE_KEY: json.dumps({"mood": "nonsense"})}).mood == "gentle"


def test_mercurial_wonka_follows_inspiration_and_suspicion():
    wonka = load_persona(ROOT, "wonka")
    team = load_team(ROOT, "chocolate-factory")
    observe = load_fixture(FIX / "observe/wonka.json")
    state = PersonaState(mood="gentle")
    apply_inputs(state, {"suspicion": {"value": 80, "tick": observe["tick"]}}, observe["tick"])
    assert step_mood(wonka, state, observe, team, random.Random(1)).mood == "deadpan"
    state = PersonaState(mood="gentle")
    apply_inputs(state, {"inspiration": {"value": 90, "tick": observe["tick"]}}, observe["tick"])
    assert step_mood(wonka, state, observe, team, random.Random(1)).mood == "manic"
    # inputs decay with age: a day-old suspicion of 80 is worth 40 and no longer forces deadpan
    state = PersonaState(mood="gentle")
    apply_inputs(state, {"suspicion": {"value": 80, "tick": observe["tick"] - 8640}}, observe["tick"])
    assert state.input_value("suspicion", observe["tick"]) == 40.0


def test_tinker_bell_holds_exactly_one_emotion_by_precedence():
    tink = load_persona(ROOT, "tinker-bell")
    team = load_team(ROOT, "neverland")
    observe = load_fixture(FIX / "observe/tinker-bell.json")
    observe["agents"] = []
    rng = random.Random(3)
    state = PersonaState(mood="devotion")
    assert step_mood(tink, state, observe, team, rng).mood == "devotion"
    apply_inputs(state, {"escape": {"value": 70, "tick": observe["tick"]}}, observe["tick"])
    assert step_mood(tink, state, observe, team, rng).mood == "jealousy"
    observe["events"].append({"id": 1, "tick": observe["tick"], "type": "demolish", "actor": "Marlow", "x": 72, "y": 114, "text": "Marlow damaged Tinkerglow's bridge at (72, 114).", "data": {}})
    assert step_mood(tink, state, observe, team, rng).mood == "fury"  # fury outranks jealousy
    observe["events"].pop()
    state.inputs.clear()
    apply_inputs(state, {"glow": {"value": 20, "tick": observe["tick"]}}, observe["tick"])
    assert step_mood(tink, state, observe, team, rng).mood == "sulk"
    assert state.glow == 20
    state.inputs.clear()
    apply_inputs(state, {"belief": {"value": 80, "tick": observe["tick"]}}, observe["tick"])
    assert step_mood(tink, state, observe, team, rng).mood == "joy"
    for mood in (state.mood,):
        assert mood in tink.mood_model["states"]


def test_grandpa_joe_bursts_only_when_glory_is_near():
    joe = load_persona(ROOT, "grandpa-joe")
    team = load_team(ROOT, "chocolate-factory")
    observe = load_fixture(FIX / "observe/grandpa-joe.json")
    observe["events"] = [e for e in observe["events"] if e["type"] not in {"goal_confirmed", "faction_founded"}]
    state = PersonaState(mood="in_bed")
    assert step_mood(joe, state, observe, team, random.Random(1)).mood == "in_bed"
    rests = sum(decide_wake_mode(joe, state, observe, random.Random(seed)) == "rest" for seed in range(400))
    assert 0.5 < rests / 400 < 0.7
    observe["events"].append({"id": 2, "tick": observe["tick"], "type": "goal_confirmed", "actor": "Fudgewright", "x": 89, "y": 99, "text": "Fudgewright confirmed a goal.", "data": {"goal_id": 1, "claimant": "Peregrine"}})
    # a peer's glory does not rouse him; the team's does (actors are in-world names, not slugs)
    assert step_mood(joe, state, observe, team, random.Random(1), member_names={"Peregrine"}).mood == "in_bed"
    assert step_mood(joe, state, observe, team, random.Random(1), member_names={"Fudgewright", "MotherPail"}).mood == "glory"
    assert decide_wake_mode(joe, state, observe, random.Random(1)) == "burst"


def test_lost_boy_distraction_rate_sits_in_its_band():
    boy = load_persona(ROOT, "lost-boy")
    observe = load_fixture(FIX / "observe/lost-boy.json")
    state = PersonaState(mood="curious")
    hits = sum(decide_wake_mode(boy, state, observe, random.Random(seed)) == "distracted" for seed in range(1000))
    assert 0.33 < hits / 1000 < 0.47


def test_second_star_heading_rotates_two_steps_right():
    assert next_heading("N", random.Random(0)) == "E"
    assert next_heading("NW", random.Random(0)) == "NE"
    assert next_heading(None, random.Random(0)) in HEADINGS
