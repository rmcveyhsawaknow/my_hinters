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


def test_only_the_founder_invites_and_each_member_only_once(tmp_path):
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
    remembered = json.loads(json.dumps(observe))
    remembered["notebook"] = {
        "persona_state": json.dumps({"mood": load_personas(ROOT)["nibs"].mood_model["initial"], "flags": {"faction_invited": {"Strayling": observe["tick"] - 100}}})
    }
    again = _wake("nibs", remembered, tmp_path)
    assert not any(a["action"] == "invite" for a in again["actions"])  # invited lately: nobody is asked twice within six hours
    member = json.loads(json.dumps(observe))
    member["you"]["faction"] = {"id": 7, "name": "Neverland"}
    assert not any(a["action"] == "invite" for a in _wake("tinker-bell", member, tmp_path)["actions"])  # a member inside never tops up


def test_a_member_found_in_a_theme_faction_leaves_it_for_the_teams_own(tmp_path):
    observe = _observe(
        _factions=[
            {"id": 2, "name": "Blueprint Science", "members": 2, "membership": "open"},
            {"id": 6, "name": "Neverland", "members": 2, "membership": "invite"},
        ]
    )
    observe["you"]["faction"] = {"id": 2, "name": "Blueprint Science"}
    record = _wake("lost-boy", observe, tmp_path)
    kinds = [a["action"] for a in record["actions"] if a["action"] != "remember"]
    assert kinds[:2] == ["leave_faction", "join_faction"] and record["actions"][1]["faction_id"] == 6
    assert record["approach"] == "team" and "the team comes first" in " ".join(record["reasons"])
    soon = json.loads(json.dumps(observe))
    soon["notebook"] = {"persona_state": json.dumps({"mood": load_personas(ROOT)["lost-boy"].mood_model["initial"], "flags": {"faction_switch": observe["tick"] - 100}})}
    assert "leave_faction" not in [a["action"] for a in _wake("lost-boy", soon, tmp_path)["actions"]]  # tried lately: wait
    theme = json.loads(json.dumps(observe))
    theme["you"]["faction"] = {"id": 3, "name": "Readable Replay"}
    assert "leave_faction" not in [a["action"] for a in _wake("tootles", theme, tmp_path)["actions"]]  # Lagalong is exempt: his theme stands


def test_a_join_without_an_invitation_in_view_waits_two_hours_between_tries(tmp_path):
    existing = [{"id": 7, "name": "Neverland", "members": 1, "membership": "invite"}]
    observe = _observe(_factions=existing)
    observe["notebook"] = {"persona_state": json.dumps({"mood": load_personas(ROOT)["tinker-bell"].mood_model["initial"], "flags": {"faction_join_try": observe["tick"] - 100}})}
    assert "join_faction" not in [a["action"] for a in _wake("tinker-bell", observe, tmp_path)["actions"]]
    invited = json.loads(json.dumps(observe))
    invited["events"] = [
        {"type": "faction_invited", "actor": "Stoutheart", "tick": observe["tick"] - 5, "text": "Stoutheart invited Tinkerglow to join the faction Neverland.", "data": {"faction_id": 7, "name": "Neverland", "invitee": "Tinkerglow"}}
    ]
    record = _wake("tinker-bell", invited, tmp_path)
    assert record["actions"][0] == {"action": "join_faction", "faction_id": 7}  # the invitation is in view: join at once
    later = json.loads(json.dumps(observe))
    later["notebook"] = {"persona_state": json.dumps({"mood": load_personas(ROOT)["tinker-bell"].mood_model["initial"], "flags": {"faction_join_try": observe["tick"] - 800}})}
    assert _wake("tinker-bell", later, tmp_path)["actions"][0]["action"] == "join_faction"


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


