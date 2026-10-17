import random
from pathlib import Path
from types import SimpleNamespace

from hglab.persona import load_persona, load_team
from hglab.talk import compose_line, summarise_shift, templated_line

ROOT = Path(__file__).parents[1]


def _records():
    return [
        {"approach": "build", "wake_mode": "act", "mood": "in_bed", "actions": [{"action": "build", "type": "hut", "x": 65, "y": 71}, {"action": "gather", "kind": "wood"}]},
        {"approach": "gather_trip", "wake_mode": "act", "mood": "in_bed", "actions": [{"action": "move", "x": 66, "y": 70}, {"action": "gather", "kind": "fiber"}, {"action": "give", "x": 66, "y": 71, "item": "stone", "qty": 12}]},
        {"approach": "rest", "wake_mode": "rest", "mood": "in_bed", "actions": []},
    ]


def test_summary_counts_what_the_shift_did():
    summary = summarise_shift(_records())
    assert summary["wakes"] == 3 and summary["rests"] == 1 and summary["moved"] == 1
    assert summary["built"] == ["hut at (65,71)"] and summary["gathered"] == {"wood": 5, "fiber": 5}
    assert summary["deposited"] == {"stone": 12}


def test_templated_line_is_in_character_and_within_limits():
    joe = load_persona(ROOT, "grandpa-joe")
    line = templated_line(joe, summarise_shift(_records()), random.Random(1))
    assert "hut at (65,71)" in line and len(line) <= joe.voice["max_say_chars"]


def test_compose_line_falls_back_to_the_template_when_the_model_misbehaves():
    joe = load_persona(ROOT, "grandpa-joe")
    team = load_team(ROOT, "chocolate-factory")
    summary = summarise_shift(_records())

    bad = SimpleNamespace(value={"line": "see http://example.com for my memoirs"})
    line, source = compose_line(joe, team, summary, ROOT, caller=lambda prompt, schema: bad)
    assert source == "template" and "http" not in line

    good = SimpleNamespace(value={"line": "Up at the crack of noon; the hut built itself while I supervised the ceiling."}, input_tokens=900, output_tokens=30, model="claude-haiku-5-5", provider="anthropic")
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    line, source = compose_line(joe, team, summary, ROOT, usage=usage, caller=lambda prompt, schema: good)
    assert source == "model" and line.startswith("Up at the crack") and usage["calls"] == 1 and usage["route"] == "talk"


def test_compose_prompt_treats_character_notes_and_summary_as_data():
    joe = load_persona(ROOT, "grandpa-joe")
    seen = {}

    def caller(prompt, schema):
        seen["prompt"] = prompt
        return SimpleNamespace(value={"line": "fine"})

    compose_line(joe, None, summarise_shift(_records()), ROOT, caller=caller)
    assert "<DATA>" in seen["prompt"] and "PG-13" in seen["prompt"] and "Never name" in seen["prompt"]
