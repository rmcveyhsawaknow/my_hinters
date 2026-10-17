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
SLUGS = ["wonka", "mrs-bucket", "grandpa-joe", "tinker-bell", "lost-boy", "tootles", "nibs"]
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
    stray = normalise_plan({"summary": "", "reasons": [], "approach": None, "actions": [{"action": "build", "type": "farm", "title": "junk", "key": "junk"}]})
    assert stray["actions"][0] == {"action": "build", "type": "farm"}
