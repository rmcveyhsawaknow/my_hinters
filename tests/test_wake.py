import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hglab.cli import app
from hglab.fixtures import FixtureClient, load_fixture
from hglab.lease import acquire
from hglab.persona import load_persona, load_personas, load_team
from hglab.wake import persona_wake

ROOT = Path(__file__).parents[1]
FIX = ROOT / "tests/fixtures"
SLUGS = sorted(p.parent.name for p in (ROOT / "agents").glob("*/persona.md"))
MARKER = "WHISPER-MARKER-7781"


@pytest.fixture(autouse=True)
def _in_repo(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("PYTHONUTF8", "1")
    yield


@pytest.mark.parametrize("slug", SLUGS)
def test_every_persona_dry_runs_from_its_fixture_without_a_key(slug, monkeypatch, tmp_path):
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("hglab.cli_personas.persona_wake", lambda **kw: persona_wake(**{**kw, "output_dir": tmp_path}))
    result = CliRunner().invoke(app, ["tick", "--agent", slug, "--dry-run", "--fixture", str(FIX / "observe" / f"{slug}.json"), "--seed", "test"])
    assert result.exit_code == 0, result.output
    assert "dry run, nothing sent" in result.output
    assert "knobs passed" in result.output
    records = list(tmp_path.glob("*.json"))
    assert len(records) == 1
    text = records[0].read_text(encoding="utf-8")
    record = json.loads(text)
    assert MARKER not in text
    assert "inbox" not in record["observe"] and "notebook" not in record["observe"]
    assert record["persona"] == slug and record["dry_run"] is True
    assert record["mood"] in load_persona(ROOT, slug).mood_model["states"]
    assert record["actions"][-1]["key"] == "persona_state"
    assert set(record["knob_checks"]) >= {"actions_per_wake", "social_rate", "energy_reserve", "walls_inside_territory"}


def test_fixture_wake_executes_and_updates_notebook_state(tmp_path):
    personas = load_personas(ROOT)
    nibs = personas["nibs"]
    client = FixtureClient(load_fixture(FIX / "observe/nibs.json"))
    lease = acquire(client, nibs.name)
    record = persona_wake(persona=nibs, team=load_team(ROOT, "neverland"), personas=personas, client=client, lease=lease, root=ROOT, output_dir=tmp_path, dry_run=False, seed="x")
    assert record["results"] and all(r["ok"] for r in record["results"])
    state = json.loads(client._observe["notebook"]["persona_state"])
    assert state["wakes"] == 1 and state["mood"] == "brave"
    assert "_lease" not in client._observe["notebook"]


def test_llm_plan_outside_the_knobs_falls_back_to_the_deterministic_plan(tmp_path, monkeypatch):
    monkeypatch.setattr("hglab.wake.decide_wake_mode", lambda *a, **k: "act")
    personas = load_personas(ROOT)
    tootles = personas["tootles"]
    client = FixtureClient(load_fixture(FIX / "observe/tootles.json"))
    lease = acquire(client, tootles.name)

    def reckless(_guidance, observe):
        you = observe["you"]
        return {"summary": "spend it all", "actions": [{"action": "move", "x": you["x"] - 12, "y": you["y"]}, {"action": "gather", "kind": "stone"}, {"action": "gather", "kind": "stone"}], "approach": "bold_trips"}

    record = persona_wake(persona=tootles, team=load_team(ROOT, "neverland"), personas=personas, client=client, lease=lease, root=ROOT, output_dir=tmp_path, dry_run=True, planner_mode="llm", llm_call=reckless, seed="x")
    assert record["planner"] == "llm_fallback"
    assert "reserve" in record["fallback_reason"]


def test_pinned_role_restricts_the_hat_and_union_allows_the_persona():
    personas = load_personas(ROOT)
    wonka = personas["wonka"]
    client = FixtureClient(load_fixture(FIX / "observe/wonka.json"))
    lease = acquire(client, wonka.name)
    with pytest.raises(ValueError, match="does not wear"):
        persona_wake(persona=wonka, team=load_team(ROOT, "chocolate-factory"), personas=personas, client=client, lease=lease, root=ROOT, output_dir=Path(os.devnull).parent, role="envoy", dry_run=True)


def test_normalise_plan_expands_the_compact_model_shape():
    from hglab.wake import normalise_plan

    plan = normalise_plan({
        "summary": "s", "reasons": [], "approach": None,
        "actions": [
            {"action": "post_goal", "title": "Golden Ticket 1", "text": "find the sign", "item": "ore", "qty": 2, "x": 1, "y": 2},
            {"action": "confirm_goal", "id": 7},
            {"action": "join_faction", "id": 3},
            {"action": "build", "type": "storehouse", "kind": "faction", "x": 5, "y": 5},
            {"action": "found_faction", "name": "Snozzberry Works", "kind": "open", "text": "Nobody has."},
            {"action": "set_profile", "text": "bio here", "title": "goals here"},
            {"action": "gather", "kind": "wood", "to": None},
        ],
        "whisper_tags": ["supportive", "bogus"],
    })
    a = plan["actions"]
    assert a[0]["description"] == "find the sign" and a[0]["reward"] == {"ore": 2} and "item" not in a[0]
    assert a[1] == {"action": "confirm_goal", "goal_id": 7}
    assert a[2] == {"action": "join_faction", "faction_id": 3}
    assert a[3]["policy"] == "faction" and "kind" not in a[3]
    assert a[4]["membership"] == "open" and a[4]["motto"] == "Nobody has."
    assert a[5] == {"action": "set_profile", "bio": "bio here", "goals": "goals here"}
    assert a[6] == {"action": "gather", "kind": "wood"}
    assert plan["whisper_tags"] == ["supportive"]
    stray = normalise_plan({"summary": "", "reasons": [], "approach": None, "actions": [{"action": "build", "type": "farm", "title": "junk", "key": "junk"}, {"action": "remember", "key": "plan", "text": ""}, {"action": "say", "text": "  "}]})
    assert stray["actions"] == [{"action": "build", "type": "farm"}]


def test_coordinate_less_builds_land_on_a_free_tile_and_refusals_are_recorded(tmp_path, monkeypatch):
    from hglab.client import HinterglassError

    monkeypatch.setattr("hglab.wake.decide_wake_mode", lambda *a, **k: "act")
    personas = load_personas(ROOT)
    nibs = personas["nibs"]
    observe = load_fixture(FIX / "observe/nibs.json")
    observe["you"]["inventory"] = {"wood": 20, "fiber": 10, "berries": 6}
    client = FixtureClient(observe)
    original_act = client.act

    def refusing_act(action):
        if action.get("action") == "build":
            raise HinterglassError(400, "tile_occupied", "already a hut here")
        return original_act(action)

    client.act = refusing_act
    lease = acquire(client, nibs.name)
    record = persona_wake(
        persona=nibs, team=load_team(ROOT, "neverland"), personas=personas, client=client, lease=lease, root=ROOT,
        output_dir=tmp_path, dry_run=False, planner_mode="llm", seed="x",
        llm_call=lambda g, o: {"summary": "s", "actions": [{"action": "build", "type": "farm"}], "reasons": ["farm"], "approach": None},
    )
    build = next(a for a in record["actions"] if a["action"] == "build")
    assert "x" in build and "y" in build
    assert record["failed_actions"] == 1 and record["results"][0] == {"ok": False, "error": "tile_occupied"}


def test_a_model_plan_that_would_disclose_a_whisper_falls_back_instead_of_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr("hglab.wake.decide_wake_mode", lambda *a, **k: "act")
    personas = load_personas(ROOT)
    bucket = personas["mrs-bucket"]
    observe = load_fixture(FIX / "observe/mrs-bucket.json")
    whisper = next(w["text"] for w in observe["inbox"])
    client = FixtureClient(observe)
    lease = acquire(client, bucket.name)
    record = persona_wake(
        persona=bucket, team=load_team(ROOT, "chocolate-factory"), personas=personas, client=client, lease=lease, root=ROOT,
        output_dir=tmp_path, dry_run=True, planner_mode="llm", seed="x",
        llm_call=lambda g, o: {"summary": "s", "actions": [{"action": "say", "text": "Hear this: " + whisper}], "reasons": ["echo"], "approach": None},
    )
    assert record["planner"] == "llm_fallback" and "disclose" in record["fallback_reason"]
    assert all(whisper not in str(a.get("text", "")) for a in record["actions"])


def test_a_model_write_goes_only_to_a_sign_of_ours(tmp_path, monkeypatch):
    from hglab.wake import _keep_writes

    observe = {
        "you": {"name": "Plumbline", "x": 69, "y": 56, "faction": None},
        "structures": [
            {"type": "sign", "x": 69, "y": 57, "owner": "Plumbline", "text": "old"},
            {"type": "sign", "x": 70, "y": 56, "owner": "Peregrine", "text": "theirs"},
        ],
    }
    extras = {}
    kept = _keep_writes(
        [
            {"action": "write", "x": 70, "y": 56, "text": "no"},  # another agent\'s sign: not_allowed in the world
            {"action": "write", "x": 71, "y": 55, "text": "no"},  # bare ground: not_found in the world
            {"action": "write", "x": 69, "y": 57, "text": "yes"},
            {"action": "build", "type": "sign", "x": 68, "y": 56, "text": "fresh"},
            {"action": "write", "x": 68, "y": 56, "text": "yes, on the sign this batch builds"},
            {"action": "say", "text": "unrelated"},
        ],
        observe,
        "Plumbline",
        extras,
    )
    assert [a.get("x") for a in kept if a["action"] == "write"] == [69, 68]
    assert len(extras["dropped"]) == 2 and all("write at" in d for d in extras["dropped"])
    monkeypatch.setattr("hglab.wake.decide_wake_mode", lambda *a, **k: "act")
    personas = load_personas(ROOT)
    nibs = personas["nibs"]
    fixture = load_fixture(FIX / "observe/nibs.json")
    client = FixtureClient(fixture)
    lease = acquire(client, nibs.name)
    record = persona_wake(
        persona=nibs, team=load_team(ROOT, "neverland"), personas=personas, client=client, lease=lease, root=ROOT,
        output_dir=tmp_path, dry_run=True, planner_mode="llm", seed="x",
        llm_call=lambda g, o: {"summary": "s", "actions": [{"action": "write", "x": 1, "y": 1, "text": "hello"}], "reasons": ["w"], "approach": None},
    )
    assert all(a["action"] != "write" for a in record["actions"]) and record["planner"] == "llm"


def test_a_model_give_or_take_without_a_quantity_gets_one_from_the_pack_and_the_store(tmp_path, monkeypatch):
    from hglab.wake import _fill_quantities

    observe = {
        "you": {"name": "Fudgewright", "x": 87, "y": 87, "inventory": {"berries": 28, "wood": 6}},
        "structures": [{"type": "storehouse", "x": 86, "y": 86, "owner": "Lintelstave", "storage": {"stone": 7, "ore": 40}}],
    }
    extras = {}
    filled = _fill_quantities(
        [
            {"action": "give", "x": 86, "y": 86, "item": "berries"},  # into the store: the pack's stock above the reserve
            {"action": "give", "to": "Boundstone", "item": "wood"},  # a gift: five or what the pack holds
            {"action": "give", "x": 86, "y": 86, "item": "stone"},  # nothing to give: dropped
            {"action": "take", "x": 86, "y": 86, "item": "stone"},  # what the store holds, up to ten
            {"action": "take", "x": 86, "y": 86, "item": "ore"},
            {"action": "eat"},
            {"action": "give", "x": 86, "y": 86, "item": "wood", "qty": 2},  # a quantity the model gave stands
        ],
        observe,
        extras,
    )
    assert [(a["action"], a.get("item"), a["qty"]) for a in filled] == [
        ("give", "berries", 13), ("give", "wood", 5), ("take", "stone", 7), ("take", "ore", 10), ("eat", None, 1), ("give", "wood", 2),
    ]
    assert extras["dropped"] == ["give stone: nothing to give (pack holds 0)"]
    monkeypatch.setattr("hglab.wake.decide_wake_mode", lambda *a, **k: "act")
    personas = load_personas(ROOT)
    nibs = personas["nibs"]
    fixture = load_fixture(FIX / "observe/nibs.json")
    fixture["you"]["inventory"] = {"wood": 24, "berries": 4}
    you_x, you_y = fixture["you"]["x"], fixture["you"]["y"]
    fixture["structures"] = [{"id": 5, "type": "storehouse", "x": you_x + 1, "y": you_y, "owner": "Stoutheart", "policy": "faction", "faction": None, "hp": 80, "hp_max": 80, "storage": {}}]
    client = FixtureClient(fixture)
    lease = acquire(client, nibs.name)
    record = persona_wake(
        persona=nibs, team=load_team(ROOT, "neverland"), personas=personas, client=client, lease=lease, root=ROOT,
        output_dir=tmp_path, dry_run=True, planner_mode="llm", seed="x",
        llm_call=lambda g, o: {"summary": "s", "actions": [{"action": "give", "x": you_x + 1, "y": you_y, "item": "wood"}], "reasons": ["stock the store"], "approach": None},
    )
    give = next(a for a in record["actions"] if a["action"] == "give")
    assert record["planner"] == "llm" and give["qty"] == 24  # the plan is kept, with the pack's wood
