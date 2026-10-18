from pathlib import Path

from hglab.data import load_events
from hglab.environment import CATEGORY_LABELS, categorise, compact_for_state, digest, render

ROOT = Path(__file__).parents[1]
FIX = ROOT / "tests/fixtures"


def test_categories_follow_the_site_filters():
    assert categorise({"type": "build"}) == "building"
    assert categorise({"type": "farm_produced"}) == "building"
    assert categorise({"type": "goal_posted"}) == "trade_goals"
    assert categorise({"type": "give"}) == "trade_goals"
    assert categorise({"type": "say"}) == "talk"
    assert categorise({"type": "faction_founded"}) == "factions"
    assert categorise({"type": "move"}) == "movement"
    assert set(CATEGORY_LABELS) == {"all", "building", "trade_goals", "talk", "factions", "movement"}


def test_digest_counts_pace_actors_and_headlines_from_fixture_events():
    events = load_events([FIX / "world/events.jsonl"])
    now = max(e["tick"] for e in events)
    collective = {"Fudgewright", "MotherPail", "GrandadPail", "Tinkerglow", "Strayling", "Lagalong", "Stoutheart"}
    d = digest(events, now, self_name="Fudgewright", team_names={"Fudgewright", "MotherPail", "GrandadPail"}, collective_names=collective)
    assert d["day"]["all"] >= d["hour"]["all"] >= 0
    assert set(d["peers_active"]).isdisjoint(collective)
    assert set(d["collective_active"]) <= {"Tinkerglow", "Strayling", "Lagalong", "Stoutheart"}
    assert all(t["actor"] not in collective for t in d["peer_talk"])
    assert d["pace"] in {"quiet", "steady", "quickening", "slowing"}
    assert "MotherPail" in d["team_active"] or "GrandadPail" in d["team_active"] or "Fudgewright" in d["team_active"]
    assert all(a not in {"Fudgewright", "MotherPail", "GrandadPail"} for a in d["peers_active"])
    text = render(d)
    assert "Building" in text and "Trade & Goals" in text and "Talk" in text and "Factions" in text
    assert "pace" in text
    before = compact_for_state(d)
    again = digest(events, now, self_name="Fudgewright", team_names=set(), previous=before)
    assert again["change_since_last_wake"] == 0.0


def test_digest_is_quiet_with_no_events():
    d = digest([], 1000, self_name="X", team_names=set())
    assert d["pace"] == "quiet" and d["day"]["all"] == 0 and render(d).startswith("tick 1000")


def test_a_rejected_claim_shows_under_trade_and_goals():
    from hglab.environment import categorise

    assert categorise({"type": "goal_rejected"}) == "trade_goals"


def test_a_self_confirmed_goal_shows_under_trade_and_goals():
    from hglab.environment import categorise

    assert categorise({"type": "goal_done"}) == "trade_goals"


def test_repairs_and_ruins_are_building_events_and_the_digest_knows_the_weather():
    from hglab.environment import categorise, digest, render

    assert categorise({"type": "repair"}) == "building" and categorise({"type": "ruin"}) == "building"
    events = [
        {"tick": 10800, "type": "weather_changed", "actor": None, "text": "Day 31 begins: winter, clear.", "data": {"day": 31, "season": "winter", "weather": "clear"}},
        {"tick": 10440, "type": "weather_changed", "actor": None, "text": "Day 30 begins: autumn, storm.", "data": {"day": 30, "season": "autumn", "weather": "storm"}},
        {"tick": 10810, "type": "repair", "actor": "Stoutheart", "text": "Stoutheart repaired a road."},
    ]
    d = digest(events, 10820, self_name="Clarion", team_names=set())
    assert d["weather"] == {"tick": 10800, "day": 31, "season": "winter", "weather": "clear"}
    assert "weather: day 31, winter, clear" in render(d)
    assert digest([], 10, self_name="Clarion", team_names=set())["weather"] is None
