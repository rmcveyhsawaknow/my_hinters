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
    assert [a["action"] for a in again] == ["say"] and "goal #21" in again[0]["text"] and "lots staked" in again[0]["text"]
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
    assert "Land registry" in actions[1]["goals"] and "G05 Quill" in actions[1]["goals"] and "H08 Fudgewright" in actions[1]["goals"]
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


def test_the_office_lists_lots_at_a_rising_price_and_sales_become_deeds():
    from hglab.lots import stake_text

    ledger = load_ledger(ROOT)
    broker = load_personas(ROOT)["land-broker"]
    observe = _observe(x=66, y=66, inventory={"berries": 4, "wood": 6})
    signs = [{"type": "sign", "x": 62 + 5 * i, "y": 62, "owner": "LandBroker", "text": stake_text(f"G06-{q}", "LandBroker")} for i, q in enumerate(("NW", "NE"))]
    structures = [VAULT, *signs]
    posted = [{"id": 21, "title": ledger["registration_title"], "poster": "LandBroker", "status": "open"}]
    observe["your_goals"] = {"claimed": None, "posted": posted}
    b = board(ledger, structures, [], posted, "LandBroker")
    assert b["lots"]["staked"] == 2 and b["lots"]["for_sale"] == 2 and b["lots"]["price"] == 5 and b["sale_goal"] is None
    actions, _reasons, _ = plan_round(broker, ledger, observe, b, public_events=[], structures=structures, agents=[], state={"last_call_tick": observe["tick"]}, collective_names=COLLECTIVE)
    assert [a["action"] for a in actions] == ["post_goal"]
    listing = actions[0]
    assert listing["title"] == "Buy a 5x5 lot from the land office" and listing["condition"]["qty"] == 5 and listing["reward"] == {"berries": 1}
    validate_actions(actions, "+".join(broker.roles), open_goal_count=1, observe=observe)
    # the price moved (most of the world filled up): the stale listing comes down and a fresh one goes up
    posted2 = [*posted, {"id": 30, "title": listing["title"], "poster": "LandBroker", "status": "open", "condition": {"type": "deliver", "x": 65, "y": 64, "item": "wood", "qty": 5}}]
    observe["your_goals"] = {"claimed": None, "posted": posted2}
    crowded = structures + [{"type": "road", "x": (i * 5) % 128, "y": (i * 5) // 128 * 5, "owner": "Cairn"} for i in range(620)]
    b2 = board(ledger, crowded, [], posted2, "LandBroker")
    assert b2["lots"]["price"] > 5 and b2["sale_goal"] == {"id": 30, "status": "open", "qty": 5}
    actions2, _, _ = plan_round(broker, ledger, observe, b2, public_events=[], structures=crowded, agents=[], state={"last_call_tick": observe["tick"]}, collective_names=COLLECTIVE)
    assert [a["action"] for a in actions2] == ["cancel_goal", "post_goal"] and actions2[0]["goal_id"] == 30 and actions2[1]["condition"]["qty"] == b2["lots"]["price"]
    validate_actions(actions2, "+".join(broker.roles), open_goal_count=2, observe=observe)
    # a sale: Quill paid and named a lot by whisper; Mara paid and gets the unsold lot nearest her hut
    observe["inbox"] = [{"id": 1, "from": "Quill", "text": "I want lot G06-NE please", "tick": observe["tick"]}]
    events = [
        {"type": "goal_done", "tick": 9000, "actor": "Quill", "data": {"goal_id": 30, "title": listing["title"], "poster": "LandBroker"}},
        {"type": "goal_done", "tick": 9010, "actor": "Mara", "data": {"goal_id": 30, "title": listing["title"], "poster": "LandBroker"}},
    ]
    agents = [{"name": "Mara", "x": 61, "y": 66}]
    actions3, _reasons3, update3 = plan_round(broker, ledger, observe, b, public_events=events, structures=structures, agents=agents, state={"registered": [], "last_call_tick": observe["tick"]}, collective_names=COLLECTIVE)
    assert update3["registered"] == ["G06-NE:Quill:9000", "G06-NW:Mara:9010"]
    assert actions3[0]["action"] == "say" and "lot G06-NE sold to Quill" in actions3[0]["text"] and "G06-NW to Mara" in actions3[0]["text"]
    assert actions3[1]["action"] == "set_profile" and "G06-NE Quill" in actions3[1]["goals"] and "Lots (5x5)" in actions3[1]["goals"]
    assert "I want lot" not in json.dumps(actions3)  # the whisper never leaves the inbox
    validate_actions(actions3, "+".join(broker.roles), observe=observe)
    after = board(ledger, structures, agents, posted, "LandBroker", {"registered": update3["registered"]})
    assert after["lots"]["for_sale"] == 0 and after["lots"]["sold"] == 2


def test_the_lot_listing_takes_an_offers_slot_when_both_are_full():
    from hglab.lots import stake_text

    ledger = load_ledger(ROOT)
    broker = load_personas(ROOT)["land-broker"]
    observe = _observe(x=66, y=66, inventory={"berries": 4, "wood": 6})
    structures = [VAULT, {"type": "sign", "x": 62, "y": 67, "owner": "LandBroker", "text": stake_text("G06-NW", "LandBroker")}]
    posted = [
        {"id": 7, "title": ledger["registration_title"], "poster": "LandBroker", "status": "open"},
        {"id": 8, "title": "Offer: 2 berries for 10 wood into the land office vault", "poster": "LandBroker", "status": "open"},
    ]
    observe["your_goals"] = {"claimed": None, "posted": posted}
    b = board(ledger, structures, [], posted, "LandBroker")
    assert b["offers"][0]["goal_id"] == 8 and b["sale_goal"] is None and b["lots"]["for_sale"] == 1
    actions, reasons, _ = plan_round(broker, ledger, observe, b, public_events=[], structures=structures, agents=[], state={"last_call_tick": observe["tick"]}, collective_names=COLLECTIVE)
    assert [a["action"] for a in actions] == ["cancel_goal", "post_goal"] and actions[0]["goal_id"] == 8
    assert actions[1]["title"] == "Buy a 5x5 lot from the land office" and any("gives its slot" in r for r in reasons)
    validate_actions(actions, "+".join(broker.roles), open_goal_count=2, observe=observe)


CLAIMS = {"registrar": "LandBroker", "keep": 1, "always_ore": True, "floor": 0, "protect_spawn": 12, "protect_homesteads": True}


def _world(structures, resources):
    return {"terrain": ["g" * 128] * 128, "width": 128, "structures": structures, "resources": resources, "agents": []}


def test_holdings_leave_the_market_and_their_signs_are_firmed_when_the_office_passes():
    from hglab.lots import holding_text, lot_anchor, stake_text

    ledger = load_ledger(ROOT)
    broker = load_personas(ROOT)["land-broker"]
    lots = ["H04-NW", "H04-NE", "I04-NW"]
    signs = [{"type": "sign", "x": lot_anchor(lid)[0], "y": lot_anchor(lid)[1], "owner": "LandBroker", "text": stake_text(lid, "LandBroker")} for lid in lots]
    stones = [{"kind": "stone", "x": lot_anchor("H04-NE")[0] + dx, "y": lot_anchor("H04-NE")[1], "amount": 20} for dx in (-1, 0, 1)]
    structures = [VAULT, *signs]
    world = _world(structures, stones)
    b = board(ledger, structures, [], [], "LandBroker", world=world, tick=1000, claims=CLAIMS)
    assert [h["lot"] for h in b["holdings"]] == ["H04-NE"] and b["lots"]["for_sale"] == 2 and b["lots"]["holdings"] == 1
    assert "holdings: 1 lots kept off the market" in render_board(b)
    plain = board(ledger, structures, [], [], "LandBroker", world=world, tick=1000)
    assert plain["holdings"] == [] and plain["lots"]["for_sale"] == 3  # without the claims block nothing is kept
    anchor = lot_anchor("H04-NE")
    observe = _observe(x=anchor[0] + 1, y=anchor[1], inventory={"berries": 4, "wood": 6})
    observe["your_goals"] = {"claimed": None, "posted": [{"id": 21, "title": ledger["registration_title"], "poster": "LandBroker", "status": "open"}]}
    actions, reasons, _ = plan_round(broker, ledger, observe, b, public_events=[], structures=structures, agents=[], state={"last_call_tick": observe["tick"]}, collective_names=COLLECTIVE, world=world, claims=CLAIMS)
    write = next(a for a in actions if a["action"] == "write")
    assert (write["x"], write["y"]) == anchor and write["text"] == holding_text(CLAIMS, b["holdings"][0], "LandBroker") and any("its claim sign now says the lot is kept" in r for r in reasons)
    validate_actions(actions, "+".join(broker.roles), open_goal_count=1, observe=observe)
    firmed = [*structures]
    firmed[2] = {**signs[1], "text": holding_text(CLAIMS, b["holdings"][0], "LandBroker")}
    b2 = board(ledger, firmed, [], [], "LandBroker", world=_world(firmed, stones), tick=1000, claims=CLAIMS)
    again, _, _ = plan_round(broker, ledger, observe, b2, public_events=[], structures=firmed, agents=[], state={"last_call_tick": observe["tick"]}, collective_names=COLLECTIVE, world=world, claims=CLAIMS)
    assert not any(a["action"] == "write" for a in again)  # firm already
    assert "Holdings: 1 lots kept" in registry_text([], ledger, b)


def test_goods_are_sold_from_the_vault_through_goals_that_confirm_themselves():
    from hglab.land import sale_goal_title

    ledger = load_ledger(ROOT)
    broker = load_personas(ROOT)["land-broker"]
    sale = ledger["sales"][0]
    assert sale["id"] == "ore-for-wood" and sale_goal_title(sale) == "Land office sale: 10 ore for 30 wood"
    observe = _observe(x=66, y=64, inventory={"berries": 4, "ore": 12})  # beside the vault with the goods in the pack
    observe["structures"] = [{**VAULT, "storage": {"ore": 40, "stone": 70}}]
    observe["your_goals"] = {"claimed": None, "posted": []}
    b = board(ledger, [VAULT], [], [], "LandBroker")
    assert b["sales"][0] == {"id": "ore-for-wood", "title": "Land office sale: 10 ore for 30 wood", "status": "open", "goal_id": None, "goal_status": None}
    actions, _reasons, _ = plan_round(broker, ledger, observe, b, public_events=[], structures=[VAULT], agents=[], state={"last_call_tick": observe["tick"]}, collective_names=COLLECTIVE)
    listing = next(a for a in actions if a["action"] == "post_goal" and a["title"].startswith("Land office sale"))
    assert listing["reward"] == {"ore": 10} and listing["condition"] == {"type": "deliver", "x": 65, "y": 64, "item": "wood", "qty": 30}
    validate_actions(actions, "+".join(broker.roles), open_goal_count=0, observe=observe)
    # the slots are full: the goods listing takes the registration slot
    full = _observe(x=66, y=64, inventory={"berries": 4, "ore": 12})
    full["structures"] = observe["structures"]
    posted = [
        {"id": 7, "title": ledger["registration_title"], "poster": "LandBroker", "status": "open"},
        {"id": 8, "title": "Offer: 2 berries for 10 wood into the land office vault", "poster": "LandBroker", "status": "open"},
    ]
    full["your_goals"] = {"claimed": None, "posted": posted}
    b_full = board(ledger, [VAULT], [], posted, "LandBroker")
    actions2, reasons2, _ = plan_round(broker, ledger, full, b_full, public_events=[], structures=[VAULT], agents=[], state={"last_call_tick": full["tick"]}, collective_names=COLLECTIVE)
    assert [a["action"] for a in actions2][:2] == ["cancel_goal", "post_goal"] and actions2[0]["goal_id"] == 7 and actions2[1]["title"].startswith("Land office sale")
    assert any("outranks the registration slot" in r for r in reasons2)
    validate_actions(actions2, "+".join(broker.roles), open_goal_count=2, observe=full)
    # no goods in the pack but the vault beside the office holds plenty: take them to escrow the listing
    empty = _observe(x=66, y=64, inventory={"berries": 4, "wood": 2})
    empty["structures"] = observe["structures"]
    empty["your_goals"] = {"claimed": None, "posted": []}
    actions3, reasons3, _ = plan_round(broker, ledger, empty, b, public_events=[], structures=[VAULT], agents=[], state={"last_call_tick": empty["tick"]}, collective_names=COLLECTIVE)
    take = next(a for a in actions3 if a["action"] == "take")
    assert take == {"action": "take", "x": 65, "y": 64, "item": "ore", "qty": 10} and any("come into the pack" in r for r in reasons3)
    low = _observe(x=66, y=64, inventory={"berries": 4})
    low["structures"] = [{**VAULT, "storage": {"ore": 15}}]  # under min_stock: the vault keeps its reserve
    low["your_goals"] = {"claimed": None, "posted": []}
    actions4, _, _ = plan_round(broker, ledger, low, b, public_events=[], structures=[VAULT], agents=[], state={"last_call_tick": low["tick"]}, collective_names=COLLECTIVE)
    assert not any(a["action"] == "take" and a["item"] == "ore" for a in actions4)
