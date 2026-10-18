import json
from pathlib import Path

from typer.testing import CliRunner

from hglab.actions import validate_actions
from hglab.cli import app
from hglab.fixtures import load_fixture
from hglab.land import (
    board,
    check_ledger,
    deed_text,
    load_ledger,
    office_line,
    plan_round,
    plot_bounds,
    plot_centre,
    plot_id,
    registry_text,
    render_board,
    survey,
    total_plots,
)
from hglab.persona import load_personas

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures"
VAULT = {"id": 900, "type": "storehouse", "x": 65, "y": 64, "owner": "LandBroker", "policy": "private"}
COLLECTIVE = {"LandBroker", "Clarion", "Fudgewright", "MotherPail", "GrandadPail", "Tinkerglow", "Strayling", "Lagalong", "Stoutheart"}


def _observe(**overrides):
    observe = load_fixture(FIX / "observe/land-broker.json")
    observe["you"].update(overrides)
    return observe


def test_plots_are_lettered_columns_and_numbered_rows():
    assert plot_id(64, 63) == "G06" and plot_id(0, 0) == "A00" and plot_id(127, 127) == "M12"
    assert plot_bounds("G06") == (60, 60, 69, 69) and plot_bounds("M12") == (120, 120, 127, 127)
    assert plot_centre("A00") == (4, 4) and total_plots() == 169
    surveyed = survey([{"type": "hut", "x": 67, "y": 56, "owner": "Quill"}, {"type": "farm", "x": 61, "y": 57, "owner": "MotherPail"}, {"type": "road", "x": 66, "y": 74, "owner": "Fudgewright"}, {"type": "road", "x": 60, "y": 58, "owner": "MotherPail"}])
    assert surveyed["G05"]["structures"] == 3 and surveyed["G05"]["holder"] == "MotherPail" and surveyed["G07"]["holder"] == "Fudgewright"


def test_ledger_validates_and_the_registrar_wears_the_right_hats():
    ledger = load_ledger(ROOT)
    assert check_ledger(ledger, load_personas(ROOT)) == []
    text = registry_text([{"plot": f"G{i:02d}", "holder": f"Holder{i}", "tick": 7000 + i} for i in range(60)], ledger)
    assert len(text) <= 500 and text.startswith("Land registry") and "more" in text
    assert len(deed_text({"plot": "G05", "holder": "Quill", "tick": 7900}, "LandBroker")) <= 200


def test_without_a_vault_the_office_only_announces_the_survey():
    ledger = load_ledger(ROOT)
    broker = load_personas(ROOT)["land-broker"]
    b = board(ledger, [{"type": "hut", "x": 70, "y": 59, "owner": "Peregrine"}], [], [], "LandBroker")
    assert b["vault"] is None and b["occupied"] == 1 and b["free"] == 168
    actions, _reasons, update = plan_round(broker, ledger, _observe(), b, public_events=[], structures=[], agents=[], state={}, collective_names=COLLECTIVE)
    assert [a["action"] for a in actions] == ["say"] and "opening" in actions[0]["text"] and update["last_call_tick"] == _observe()["tick"]
    assert len(actions[0]["text"]) <= broker.voice["max_say_chars"]
    validate_actions(actions, "+".join(broker.roles), observe=_observe())


def test_with_a_vault_the_office_posts_the_registration_goal_and_an_offer():
    ledger = load_ledger(ROOT)
    broker = load_personas(ROOT)["land-broker"]
    observe = _observe(inventory={"berries": 6, "wood": 8})
    structures = [VAULT]
    b = board(ledger, structures, [], [], "LandBroker")
    assert b["vault"] == {"x": 65, "y": 64}
    actions, _reasons, _update = plan_round(broker, ledger, observe, b, public_events=[], structures=structures, agents=[], state={}, collective_names=COLLECTIVE)
    kinds = [a["action"] for a in actions]
    assert kinds == ["post_goal", "post_goal", "say"]
    registration, offer, line = actions
    assert registration["title"] == ledger["registration_title"] and registration["condition"] == {"type": "deliver", "x": 65, "y": 64, "item": "wood", "qty": 5}
    assert offer["title"].startswith("Offer: 2 berries for 10 wood") and offer["reward"] == {"berries": 2}
    assert "claim goal" not in line["text"]  # the goal ids are not known until posted
    validate_actions(actions, "+".join(broker.roles), open_goal_count=0, observe=observe)
    posted = [{"id": 21, "title": registration["title"], "poster": "LandBroker", "status": "open"}, {"id": 22, "title": offer["title"], "poster": "LandBroker", "status": "open"}]
    observe["your_goals"] = {"claimed": None, "posted": posted}
    b2 = board(ledger, structures, [], posted, "LandBroker")
    assert b2["registration_goal"] == {"id": 21, "status": "open"} and b2["offers"][0]["goal_id"] == 22
    again, _, _ = plan_round(broker, ledger, observe, b2, public_events=[], structures=structures, agents=[], state={}, collective_names=COLLECTIVE)
    assert [a["action"] for a in again] == ["say"] and "goal #21" in again[0]["text"] and "Buying" in again[0]["text"]
    assert "goal #21" in office_line(ledger, b2, 280)


