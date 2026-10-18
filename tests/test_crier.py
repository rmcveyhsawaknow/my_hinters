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
    return [
        {"id": 10 + i, "title": r["title"], "poster": "Clarion", "status": status, "claimant": "Quill" if status == "claimed" else None}
        for i, (r, status) in enumerate(zip(ledger["requests"], statuses, strict=True))
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
    factions = [{"id": 7, "name": "readable replay", "members": 3, "membership": "open"}]
    goals = _posted(ledger, ["claimed", "open"])
    says = [
        {"type": "say", "actor": "Mara", "text": "I back Blueprint Science too"},
        {"type": "say", "actor": "Clarion", "text": "Blueprint Science!"},
    ]
    b = _board(ledger, goals, factions, says)
    by = {t["name"]: t for t in b["themes"]}
    assert by["Readable Replay"]["founded"] and by["Readable Replay"]["members"] == 3 and by["Readable Replay"]["votes"] == 3
    assert not by["Blueprint Science"]["founded"] and by["Blueprint Science"]["endorsers"] == ["Mara"] and by["Blueprint Science"]["votes"] == 1
    first, second = b["requests"]
    assert first["goal_id"] == 10 and first["goal_status"] == "claimed" and first["claimant"] == "Quill"
    assert second["goal_status"] == "open"
    text = render_board(b)
    assert "Readable Replay" in text and "goal #10 claimed, claimed by Quill" in text


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
    assert actions[1]["title"] == ledger["requests"][0]["title"] and actions[2]["reward"] == {"berries": 5}
    assert update == {}  # no room for the call this round; it comes next hour
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
    posted = _posted(ledger, ["open", "open"])
    observe["your_goals"] = {"claimed": None, "posted": posted}
    factions = [{"id": 9, "name": "Blueprint Science", "members": 1, "membership": "open"}, {"id": 8, "name": "Readable Replay", "members": 2, "membership": "open"}]
    b = _board(ledger, posted, factions)
    actions, _, update = plan_round(clarion, ledger, observe, b, active_names=NAMES, state={}, factions_of={"Quill": "Wayfarers"})
    assert [a["action"] for a in actions] == ["invite", "invite", "say"]
    assert [a["name"] for a in actions[:2]] == ["Cairn", "Mara"]  # Quill already belongs to a faction
    assert update["invited"] == ["Cairn", "Mara"]
    line = actions[2]["text"]
    assert len(line) <= clarion.voice["max_say_chars"] and all(n in line for n in NAMES[:3]) and "goal #10" in line
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


def test_feedback_from_a_claimant_is_confirmed():
    ledger = load_ledger(ROOT)
    clarion = load_personas(ROOT)["town-crier"]
    observe = load_fixture(FIX / "observe/town-crier.json")
    observe["you"]["faction"] = {"id": 9, "name": "Blueprint Science"}
    posted = _posted(ledger, ["claimed", "open"])
    observe["your_goals"] = {"claimed": None, "posted": posted}
    observe["inbox"] = [{"id": 1, "from": "Quill", "text": "private report", "tick": observe["tick"]}]
    b = _board(ledger, posted, [{"id": 9, "name": "Blueprint Science", "members": 1}])
    actions, reasons, _ = plan_round(clarion, ledger, observe, b, active_names=[], state={"last_call_tick": observe["tick"]})
    assert actions == [{"action": "confirm_goal", "goal_id": 10}]  # nobody to invite, no call due
    assert not any("private report" in r for r in reasons)


def test_a_theme_founder_founds_once_and_nothing_else():
    ledger = load_ledger(ROOT)
    lagalong = load_personas(ROOT)["tootles"]
    observe = load_fixture(FIX / "observe/tootles.json")
    actions, _, update = plan_round(lagalong, ledger, observe, _board(ledger), active_names=NAMES, state={})
    assert [a["action"] for a in actions] == ["found_faction"] and actions[0]["name"] == "Readable Replay" and update == {}
    founded = _board(ledger, factions=[{"id": 8, "name": "Readable Replay", "members": 1}])
    assert plan_round(lagalong, ledger, observe, founded, active_names=NAMES, state={})[0] == []
    observe["you"]["faction"] = {"id": 8, "name": "Readable Replay"}
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
