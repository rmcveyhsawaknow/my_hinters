"""What others build on the land office's staked lots without buying them comes down, after a notice (owner, 2026-10-25)."""

from pathlib import Path

from hglab.crew import plan_crew
from hglab.evict import (
    block_builders,
    due_owners,
    held_lots,
    intruders,
    load_shared,
    plan_notice,
    policed_lots,
    record_notice,
    save_shared,
)
from hglab.lots import lot_anchor, lot_bounds, lot_id, stake_text
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team

ROOT = Path(__file__).resolve().parents[1]
ROWS = ["g" * 128] * 128
LOT = lot_id(85, 75)
OTHER = lot_id(95, 75)
COLLECTIVE = {p.name.casefold() for p in load_personas(ROOT).values()}


def _claims():
    return dict(load_team(ROOT, "exchange").extra["pipeline"]["claims"])


def _sign(lid, text=None):
    x, y = lot_anchor(lid)
    return {"type": "sign", "x": x, "y": y, "owner": "LandBroker", "text": text or stake_text(lid, "LandBroker")}


def test_the_registry_and_the_signs_say_who_holds_a_lot():
    structures = [
        _sign(LOT, f"Lot {LOT}: held by Mara, bought from the land office at tick 9. A public record, not a wall."),
        {"type": "sign", "x": 3, "y": 3, "owner": "LandBroker", "text": "Deed B02: holder Quill, registered tick 5 by LandBroker. A public record, not a wall."},
        {"type": "sign", "x": 4, "y": 4, "owner": "Mara", "text": "Deed C03: holder Mara, made up"},  # not the registrar's sign
    ]
    held = held_lots(structures, "LandBroker", {"held": {"D04": "Cairn"}})
    assert held[LOT] == "Mara" and held["B02-SE"] == "Quill" and held["D04-NW"] == "Cairn" and "C03-NW" not in held


def test_only_unheld_staked_lots_away_from_the_spawn_and_the_factory_are_policed():
    spawn = lot_id(66, 66)
    structures = [_sign(LOT), _sign(OTHER), _sign(spawn), _sign("I09-SE")]
    policed = policed_lots(_claims(), structures, {OTHER: "Mara"})
    assert policed == {LOT}  # OTHER is bought, the spawn lot protected, I09-SE the factory's under contract


def test_intruders_are_outsiders_builds_on_policed_lots_bridges_spared():
    x0, y0, _x1, _y1 = lot_bounds(LOT)
    structures = [
        _sign(LOT),
        {"id": 5, "type": "hut", "x": x0 + 1, "y": y0 + 1, "owner": "Mara", "hp": 40},
        {"id": 6, "type": "road", "x": x0, "y": y0, "owner": "Mara", "hp": 20},
        {"id": 7, "type": "bridge", "x": x0 + 2, "y": y0, "owner": "Mara", "hp": 40},
        {"id": 8, "type": "farm", "x": x0 + 3, "y": y0 + 1, "owner": "MotherPail", "hp": 30},  # the collective's own
        {"id": 9, "type": "hut", "x": 10, "y": 10, "owner": "Quill", "hp": 40},  # on no staked lot
    ]
    found = intruders({LOT}, structures, COLLECTIVE)
    assert sorted(i["id"] for i in found) == [5, 6]
    events = [
        {"type": "place", "actor": "Cairn", "x": x0 + 2, "y": y0 + 2},
        {"type": "place", "actor": "Toffeetrowel", "x": x0 + 2, "y": y0 + 3},  # the factory's mason
        {"type": "place", "actor": "Quill", "x": 10, "y": 10},
    ]
    assert block_builders({LOT}, events, COLLECTIVE) == {"Cairn": {LOT}}


def test_the_registrar_notices_each_builder_once_with_the_price_and_the_wait():
    x0, y0, _x1, _y1 = lot_bounds(LOT)
    structures = [
        _sign(LOT), _sign(OTHER),
        {"id": 5, "type": "hut", "x": x0 + 1, "y": y0 + 1, "owner": "Mara", "hp": 40},
        {"id": 6, "type": "road", "x": x0, "y": y0, "owner": "Mara", "hp": 20},
        {"id": 7, "type": "sign", "x": lot_anchor(OTHER)[0] + 1, "y": lot_anchor(OTHER)[1], "owner": "Quill", "hp": 10},
    ]
    shared = {"notices": {}, "held": {}}
    first = plan_notice(_claims(), structures, [], COLLECTIVE, shared, prices={LOT: 23}, vault={"x": 73, "y": 72})
    whisper, owner, lots, reason = first
    assert owner == "Mara" and lots == [LOT] and whisper["action"] == "whisper" and whisper["to"] == "Mara"
    assert LOT in whisper["text"] and "23 wood" in whisper["text"] and "6 hours" in whisper["text"] and "(73,72)" in whisper["text"] and len(whisper["text"]) <= 500
    assert "notice first" in reason
    shared = record_notice(shared, owner, lots, 1000)
    second = plan_notice(_claims(), structures, [], COLLECTIVE, shared)
    assert second[1] == "Quill"  # Mara heard hers; the next builder is next
    assert due_owners(shared, 1000 + 2159, 2160) == set() and due_owners(shared, 1000 + 2160, 2160) == {"mara"}