def test_the_assignment_s_preferred_steps_come_before_the_default_order(tmp_path):
    base = _observe(
        _factions=[{"id": 7, "name": "Neverland", "members": 3, "membership": "invite"}]
    )
    base["you"]["faction"] = {"id": 7, "name": "Neverland"}
    base["you"]["inventory"] = {"wood": 20, "stone": 10, "fiber": 6, "berries": 4}
    base["you"]["home"] = None
    assert _wake("nibs", json.loads(json.dumps(base)), tmp_path)["actions"][0]["action"] == "build"
    steered_observe = json.loads(json.dumps(base))
    steered_observe["_guidance"] = {"assignment": {"label": "stores", "works": [], "avoid": [], "prefer": ["gather_trip", "build"]}}
    steered = _wake("nibs", steered_observe, tmp_path)
    kinds = [a["action"] for a in steered["actions"] if a["action"] != "remember"]
    assert kinds[0] in {"move", "gather"} and steered["approach"] in {"gather_trip", "gather_near"}
    assert steered["assignment"]["prefer"] == ["gather_trip", "build"] and steered["assignment"]["stalled"] is False
    tick_observe = json.loads(json.dumps(base))
    tick_observe["_guidance"] = {"assignment": {"label": "stores", "works": [], "avoid": [], "prefer": ["gather_trip"]}}
    personas = load_personas(ROOT)
    client = FixtureClient(tick_observe)
    record = persona_wake(
        persona=personas["nibs"], team=load_team(ROOT, "neverland"), personas=personas, client=client,
        lease=acquire(client, personas["nibs"].name), root=ROOT, output_dir=tmp_path, dry_run=True, work=False, seed="team",
    )
    record = record[0] if isinstance(record, tuple) else record
    first = next(a for a in record["actions"] if a["action"] != "remember")
    assert first["action"] in {"move", "gather"}  # the tick wake, too, runs the gather activity before the build


def test_the_founder_skips_mates_the_world_does_not_know_and_those_the_roster_shows_inside(tmp_path):
    from hglab.mood import PersonaState
    from hglab.planner import WorldView, _plan_team_faction, _roster

    personas = load_personas(ROOT)
    wonka = personas["wonka"]
    team = load_team(ROOT, "chocolate-factory")
    names = {p.name: s for s, p in personas.items()}
    observe = {"you": {"name": "Fudgewright", "faction": {"id": 5, "name": "Chocolate Factory"}}, "tick": 55600, "agents": [],
               "_factions": [{"id": 5, "name": "Chocolate Factory", "members": 3, "membership": "invite"}]}
    residents = [
        {"name": "Fudgewright", "faction": {"id": 5, "name": "Chocolate Factory"}},
        {"name": "MotherPail", "faction": {"id": 5, "name": "Chocolate Factory"}},
        {"name": "GrandadPail", "faction": {"id": 5, "name": "Chocolate Factory"}},
        {"name": "Treacleaxe", "faction": None},
        {"name": "Nougatpick", "faction": None},
        {"name": "Sherbetsack", "faction": None},
    ]  # Caramelcart and Toffeetrowel are not registered yet
    roster = _roster(WorldView(x0=0, y0=0, rows=["g" * 128] * 128, residents=residents))
    state = PersonaState(mood="gentle")
    state.flags["faction_invited"] = ["Caramelcart", "GrandadPail", "MotherPail"]  # a wake before the roster was consulted
    step = _plan_team_faction(wonka, team, state, observe, 100, 25, {p.name for p in personas.values()}, names, room=3, roster=roster)
    assert step is not None and sorted(a["name"] for a in step[0]) == ["Nougatpick", "Sherbetsack", "Treacleaxe"]
    assert "Caramelcart" not in state.flags["faction_invited"]  # dropped: the world never knew the name, so it was never invited
    later = dict(roster, Caramelcart=None)
    again = _plan_team_faction(wonka, team, state, observe, 100, 25, {p.name for p in personas.values()}, names, room=3, roster=later)
    assert again is not None and [a["name"] for a in again[0]] == ["Caramelcart"]  # registered since: invited now, once
    assert _plan_team_faction(wonka, team, state, observe, 100, 25, {p.name for p in personas.values()}, names, room=3, roster=later) is None
    assert state.flags["faction_invited"]["Caramelcart"] == 55600  # the memory carries the tick of the invitation
    quiet = dict(observe, agents=[])
    pruned = PersonaState(mood="gentle")
    pruned.flags["faction_invited"] = {"Caramelcart": 1, "Treacleaxe": 55500, "Nougatpick": 55500, "Sherbetsack": 55500}
    assert _plan_team_faction(wonka, team, pruned, quiet, 100, 25, {p.name for p in personas.values()}, names, room=3, roster=roster) is None  # nobody known is pending
    assert "Caramelcart" not in pruned.flags["faction_invited"]  # the pruning is written back even when nobody is pending
    old_invite = PersonaState(mood="gentle")
    old_invite.flags["faction_invited"] = {"Treacleaxe": 50000, "Nougatpick": 55500, "Sherbetsack": 55500}
    retry = _plan_team_faction(wonka, team, old_invite, quiet, 100, 25, {p.name for p in personas.values()}, names, room=3, roster=roster)
    assert retry is not None and [a["name"] for a in retry[0]] == ["Treacleaxe"]  # still outside six hours on: asked again
