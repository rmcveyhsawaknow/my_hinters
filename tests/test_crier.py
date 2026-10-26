import json
from pathlib import Path

from typer.testing import CliRunner

from hglab.actions import validate_actions
from hglab.cli import app
from hglab.crier import (
    board,
    call_line,
    check_ledger,
    duties,
    load_ledger,
    plan_round,
    render_board,
)
from hglab.fixtures import load_fixture
from hglab.persona import load_personas

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures"
NAMES = ["Quill", "Cairn", "Mara", "Bishop"]


def _board(ledger, goals=(), factions=(), says=()):
    return board(ledger, list(goals), list(factions), "Clarion", list(says))


def _posted(ledger, statuses):
    """Clarion's goals for the ledger's requests in order; a request past the given statuses has none yet."""
    padded = [*statuses, *["none"] * (len(ledger["requests"]) - len(statuses))]
    return [
        {"id": 10 + i, "title": r["title"], "poster": "Clarion", "status": status, "claimant": "Quill" if status == "claimed" else None}
        for i, (r, status) in enumerate(zip(ledger["requests"], padded, strict=True))
        if status != "none"
    ]


def test_ledger_validates_and_duties_match_the_hats():
    ledger = load_ledger(ROOT)
    personas = load_personas(ROOT)
    assert check_ledger(ledger, personas) == []
    assert duties(personas["town-crier"], ledger) == {"collect", "found"}
    assert duties(personas["tootles"], ledger) == {"found"}
    assert duties(personas["wonka"], ledger) == set()
    for request in ledger["requests"]:
        assert 3 <= len(request["title"]) <= 80 and len(request["description"]) <= 1000


def test_board_reads_factions_goals_and_public_endorsements():
    ledger = load_ledger(ROOT)
    factions = [{"id": 7, "name": "pixel portraits", "members": 3, "membership": "open"}]
    goals = _posted(ledger, ["expired", "claimed", "open"])
    says = [
        {"type": "say", "actor": "Mara", "text": "I back Blueprint Science too"},
        {"type": "say", "actor": "Clarion", "text": "Blueprint Science!"},
    ]
    b = _board(ledger, goals, factions, says)
    by = {t["name"]: t for t in b["themes"]}
    assert by["Pixel Portraits"]["founded"] and by["Pixel Portraits"]["members"] == 3 and by["Pixel Portraits"]["votes"] == 3
    assert not by["Blueprint Science"]["founded"] and by["Blueprint Science"]["endorsers"] == ["Mara"] and by["Blueprint Science"]["votes"] == 1
    assert by["Readable Replay"]["status"] == "closed" and by["Pixel Portraits"]["status"] == "open"
    _replay, blueprint, portraits, faction_board = b["requests"]
    assert by["Faction Board"]["faction"] is False and not by["Faction Board"]["founded"] and faction_board["goal_id"] is None  # no faction of its own: votes are lines naming it
    assert blueprint["goal_id"] == 11 and blueprint["goal_status"] == "claimed" and blueprint["claimant"] == "Quill"
    assert portraits["goal_status"] == "open" and _replay["ledger_status"] == "parked"
    text = render_board(b)
    assert "Readable Replay (bug) [closed]" in text and "goal #11 claimed, claimed by Quill" in text


def test_first_round_founds_the_theme_and_posts_the_goals_it_can_pay_for():
    ledger = load_ledger(ROOT)
    clarion = load_personas(ROOT)["town-crier"]
    observe = load_fixture(FIX / "observe/town-crier.json")
    observe["you"]["inventory"] = {"berries": 12, "wood": 5}
    observe["you"]["energy"] = 90
    actions, reasons, update = plan_round(clarion, ledger, observe, _board(ledger), active_names=NAMES, state={})
    kinds = [a["action"] for a in actions]
    assert kinds == ["found_faction", "post_goal", "post_goal"]
    assert actions[0]["name"] == "Blueprint Science" and actions[0]["membership"] == "open"
    open_titles = [r["title"] for r in ledger["requests"] if r["status"] == "open"]
    assert [a["title"] for a in actions[1:]] == open_titles[:2] and actions[2]["reward"] == {"berries": 5}  # the parked replay bug is not posted again; two goals at a time
    assert set(update) == {"posted"} and sorted(update["posted"]) == sorted(r["id"] for r in ledger["requests"] if r["title"] in open_titles[:2])  # each posted request remembers its turn; no room for the call, it comes next hour
    validate_actions(actions, "+".join(clarion.roles), open_goal_count=0, observe=observe)
    observe["you"]["inventory"] = {"berries": 5}
    actions, reasons, _ = plan_round(clarion, ledger, observe, _board(ledger), active_names=NAMES, state={})
    assert [a["action"] for a in actions][:2] == ["found_faction", "post_goal"]
    assert any("not in the pack" in r for r in reasons)


