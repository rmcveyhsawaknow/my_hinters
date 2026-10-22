import json

from hglab.notes import fit_note


def test_a_note_that_outgrows_the_limit_is_trimmed_and_still_parses():
    state = {"invited": [f"Resident{i:03d}" for i in range(400)], "asked": [f"tick{i}" for i in range(50)], "last_call_tick": 46000}
    text = fit_note(state)
    assert len(text) <= 2000
    back = json.loads(text)
    assert back["last_call_tick"] == 46000 and back["invited"][-1] == "Resident399" and len(back["invited"]) < 400  # the newest stay
    assert json.loads(fit_note({"a": 1})) == {"a": 1}
    huge = {"surveys": {f"r{i}": {"lot": "A01-NW", "price": 45, "reasons": ["x" * 100]} for i in range(60)}}
    back = json.loads(fit_note(huge))
    assert len(back.get("surveys", {})) < 60 and "r59" in back["surveys"]  # the oldest surveys go first