def test_the_shared_ledger_round_trips(tmp_path):
    from hglab import evict

    data = record_notice(load_shared(tmp_path), "Mara", [LOT], 7)
    save_shared(tmp_path, data)
    assert evict.load_shared(tmp_path)["notices"]["Mara"]["tick"] == 7


def _step(slug, inventory, position, view, observe=None, energy=80, room=3):
    personas = load_personas(ROOT)
    persona = personas[slug]
    observe = observe or {"you": {"x": position[0], "y": position[1], "faction": {"id": 7, "name": "Land Office"}}, "tick": 10000}
    return plan_crew(
        persona, load_team(ROOT, "exchange"), PersonaState(mood="busy"), observe, view, dict(inventory), position, energy, persona.energy_reserve, room,
        {p.name for p in personas.values()}, {p.name: s for s, p in personas.items()}, None,
    )


def _world(extra=()):
    from hglab.planner import WorldView

    vault = {"id": 1, "type": "storehouse", "x": 73, "y": 72, "owner": "LandBroker", "policy": "private", "storage": {"wood": 10}}
    return WorldView(x0=0, y0=0, rows=[], full_map=ROWS, structures=[vault], world_structures=[vault, _sign(LOT), *extra], tick=10000)


def test_once_the_notice_ran_out_a_hand_takes_down_the_build_beside_it():
    from hglab.factory import root_of

    x0, y0, _x1, _y1 = lot_bounds(LOT)
    hut = {"id": 5, "type": "hut", "x": x0 + 1, "y": y0 + 1, "owner": "Mara", "hp": 40, "hp_max": 40}
    view = _world([hut])
    here = (x0 + 2, y0 + 2)
    assert _step("office-quarrier", {"berries": 5}, here, view) is None or all(a["action"] != "demolish" for a in _step("office-quarrier", {"berries": 5}, here, view)[0])  # no notice yet
    root = root_of(load_team(ROOT, "exchange"))
    save_shared(root, record_notice(load_shared(root), "Mara", [LOT], 10000 - 600))
    waiting = _step("office-quarrier", {"berries": 5}, here, view)
    assert waiting is None or all(a["action"] != "demolish" for a in waiting[0])  # the six hours have not run
    save_shared(root, record_notice(load_shared(root), "Mara", [LOT], 10000 - 2160))
    hits = _step("office-quarrier", {"berries": 5}, here, view)
    assert hits[0] == [{"action": "demolish", "x": x0 + 1, "y": y0 + 1}] * 3 and "notice to its builder has run out" in hits[1]  # three hits of the four a hut takes
    far = _step("office-quarrier", {"berries": 5}, (74, 73), view)
    assert far[0][0]["action"] == "move" and "Mara's hut" in far[1]
    tired = _step("office-quarrier", {"berries": 5}, here, view, energy=load_personas(ROOT)["office-quarrier"].energy_reserve + 4)
    assert tired is None or all(a["action"] != "demolish" for a in tired[0])
    bought = _world([hut, {**_sign(LOT, f"Lot {LOT}: held by Mara, bought from the land office at tick 9000.")}])
    bought.world_structures = [s for s in bought.world_structures if not (s.get("type") == "sign" and "staked by" in str(s.get("text")))]
    kept = _step("office-quarrier", {"berries": 5}, here, bought)
    assert kept is None or all(a["action"] != "demolish" for a in kept[0])  # she bought it: it stays


def test_blocks_on_a_staked_lot_are_removed_eight_at_a_time_once_noticed():
    from hglab.factory import root_of

    x0, y0, _x1, _y1 = lot_bounds(LOT)
    root = root_of(load_team(ROOT, "exchange"))
    save_shared(root, record_notice(load_shared(root), "Cairn", [LOT], 1000))
    here = (x0 + 2, y0 + 2)
    observe = {
        "you": {"x": here[0], "y": here[1], "faction": {"id": 7, "name": "Land Office"}}, "tick": 10000,
        "blocks": [{"x": x0 + 3, "y": y0 + 3, "count": 20, "top": 2, "owner": "Cairn", "closed": True}],
    }
    step = _step("office-feller", {"berries": 5}, here, _world(), observe=observe)
    box = {"action": "remove", "bx": (x0 + 3) * 4, "by": (y0 + 3) * 4, "bz": 0, "bx2": (x0 + 3) * 4 + 3, "by2": (y0 + 3) * 4 + 3, "bz2": 1}
    assert step[0] == [box, box, box] and "eight blocks each" in step[1]
    from hglab.actions import validate_actions

    validate_actions(step[0], "builder", observe=observe)