def test_a_settled_round_makes_one_call_naming_fresh_residents():
    ledger = load_ledger(ROOT)
    clarion = load_personas(ROOT)["town-crier"]
    observe = load_fixture(FIX / "observe/town-crier.json")
    observe["you"]["faction"] = {"id": 9, "name": "Blueprint Science"}
    posted = _posted(ledger, ["expired", "open", "open"])
    observe["your_goals"] = {"claimed": None, "posted": posted}
    factions = [{"id": 9, "name": "Blueprint Science", "members": 1, "membership": "open"}, {"id": 8, "name": "Readable Replay", "members": 1, "membership": "open"}, {"id": 10, "name": "Pixel Portraits", "members": 2, "membership": "open"}]
    b = _board(ledger, posted, factions)
    actions, _, update = plan_round(clarion, ledger, observe, b, active_names=NAMES, state={}, factions_of={"Quill": "Wayfarers"})
    assert [a["action"] for a in actions] == ["invite", "invite", "say"]
    assert [a["name"] for a in actions[:2]] == ["Cairn", "Mara"]  # Quill already belongs to a faction
    assert update["invited"] == ["Cairn", "Mara"]
    line = actions[2]["text"]
    assert len(line) <= clarion.voice["max_say_chars"] and all(n in line for n in NAMES[:3]) and "goal #11" in line
    assert "Readable Replay" not in line  # a closed theme is not called
    assert update["asked"] == NAMES[:3] and update["last_call_tick"] == observe["tick"]
    validate_actions(actions, "+".join(clarion.roles), observe=observe)
    later, _, update_later = plan_round(clarion, ledger, observe, b, active_names=NAMES, state={**update, "last_call_tick": observe["tick"] - 1000}, factions_of={"Quill": "Wayfarers"})
    assert [a["action"] for a in later] == ["invite", "say"] and later[0]["name"] == "Bishop"  # Cairn and Mara were invited already
    assert update_later["invited"] == ["Cairn", "Mara", "Bishop"]
    everyone = {**update_later, "invited": NAMES, "last_call_tick": observe["tick"] - 1000}
    again, _, update2 = plan_round(clarion, ledger, observe, b, active_names=NAMES, state=everyone)
    assert [a["action"] for a in again] == ["say"] and "Quill" in again[0]["text"] and update2["asked"] == NAMES[:3]  # everyone was asked once: the rotation starts over
    third, _, update3 = plan_round(clarion, ledger, observe, b, active_names=NAMES, state={**update2, "invited": NAMES, "last_call_tick": observe["tick"] - 1000})
    assert "Bishop" in third[0]["text"] and update3["asked"] == NAMES
    quiet, _, none = plan_round(clarion, ledger, observe, b, active_names=NAMES, state={**update, "invited": NAMES})
    assert quiet == [] and none == {}


def test_a_parked_request_gives_its_goal_slot_to_an_open_one():
    """On 2026-10-25 the owner closed Readable Replay while its goal was open; Clarion held two open goals, the most allowed."""
    ledger = load_ledger(ROOT)
    clarion = load_personas(ROOT)["town-crier"]
    observe = load_fixture(FIX / "observe/town-crier.json")
    observe["you"]["faction"] = {"id": 9, "name": "Blueprint Science"}
    observe["you"]["inventory"] = {"berries": 2}
    observe["you"]["energy"] = 90
    posted = [{**g, "reward": {"berries": 5}} for g in _posted(ledger, ["open", "open", "none"])[:2]]
    observe["your_goals"] = {"claimed": None, "posted": posted}
    b = _board(ledger, posted, [{"id": 9, "name": "Blueprint Science", "members": 1}])
    actions, reasons, _ = plan_round(clarion, ledger, observe, b, active_names=[], state={"last_call_tick": observe["tick"]})
    assert [a["action"] for a in actions] == ["cancel_goal", "post_goal"] and actions[0]["goal_id"] == 10  # the replay bug's goal, not the blueprint one
    assert actions[1]["title"] == ledger["requests"][2]["title"]  # the refunded escrow pays the portraits goal's reward
    assert any("no longer open" in r for r in reasons)
    validate_actions(actions, "+".join(clarion.roles), open_goal_count=2, observe=observe)
    posted[0]["status"], posted[0]["claimant"] = "claimed", "Quill"
    held, _, _ = plan_round(clarion, ledger, observe, _board(ledger, posted, [{"id": 9, "name": "Blueprint Science", "members": 1}]), active_names=[], state={"last_call_tick": observe["tick"]})
    assert not any(a["action"] == "cancel_goal" for a in held)  # a claimed goal waits for its claimant


