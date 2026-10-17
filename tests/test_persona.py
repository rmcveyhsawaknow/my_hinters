import copy
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from hglab.fixtures import load_fixture
from hglab.persona import (
    PERSONA_STATE_KEY,
    Team,
    enforce_knobs,
    in_region,
    in_territory,
    load_persona,
    load_personas,
    load_team,
    load_teams,
    team_say_count,
    validate_personas,
)

ROOT = Path(__file__).parents[1]
FIX = ROOT / "tests/fixtures"


def test_every_persona_metrics_and_team_validate():
    assert validate_personas(ROOT) == []
    personas = load_personas(ROOT)
    teams = load_teams(ROOT)
    assert set(personas) == {"wonka", "mrs-bucket", "grandpa-joe", "tinker-bell", "lost-boy", "tootles", "nibs"}
    assert set(teams) == {"chocolate-factory", "neverland"}
    for team in teams.values():
        assert sum(personas[m].social_rate for m in team.members) <= team.social_budget["says_per_hour"]


def test_persona_schema_rejects_unsafe_knobs():
    schema = json.loads((ROOT / "schemas/persona.json").read_text(encoding="utf-8"))
    text = (ROOT / "agents/nibs/persona.md").read_text(encoding="utf-8")
    front = yaml.safe_load(text.split("---", 2)[1])
    jsonschema.validate(front, schema)
    bad = copy.deepcopy(front)
    bad["knobs"]["energy_reserve"] = 10  # below the global floor
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
    bad = copy.deepcopy(front)
    bad["knobs"]["actions_per_wake"] = 5
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
    bad = copy.deepcopy(front)
    bad["knobs"]["social_rate"] = 4
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


def _confirmed(team: Team) -> Team:
    territory = dict(team.territory or {"kind": "circle", "x": 74, "y": 112, "radius": 6})
    territory["status"] = "confirmed"
    return Team(
        slug=team.slug, name=team.name, aim=team.aim, members=team.members, home=team.home,
        territory=territory, social_budget=team.social_budget, links=team.links,
    )


def test_territory_is_binding_only_once_confirmed():
    neverland = load_team(ROOT, "neverland")
    assert neverland.binding_territory is None
    assert in_territory(neverland, 74, 112) is None
    assert in_region(neverland, 74, 112) is True  # proposed home still measures
    confirmed = _confirmed(neverland)
    assert in_territory(confirmed, 74, 112) is True
    assert in_territory(confirmed, 100, 100) is False


def test_nibs_never_leaves_a_confirmed_neverland_and_stays_near_tinker_bell_before():
    nibs = load_persona(ROOT, "nibs")
    observe = load_fixture(FIX / "observe/nibs.json")
    team = load_team(ROOT, "neverland")
    # before Neverland exists: within radius of Tinker Bell
    enforce_knobs([{"action": "move", "x": 76, "y": 114}], nibs, team, observe, teammates={"tinker-bell": (74, 112)})
    with pytest.raises(ValueError, match="stays within 6 of tinker-bell"):
        enforce_knobs([{"action": "move", "x": 85, "y": 112}], nibs, team, observe, teammates={"tinker-bell": (74, 112)})
    # once confirmed: the territory itself is the law
    confirmed = _confirmed(team)
    enforce_knobs([{"action": "move", "x": 78, "y": 110}], nibs, confirmed, observe, teammates={})
    with pytest.raises(ValueError, match="never leaves Neverland"):
        enforce_knobs([{"action": "move", "x": 90, "y": 112}], nibs, confirmed, observe, teammates={})
    with pytest.raises(ValueError, match="never leaves Neverland"):
        enforce_knobs([{"action": "build", "type": "sign", "x": 95, "y": 112}], nibs, confirmed, observe, teammates={})


