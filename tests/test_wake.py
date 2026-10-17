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