def test_paid_registrations_become_deeds_from_goal_done_and_collective_gives():
    ledger = load_ledger(ROOT)
    broker = load_personas(ROOT)["land-broker"]
    observe = _observe(x=67, y=56, inventory={"berries": 2, "wood": 3})
    structures = [VAULT, {"type": "hut", "x": 67, "y": 56, "owner": "Quill"}, {"type": "hut", "x": 71, "y": 84, "owner": "Fudgewright"}]
    agents = [{"name": "Quill", "x": 67, "y": 56}, {"name": "Fudgewright", "x": 71, "y": 84}, {"name": "Mara", "x": 30, "y": 30}]
    events = [
        {"type": "goal_done", "tick": 7950, "actor": "Quill", "data": {"goal_id": 21, "title": ledger["registration_title"], "poster": "LandBroker", "reward": {"berries": 1}}},
        {"type": "give", "tick": 7960, "actor": "Fudgewright", "data": {"structure_type": "storehouse", "x": 65, "y": 64, "item": "wood", "qty": 5}},
        {"type": "give", "tick": 7961, "actor": "Mara", "data": {"structure_type": "storehouse", "x": 65, "y": 64, "item": "wood", "qty": 5}},  # not a member: must claim the goal
        {"type": "goal_done", "tick": 7970, "actor": "Quill", "data": {"goal_id": 21, "title": ledger["registration_title"], "poster": "LandBroker"}},  # a repeat changes nothing
    ]
    posted = [{"id": 21, "title": ledger["registration_title"], "poster": "LandBroker", "status": "open"}]
    b = board(ledger, structures, agents, posted, "LandBroker")
    actions, _reasons, update = plan_round(broker, ledger, observe, b, public_events=events, structures=structures, agents=agents, state={"registered": []}, collective_names=COLLECTIVE)
    kinds = [a["action"] for a in actions]
    assert kinds[:2] == ["say", "set_profile"] and "build" in kinds  # standing in G05 with wood: the deed goes on a sign
    assert "deed G05 to Quill" in actions[0]["text"] and "H08 to Fudgewright" in actions[0]["text"]
    assert actions[1]["goals"].startswith("Land registry") and "G05 Quill" in actions[1]["goals"] and "H08 Fudgewright" in actions[1]["goals"]
    assert update["registered"] == ["G05:Quill:7950", "H08:Fudgewright:7960"]
    assert "Mara" not in json.dumps(actions)
    validate_actions(actions, "+".join(broker.roles), observe=observe)
    state = {"registered": update["registered"], "last_call_tick": observe["tick"]}
    observe["you"]["inventory"] = {"berries": 1, "wood": 3}  # too few berries to escrow an offer
    quiet, _, none = plan_round(broker, ledger, observe, board(ledger, structures, agents, posted, "LandBroker", state), public_events=events, structures=structures, agents=agents, state=state, collective_names=COLLECTIVE)
    assert quiet == [] and none == {}


def test_another_persona_has_no_land_duties_and_the_cli_runs_offline():
    ledger = load_ledger(ROOT)
    clarion = load_personas(ROOT)["town-crier"]
    assert plan_round(clarion, ledger, _observe(), board(ledger, [], [], [], "LandBroker"), public_events=[], structures=[], agents=[], state={}, collective_names=COLLECTIVE) == ([], [], {})
    runner = CliRunner()
    result = runner.invoke(app, ["land", "round", "--agent", "land-broker", "--fixture", str(FIX / "observe/land-broker.json"), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "land office round" in result.output and "dry run" in result.output
    assert runner.invoke(app, ["land", "validate"]).exit_code == 0
    result = runner.invoke(app, ["land", "board", "--fixtures"])
    assert result.exit_code == 0 and "plots:" in result.output
    assert "free" in render_board(board(ledger, [], [], [], "LandBroker"))


def test_surplus_goes_into_the_vault_when_no_own_storehouse_is_near():
    from hglab.planner import WorldView, _plan_deposit

    joe = load_personas(ROOT)["grandpa-joe"]
    view = WorldView(x0=60, y0=60, rows=["g" * 10] * 10, structures=[VAULT])
    inventory = {"wood": 25, "stone": 12, "berries": 5}
    assert _plan_deposit(joe, dict(inventory), (64, 64), view) is None
    plan = _plan_deposit(joe, dict(inventory), (64, 64), view, "LandBroker")
    assert plan is not None and plan[0][0] == {"action": "give", "x": 65, "y": 64, "item": "stone", "qty": 12} and "vault" in plan[1]