def test_energy_reserve_blocks_plans_that_dip_below_it():
    tootles = load_persona(ROOT, "tootles")  # reserve 28
    observe = load_fixture(FIX / "observe/tootles.json")
    observe["you"]["energy"] = 35
    observe["you"]["inventory"] = {"stone": 3}
    team = load_team(ROOT, "neverland")
    enforce_knobs([{"action": "move", "x": 112, "y": 72}], tootles, team, observe)  # costs 2
    with pytest.raises(ValueError, match="below the reserve"):
        enforce_knobs([{"action": "move", "x": 120, "y": 70}], tootles, team, observe)  # costs 10
    observe["you"]["energy"] = 20
    with pytest.raises(ValueError, match="no berries"):
        enforce_knobs([{"action": "gather", "kind": "stone"}], tootles, team, observe)
    observe["you"]["home"] = {"x": 106, "y": 75}
    enforce_knobs([{"action": "move", "x": 108, "y": 72}], tootles, team, observe)  # one step toward home is allowed
    observe["you"]["inventory"] = {"berries": 2}
    enforce_knobs([{"action": "eat", "qty": 1}, {"action": "gather", "kind": "stone"}], tootles, team, observe)


def test_social_rate_and_team_budget_cap_public_speech():
    joe = load_persona(ROOT, "grandpa-joe")  # social_rate 2
    team = load_team(ROOT, "chocolate-factory")  # 5 says/hour
    observe = load_fixture(FIX / "observe/grandpa-joe.json")
    say = {"action": "say", "text": "Back at the old factory this took half the time."}
    enforce_knobs([say], joe, team, observe, recent_say_count=1)
    with pytest.raises(ValueError, match="at most 2 time"):
        enforce_knobs([say], joe, team, observe, recent_say_count=2)
    with pytest.raises(ValueError, match="public-speech budget"):
        enforce_knobs([say], joe, team, observe, recent_say_count=0, team_recent_says=5)
    with pytest.raises(ValueError, match="under 240 characters"):
        enforce_knobs([{"action": "say", "text": "x" * 250}], joe, team, observe)
    events = [{"type": "say", "actor": "Wonka", "tick": 100}, {"type": "say", "actor": "MrsBucket", "tick": 300}, {"type": "say", "actor": "Peregrine", "tick": 300}, {"type": "say", "actor": "Wonka", "tick": 1}]
    assert team_say_count(events, {"Wonka", "MrsBucket"}, 400) == 2


def test_actions_per_wake_excludes_the_state_bookkeeping():
    joe = load_persona(ROOT, "grandpa-joe")  # 2 actions per wake
    team = load_team(ROOT, "chocolate-factory")
    observe = load_fixture(FIX / "observe/grandpa-joe.json")
    state = {"action": "remember", "key": PERSONA_STATE_KEY, "text": "{}"}
    enforce_knobs([{"action": "eat", "qty": 1}, {"action": "remember", "key": "plan", "text": "nap"}, state], joe, team, observe)
    with pytest.raises(ValueError, match="at most 2 action"):
        enforce_knobs([{"action": "eat", "qty": 1}, {"action": "remember", "key": "a", "text": "b"}, {"action": "remember", "key": "c", "text": "d"}, state], joe, team, observe)


def test_walls_only_inside_own_confirmed_territory_and_never_beside_others():
    nibs = load_persona(ROOT, "nibs")
    team = load_team(ROOT, "neverland")
    observe = load_fixture(FIX / "observe/nibs.json")
    wall = {"action": "build", "type": "wall", "x": 76, "y": 112}
    with pytest.raises(ValueError, match="only built inside"):
        enforce_knobs([wall], nibs, team, observe, teammates={"tinker-bell": (74, 112)})
    confirmed = _confirmed(team)
    enforce_knobs([wall], nibs, confirmed, observe, teammates={"tinker-bell": (74, 112)})
    observe["structures"].append({"id": 999, "type": "hut", "x": 77, "y": 112, "owner": "Peregrine"})
    with pytest.raises(ValueError, match="beside another agent"):
        enforce_knobs([wall], nibs, confirmed, observe, teammates={"tinker-bell": (74, 112)})
