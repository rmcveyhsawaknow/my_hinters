import json
from pathlib import Path

from hglab.engage import _flags, _mark
from hglab.mood import STATE_TEXT_LIMIT, PersonaState, dump_state, load_state
from hglab.persona import load_personas

ROOT = Path(__file__).resolve().parents[1]


def test_a_busy_persona_keeps_its_plans_flags_within_the_notebook_limit():
    state = PersonaState(mood="warm")
    flags = _flags(state)
    for kind in ("replied", "gifted", "whispered", "welcomed", "contested", "retaliated"):
        for i in range(12):
            _mark(flags, kind, f"Resident{kind[:3]}{i:02d}", 46000 + i)
    state.flags["house_site"] = {"x": 87, "y": 87, "lot": "I08-SE", "price": 45, "currency": "wood", "paid": 20, "tick": 46182}
    state.flags["patrol"] = {"i": 120, "walked": 467, "n": 347, "dir": "clockwise"}
    state.flags["house"] = {"hut": [87, 87], "done": 36, "tick": 46300}
    state.flags["full_stores"] = {"65,54": 46000, "85,92": 46010}
    state.flags["world"] = {"day": {"all": 400, "build": 50}, "pace": "busy", "x": "y" * 900}
    state.visited = [f"{x},{y}" for x in range(40) for y in range(2)]
    text = dump_state(state)
    assert len(text) <= STATE_TEXT_LIMIT
    back = json.loads(text)
    assert back["flags"]["house_site"]["lot"] == "I08-SE" and back["flags"]["patrol"]["i"] == 120 and back["flags"]["house"]["done"] == 36
    assert back["flags"]["engaged"]["whispered"]  # the spacing tables survive, shrunk
    assert all(len(t) <= 6 for t in back["flags"]["engaged"].values())
    persona = load_personas(ROOT)["mrs-bucket"]
    restored = load_state(persona, {"persona_state": text})
    assert restored.flags["house_site"]["price"] == 45 and restored.wakes == state.wakes


def test_the_six_newest_names_stay_in_a_spacing_table():
    state = PersonaState(mood="warm")
    flags = _flags(state)
    for i in range(10):
        _mark(flags, "whispered", f"R{i}", 1000 + i)
    assert sorted(flags["whispered"]) == ["R4", "R5", "R6", "R7", "R8", "R9"]
