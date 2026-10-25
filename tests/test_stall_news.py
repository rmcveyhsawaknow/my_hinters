"""Fudgewright's walks no longer cancel each other; Clarion's news is fresh, announced once, and never retold with invented numbers."""

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from hglab import factory
from hglab.fixtures import load_fixture
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import _plan_news, plan_wake

ROOT = Path(__file__).parents[1]
FIX = ROOT / "tests/fixtures"


def test_the_land_payment_walk_is_not_undone_by_a_blueprint_walk_the_other_way(tmp_path, monkeypatch):
    """Live on 2026-10-25 Fudgewright walked toward the office's depot and back toward the mill depot in every wake for five hours."""
    monkeypatch.setattr(factory, "ledger_path", lambda root, name: tmp_path / f"{name}.json")
    personas = load_personas(ROOT)
    wonka = personas["wonka"]
    team = load_team(ROOT, "chocolate-factory")
    observe = load_fixture(FIX / "observe/wonka.json")
    observe["you"].update({"x": 92, "y": 89, "energy": 100, "inventory": {"ore": 1, "wood": 20, "fiber": 1, "stone": 7, "berries": 5}})
    observe["view"] = {"x0": 84, "y0": 82, "rows": ["g" * 13] * 13}
    observe["structures"], observe["resources"], observe["agents"], observe["events"] = [], [], [], []
    observe["_factions"], observe["_guidance"] = [], {}
    state = PersonaState(mood="mercurial")
    state.flags["house_site"] = {"id": "works", "x": 87, "y": 97, "lot": "I09-SE", "price": 76, "currency": "wood", "paid": 33, "tick": 1}
    state.flags["site_asked"], state.flags["site_asked_for"] = int(observe["tick"]), "works"
    depot = {"type": "storehouse", "x": 86, "y": 86, "owner": "Lintelstave", "faction": "Land Office", "policy": "faction"}
    mill = {"type": "storehouse", "x": 92, "y": 88, "owner": "Toffeetrowel", "faction": "Chocolate Factory", "policy": "faction"}
    names = {personas[m].name.casefold(): m for m in team.members if m in personas}
    plan = plan_wake(
        wonka, team, state, observe, "act", random.Random("walk"), teammates=None, terrain_rows=None, allowed=None, team_names=names,
        work=True, registrar_name="LandBroker", public_structures=[depot, mill], collective_names={p.name for p in personas.values()},
        cast={"office_names": {"Lintelstave"}, "crew_roles": {}},
    )
    moves = [a for a in plan["actions"] if a["action"] == "move"]
    assert len(moves) == 1, json.dumps(plan["actions"])  # one walk, toward the office's store: the next wake pays
    assert moves[0]["x"] < 92 and "land office" in " ".join(plan["reasons"])


def test_the_news_queue_holds_only_fresh_news_the_crier_announces(tmp_path):
    from hglab.features import NEWS_KINDS, announceable, news_path, pending_news

    now = datetime.now(UTC)
    rows = [
        {"key": "a", "kind": "newcomers", "text": "1 new resident stepped through the glass.", "tick": 58659, "utc": (now - timedelta(days=1, hours=14)).isoformat(), "announced": False},
        {"key": "b", "kind": "newcomers", "text": "2 new residents stepped through the glass.", "tick": 71000, "utc": (now - timedelta(minutes=30)).isoformat(), "announced": False},
        {"key": "c", "kind": "api_version", "text": "The game updated: API 0.33.1 became 0.34.0.", "tick": 71000, "utc": (now - timedelta(hours=3)).isoformat(), "announced": False},
        {"key": "d", "kind": "new_event_type", "text": "A new kind of event appeared in the public log: write.", "tick": 60000, "utc": (now - timedelta(days=2)).isoformat(), "announced": False},
        {"key": "e", "kind": "something_else", "text": "Not for the crier.", "tick": 71000, "utc": now.isoformat(), "announced": False},
    ]
    path = news_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert [r["key"] for r in pending_news(tmp_path)] == ["b", "c"]  # the day-and-a-half-old newcomer and the two-day-old event type are no longer news
    assert "newcomers" in NEWS_KINDS and announceable("newcomers") and announceable("new_event_type") and not announceable("something_else")


def test_the_crier_announces_a_newcomer_once_in_its_own_words():
    personas = load_personas(ROOT)
    crier = personas["town-crier"]
    env = {"discoveries": ["2 new residents stepped through the glass."], "discovery_kinds": ["newcomers"]}
    observe = {"tick": 71900, "you": {"name": "Clarion"}, "notebook": {}, "events": []}
    state = PersonaState(mood="bright")
    step = _plan_news(crier, state, observe, env)
    assert step is not None and step[0][0]["text"] == "News from the glass! 2 new residents stepped through the glass."
    assert _plan_news(crier, state, observe, env) is None  # once


def test_a_shift_line_never_retells_the_news_or_invents_a_number():
    from hglab.talk import compose_line, summarise_shift

    clarion = load_personas(ROOT)["town-crier"]
    records = [{"approach": "gather_trip", "actions": [{"action": "gather", "kind": "wood"}, {"action": "move", "x": 71, "y": 86}], "mood": "bright", "discoveries": ["1 new resident stepped through the glass."]}]
    summary = summarise_shift(records)
    assert "discoveries" not in summary  # the news step owns the news
    made_up = SimpleNamespace(value={"line": "Hear this! Tick 6041 saw five fresh wood-piles at [71, 86]!"}, input_tokens=1, output_tokens=1, model="qwen3.5:9b", provider="ollama")
    line, source = compose_line(clarion, None, summary, ROOT, caller=lambda p, s: made_up)
    assert source == "template" and "6041" not in line  # 6041 is in no data: the template stands
    redacted = SimpleNamespace(value={"line": "Hear this! At tick [REDACTED] near 71, 86 I gathered wood."}, input_tokens=1, output_tokens=1, model="qwen3.5:9b", provider="ollama")
    assert compose_line(clarion, None, summary, ROOT, caller=lambda p, s: redacted)[1] == "template"
    honest = SimpleNamespace(value={"line": "Hear this! Five wood gathered by the road at 71, 86, and the square is still standing."}, input_tokens=1, output_tokens=1, model="qwen3.5:9b", provider="ollama")
    assert compose_line(clarion, None, summary, ROOT, caller=lambda p, s: honest)[1] == "model"  # 71 and 86 are the shift's own numbers