def test_feedback_from_a_claimant_is_confirmed():
    ledger = load_ledger(ROOT)
    clarion = load_personas(ROOT)["town-crier"]
    observe = load_fixture(FIX / "observe/town-crier.json")
    observe["you"]["faction"] = {"id": 9, "name": "Blueprint Science"}
    posted = _posted(ledger, ["expired", "claimed", "open"])
    observe["your_goals"] = {"claimed": None, "posted": posted}
    observe["inbox"] = [{"id": 1, "from": "Quill", "text": "private report", "tick": observe["tick"]}]
    b = _board(ledger, posted, [{"id": 9, "name": "Blueprint Science", "members": 1}])
    actions, reasons, _ = plan_round(clarion, ledger, observe, b, active_names=[], state={"last_call_tick": observe["tick"]})
    assert actions == [{"action": "confirm_goal", "goal_id": 11}]  # nobody to invite, no call due
    assert not any("private report" in r for r in reasons)


def test_a_theme_founder_founds_once_and_nothing_else():
    ledger = load_ledger(ROOT)
    lagalong = load_personas(ROOT)["tootles"]
    observe = load_fixture(FIX / "observe/tootles.json")
    actions, _, update = plan_round(lagalong, ledger, observe, _board(ledger), active_names=NAMES, state={})
    assert [a["action"] for a in actions] == ["found_faction"] and actions[0]["name"] == "Pixel Portraits" and update == {}  # the closed theme is never founded again
    observe["you"]["faction"] = {"id": 3, "name": "Readable Replay"}
    closing, reasons, _ = plan_round(lagalong, ledger, observe, _board(ledger, factions=[{"id": 3, "name": "Readable Replay", "members": 1}]), active_names=NAMES, state={})
    assert [a["action"] for a in closing] == ["leave_faction", "found_faction"] and closing[1]["name"] == "Pixel Portraits" and closing[1]["membership"] == "open"
    assert any("is closed" in r for r in reasons)
    validate_actions(closing, "+".join(lagalong.roles), observe=observe)
    observe["you"]["faction"] = None
    founded = _board(ledger, factions=[{"id": 8, "name": "Pixel Portraits", "members": 1}])
    assert plan_round(lagalong, ledger, observe, founded, active_names=NAMES, state={})[0] == []
    observe["you"]["faction"] = {"id": 8, "name": "Pixel Portraits"}
    invites, reasons, update = plan_round(lagalong, ledger, observe, founded, active_names=NAMES, state={}, factions_of={"Quill": "Wayfarers"})
    assert [a["action"] for a in invites] == ["invite", "invite"] and [a["name"] for a in invites] == ["Cairn", "Mara"]
    assert update == {"invited": ["Cairn", "Mara"]} and all("Factions feed" in r for r in reasons)
    validate_actions(invites, "+".join(lagalong.roles), observe=observe)


def test_the_call_line_fits_any_limit():
    clarion = load_personas(ROOT)["town-crier"]
    ledger = load_ledger(ROOT)
    b = _board(ledger, factions=[{"id": 1, "name": "Readable Replay", "members": 12}, {"id": 2, "name": "Blueprint Science", "members": 7}])
    for limit in (280, 200, 120):
        clarion.voice["max_say_chars"] = limit
        line = call_line(clarion, b, ["Quill", "Cairn", "Mara"], 7200)
        assert len(line) <= limit and "Quill" in line
    clarion.voice["max_say_chars"] = 280


