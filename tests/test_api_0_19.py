import json
from pathlib import Path

from hglab.wake import FIELDS_BY_ACTION, normalise_plan

ROOT = Path(__file__).resolve().parents[1]


def test_reject_claim_is_in_the_schema_and_keeps_its_goal_id():
    schema = json.loads((ROOT / "schemas/action.json").read_text(encoding="utf-8"))
    assert "reject_claim" in schema["properties"]["action"]["enum"]
    assert FIELDS_BY_ACTION["reject_claim"] == {"goal_id"}
    plan = normalise_plan({"summary": "s", "actions": [{"action": "reject_claim", "goal_id": 7}], "reasons": [], "approach": None})
    assert plan["actions"][0]["action"] == "reject_claim" and plan["actions"][0]["goal_id"] == 7
