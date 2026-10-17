import json
from pathlib import Path

from typer.testing import CliRunner

from hglab.cli import app
from hglab.fixtures import FixtureClient, load_fixture
from hglab.lease import acquire
from hglab.persona import load_personas, load_team
from hglab.pulse import scheduled_wakes
from hglab.wake import persona_wake
from hglab.workflows import caller_text

ROOT = Path(__file__).parents[1]
FIX = ROOT / "tests/fixtures"


def _wake(slug: str, observe: dict, tmp_path: Path, **overrides):
    personas = load_personas(ROOT)
    persona = personas[slug]
    client = FixtureClient(observe)
    lease = acquire(client, persona.name)
    return persona_wake(persona=persona, team=load_team(ROOT, persona.team), personas=personas, client=client, lease=lease, root=ROOT, output_dir=tmp_path, dry_run=True, work=True, seed="shift", **overrides), client


def test_work_wake_builds_first_when_materials_are_in_hand(tmp_path):
    observe = load_fixture(FIX / "observe/nibs.json")
    observe["you"]["inventory"] = {"wood": 20, "stone": 10, "fiber": 6, "berries": 4}
    observe["you"]["home"] = None
    record, _ = _wake("nibs", observe, tmp_path)
    assert record["work"] is True and record["planner"] == "heuristic"
    assert record["actions"][0]["action"] == "build" and record["actions"][0]["type"] == "hut"
    assert "inbox" not in json.dumps(record) and record["observe"].keys() == {"tick", "you"}


def test_work_wake_deposits_surplus_and_can_raise_a_monument(tmp_path):
    observe = load_fixture(FIX / "observe/wonka.json")
    you = observe["you"]
    you["inventory"] = {"stone": 30, "ore": 10, "wood": 6}
    observe["structures"] = [{"id": 1, "type": "storehouse", "x": you["x"] + 1, "y": you["y"], "owner": "Fudgewright", "faction": None, "hp": 80, "text": None, "policy": "faction", "storage": {"stone": 25}}]
    record, _ = _wake("wonka", observe, tmp_path)
    kinds = [a["action"] for a in record["actions"]]
    assert record["approach"] == "build_monument"
    assert record["actions"][0]["type"] == "monument"
    assert "remember" in kinds


def test_work_wake_migrates_toward_the_team_site_when_far(tmp_path):
    observe = load_fixture(FIX / "observe/mrs-bucket.json")
    observe["you"].update({"x": 62, "y": 56})
    observe["you"]["inventory"] = {"berries": 5}
    observe["resources"] = []
    observe["structures"] = []
    observe["view"]["x0"], observe["view"]["y0"] = 56, 50
    record, _ = _wake("mrs-bucket", observe, tmp_path)
    moves = [a for a in record["actions"] if a["action"] == "move"]
    assert record["approach"] in {"migrate", "explore"}
    if record["approach"] == "migrate":
        assert moves and (moves[0]["x"] > 62 or moves[0]["y"] > 56)


def test_shift_command_runs_several_fixture_wakes_without_a_key(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr("hglab.cli_personas.persona_wake", lambda **kw: persona_wake(**{**kw, "output_dir": tmp_path}))
    result = CliRunner().invoke(app, ["shift", "--agent", "nibs", "--fixture", str(FIX / "observe/nibs.json"), "--max-wakes", "3", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "shift over: 3 wake(s)" in result.output
    assert len(list(tmp_path.glob("*.json"))) == 3


def test_callers_carry_the_work_cron_and_scheduled_wakes_count_shifts():
    personas = load_personas(ROOT)
    wonka = personas["wonka"]
    text = caller_text(wonka)
    assert wonka.knobs["work"]["cron"] in text and "'shift'" in text and "shift]" in text
    assert scheduled_wakes(wonka, [{"tick": 99000, "work": True}], 100000, 7 * 8640) > scheduled_wakes(wonka, [{"tick": 99000}], 100000, 7 * 8640)


def test_far_settlers_migrate_before_building(tmp_path):
    observe = load_fixture(FIX / "observe/mrs-bucket.json")
    observe["you"].update({"x": 62, "y": 56, "home": None})
    observe["you"]["inventory"] = {"wood": 20, "fiber": 10, "berries": 5}
    observe["structures"] = []
    observe["view"]["x0"], observe["view"]["y0"] = 56, 50
    record, _ = _wake("mrs-bucket", observe, tmp_path)
    assert record["approach"] == "migrate"
    assert record["actions"][0]["action"] == "move"
    assert all(a["action"] != "build" for a in record["actions"])


def test_roads_only_extend_existing_structures(tmp_path):
    observe = load_fixture(FIX / "observe/nibs.json")
    observe["you"]["inventory"] = {"stone": 6, "berries": 5}
    observe["structures"] = []
    record, _ = _wake("nibs", observe, tmp_path)
    assert all(not (a["action"] == "build" and a.get("type") == "road") for a in record["actions"])