def test_cli_round_runs_offline_and_validate_passes():
    runner = CliRunner()
    result = runner.invoke(app, ["crier", "round", "--agent", "town-crier", "--fixture", str(FIX / "observe/town-crier.json"), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "collector round" in result.output and "found_faction" in result.output and "dry run" in result.output
    result = runner.invoke(app, ["crier", "validate"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["crier", "board", "--fixtures"])
    assert result.exit_code == 0 and "Readable Replay" in result.output
    records = sorted((ROOT / "runs").glob("*/Clarion-collector-*.json"))
    if records:
        latest = json.loads(records[-1].read_text(encoding="utf-8"))
        assert "inbox" not in json.dumps(latest) or "private" not in json.dumps(latest)


def test_the_shift_keeps_its_closing_line_when_the_round_has_no_call(monkeypatch):
    from hglab import cli_personas

    calls = {"announce": 0}
    outcomes = iter([{"said": False}, {"said": True}])
    monkeypatch.setattr(cli_personas, "crier_round", lambda *a, **k: next(outcomes))
    monkeypatch.setattr(cli_personas, "announce_shift", lambda *a, **k: calls.__setitem__("announce", calls["announce"] + 1))
    runner = CliRunner()
    args = ["shift", "--agent", "town-crier", "--fixture", str(FIX / "observe/town-crier.json"), "--max-wakes", "1", "--dry-run"]
    assert runner.invoke(app, args).exit_code == 0
    assert calls["announce"] == 1  # the round was silent, so the shift spoke
    assert runner.invoke(app, args).exit_code == 0
    assert calls["announce"] == 1  # the round spoke, so the shift stayed quiet


def test_an_agent_already_invited_in_public_is_not_invited_again():
    from hglab.crier import plan_invites
    from hglab.persona import load_personas

    clarion = load_personas(ROOT)["town-crier"]
    theme = {"name": "Readable Replay", "founded": True}
    events = [{"type": "faction_invited", "actor": "Clarion", "text": "Clarion invited LandBroker to Readable Replay."}]
    actions, _reasons, names = plan_invites(clarion, {}, theme, ["LandBroker", "Quill", "Cairn"], {"Cairn": "Goon Squad"}, {}, public_events=events)
    assert names == ["Quill"] and actions == [{"action": "invite", "name": "Quill"}]
    assert plan_invites(clarion, {}, theme, ["LandBroker"], {}, {"invited": ["LandBroker"]})[2] == []


def test_theme_invitations_skip_members_of_teams_with_their_own_faction():
    from hglab.crier import reserved_names
    from hglab.persona import load_personas, load_teams

    personas, teams = load_personas(ROOT), load_teams(ROOT)
    reserved = reserved_names(personas, teams)
    assert {"Strayling", "Tinkerglow", "Stoutheart", "Fudgewright", "MotherPail", "GrandadPail"} <= reserved
    assert "Lagalong" not in reserved and "Clarion" not in reserved  # exempt, or a team with no faction
    assert "Plumbline" in reserved  # the atelier joins the factory's faction as its ally (2026-10-24): no theme for it


def test_every_open_request_takes_its_turn_in_the_two_goal_slots():
    """2026-10-26: the owner's Faction Board request would have waited forever behind two requests reposted on every expiry."""
    from hglab.crier import ROTATE_TICKS

    ledger = load_ledger(ROOT)
    clarion = load_personas(ROOT)["town-crier"]
    observe = load_fixture(FIX / "observe/town-crier.json")
    observe["you"]["faction"] = {"id": 9, "name": "Blueprint Science"}
    observe["you"]["inventory"] = {"berries": 12}
    observe["you"]["energy"] = 90
    tick = observe["tick"]
    titles = {r["id"]: r["title"] for r in ledger["requests"]}
    goals = [
        {"id": 46, "title": titles["R-20261018-propose-blueprint"], "poster": "Clarion", "status": "open", "claimant": None, "created_tick": tick - ROTATE_TICKS - 10},
        {"id": 47, "title": titles["R-20261025-agent-portraits"], "poster": "Clarion", "status": "open", "claimant": None, "created_tick": tick - 100},
    ]
    observe["your_goals"] = {"claimed": None, "posted": [{k: g[k] for k in ("id", "title", "status")} for g in goals]}
    b = _board(ledger, goals, [{"id": 9, "name": "Blueprint Science", "members": 1}])
    actions, reasons, update = plan_round(clarion, ledger, observe, b, active_names=[], state={"last_call_tick": tick})
    assert [a["action"] for a in actions] == ["cancel_goal", "post_goal"] and actions[0]["goal_id"] == 46  # the goal that stood half a day unclaimed
    assert actions[1]["title"] == titles["R-20261026-faction-board"] and update["posted"]["R-20261026-faction-board"] == tick
    assert any("waiting for its first posting" in r for r in reasons)
    validate_actions(actions, "+".join(clarion.roles), open_goal_count=2, observe=observe)
    young = [{**goals[0], "created_tick": tick - 100}, goals[1]]
    held, _, _ = plan_round(clarion, ledger, observe, _board(ledger, young, [{"id": 9, "name": "Blueprint Science", "members": 1}]), active_names=[], state={"last_call_tick": tick})
    assert held == []  # both goals are young: the new request waits for a slot
    turned, _, _ = plan_round(clarion, ledger, observe, b, active_names=[], state={"last_call_tick": tick, "posted": {"R-20261026-faction-board": tick - 9000}})
    assert turned == []  # it has had its turn: it waits for the next slot that frees, no cancel
    line = call_line(clarion, b, NAMES[:2], tick)
    assert "Faction Board 0 votes (say its name)" in line
