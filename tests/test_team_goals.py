import json
from pathlib import Path

from hglab.fixtures import FixtureClient, load_fixture
from hglab.lease import acquire
from hglab.persona import load_personas, load_team, load_teams
from hglab.wake import persona_wake

ROOT = Path(__file__).parents[1]
FIX = ROOT / "tests/fixtures"
INSIDE = {"id": 9, "name": "Chocolate Factory"}


def _wake(slug: str, observe: dict, tmp_path: Path, **overrides):
    personas = load_personas(ROOT)
    persona = personas[slug]
    observe["you"]["name"] = persona.name
    client = FixtureClient(observe)
    lease = acquire(client, persona.name)
    return persona_wake(
        persona=persona,
        team=load_team(ROOT, persona.team),
        personas=personas,
        client=client,
        lease=lease,
        root=ROOT,
        output_dir=tmp_path,
        dry_run=True,
        work=True,
        seed="team",
        **overrides,
    )


def _observe(**over):
    observe = load_fixture(FIX / "observe/nibs.json")
    observe["you"]["faction"] = None
    observe["you"]["energy"] = 100
    observe["you"]["inventory"] = {"wood": 30, "stone": 5, "berries": 3}
    observe["_factions"] = []
    observe["_guidance"] = {}
    observe.update(over)
    return observe


def test_team_files_carry_their_faction_and_founder():
    teams = load_teams(ROOT)
    neverland = teams["neverland"].extra["faction"]
    assert (
        neverland["name"] == "Neverland"
        and neverland["founder"] == "nibs"
        and neverland["exempt"] == ["tootles"]
    )
    assert teams["chocolate-factory"].extra["faction"]["founder"] == "wonka"
    assert "faction" not in teams["square"].extra


def test_the_founder_founds_the_team_faction_and_invites_within_the_cap(tmp_path):
    record = _wake("nibs", _observe(), tmp_path)
    kinds = [a["action"] for a in record["actions"] if a["action"] != "remember"]
    assert kinds[0] == "found_faction"
    assert (
        record["actions"][0]["name"] == "Neverland"
        and record["actions"][0]["membership"] == "invite"
    )
    invited = sorted(a["name"] for a in record["actions"] if a["action"] == "invite")
    # the cap is three actions: the founding and two invitations; the third mate is invited on a later day
    assert invited == [
        "Strayling",
        "Tinkerglow",
    ]  # Lagalong is exempt: he founded a theme faction for the collector programme
    assert record["approach"] == "team"
    dumped = json.dumps(record)
    assert "_factions" not in dumped and "_guidance" not in dumped


def test_a_member_joins_once_the_faction_exists_and_a_non_founder_waits(tmp_path):
    existing = [{"id": 7, "name": "Neverland", "members": 1, "membership": "invite"}]
    record = _wake("nibs", _observe(_factions=existing), tmp_path)
    assert record["actions"][0] == {"action": "join_faction", "faction_id": 7}
    waiting = _wake("lost-boy", _observe(), tmp_path)  # Strayling is not the founder
    assert not any(a["action"] in {"found_faction", "join_faction"} for a in waiting["actions"])
    unknown = _observe()
    del unknown["_factions"]  # the faction list is unknown: the founder does not found on a guess
    assert not any(
        a["action"] == "found_faction" for a in _wake("nibs", unknown, tmp_path)["actions"]
    )


def test_a_member_already_inside_tops_up_invitations_once_a_day(tmp_path):
    observe = _observe(
        _factions=[{"id": 7, "name": "Neverland", "members": 2, "membership": "invite"}]
    )
    observe["you"]["faction"] = {"id": 7, "name": "Neverland"}
    observe["agents"] = [
        {
            "name": "Tinkerglow",
            "distance": 1,
            "faction": {"id": 7, "name": "Neverland"},
            "x": 74,
            "y": 112,
        }
    ]
    record = _wake("nibs", observe, tmp_path)
    invited = sorted(a["name"] for a in record["actions"] if a["action"] == "invite")
    assert invited == ["Strayling"]  # Tinkerglow is seen inside already and Lagalong is exempt


def test_the_delivery_goal_is_posted_on_the_posters_own_storehouse_when_the_team_asks(tmp_path):
    suggestion = {
        "kind": "post_goal",
        "text": "logistics fail",
        "evidence": "migrate 60/201 failed",
    }
    observe = _observe(_guidance={"suggestions": [suggestion]})
    observe["you"]["faction"] = INSIDE  # the faction step stays quiet: already inside
    observe["your_goals"] = {"claimed": None, "posted": []}
    x, y = observe["you"]["x"] + 1, observe["you"]["y"]
    observe["structures"] = [
        {
            "id": 900,
            "type": "storehouse",
            "owner": "Fudgewright",
            "x": x,
            "y": y,
            "hp": 80,
            "policy": "private",
            "faction": None,
        }
    ]
    record = _wake("wonka", observe, tmp_path)
    goal = next(a for a in record["actions"] if a["action"] == "post_goal")
    assert goal["condition"] == {"type": "deliver", "x": x, "y": y, "item": "wood", "qty": 20}
    assert goal["reward"] == {"wood": 4} and goal["title"].startswith("Team delivery")
    assert record["observe"]["your_goals"] == {"claimed": None, "posted": []}
    again = _observe(_guidance={"suggestions": [suggestion]})
    again["you"]["faction"] = INSIDE
    again["your_goals"] = {
        "claimed": None,
        "posted": [
            {"id": 5, "title": "Team delivery: 20 wood to The Chocolate Factory", "status": "open"}
        ],
    }
    again["structures"] = observe["structures"]
    assert not any(a["action"] == "post_goal" for a in _wake("wonka", again, tmp_path)["actions"])


def test_the_assignment_steers_the_heuristic_planner_away_from_an_approach(tmp_path):
    base = _observe(
        _factions=[{"id": 7, "name": "Neverland", "members": 3, "membership": "invite"}]
    )
    base["you"]["faction"] = {
        "id": 7,
        "name": "Neverland",
    }  # inside a full faction: the team step is quiet
    base["you"]["inventory"] = {"wood": 20, "stone": 10, "fiber": 6, "berries": 4}
    base["you"]["home"] = None
    building = _wake("nibs", json.loads(json.dumps(base)), tmp_path)
    assert building["actions"][0]["action"] == "build"
    steered_observe = json.loads(json.dumps(base))
    steered_observe["_guidance"] = {
        "assignment": {"label": "stores", "works": ["gather_trip"], "avoid": ["build"]}
    }
    steered = _wake("nibs", steered_observe, tmp_path)
    assert steered["actions"][0]["action"] != "build" and steered["assignment"]["avoid"] == [
        "build"
    ]
    everything_observe = json.loads(json.dumps(base))
    every_label = [
        "build",
        "deposit",
        "deposit_trip",
        "gather_trip",
        "gather",
        "explore",
        "migrate",
        "harvest",
        "repair",
        "lighten",
        "team",
        "homing",
        "house",
        "market_watch",
        "stake",
        "patrol",
        "engage",
        "salvage",
        "news",
        "deliver",
        "build_monument",
        "border",
        "hearth",
        "forage",
        "gather_near",
        "reclaim",
        "site_trade",
        "team_goal",
        "credit_claim",
    ]
    everything_observe["_guidance"] = {
        "assignment": {"label": "x", "works": [], "avoid": every_label}
    }
    everything = _wake("nibs", everything_observe, tmp_path)
    assert [a for a in everything["actions"] if a["action"] != "remember"], (
        "the fallback still plans when every approach is avoided"
    )
