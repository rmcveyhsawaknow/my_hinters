"""The land office walls its staked lots with the stone its full stores cannot hold (owner, 2026-10-25)."""

from pathlib import Path

from hglab.crew import plan_crew
from hglab.lots import HOLDING_TEXT, lot_anchor, lot_bounds, lot_id, stake_text
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView, _mark_full
from hglab.walls import gates, mark_no_wall, no_wall, ring, wall_lots

ROOT = Path(__file__).resolve().parents[1]
ROWS = ["g" * 128] * 128
OFFICE = {"landbroker", "lintelstave", "boundstone", "fellwright", "sheafwell", "drayhand"}
LOT = lot_id(85, 75)  # east of the vault, far from the spawn, no homestead near


def _claims(**walls):
    claims = dict(load_team(ROOT, "exchange").extra["pipeline"]["claims"])
    claims["walls"] = {**claims.get("walls", {}), **walls}
    return claims


def _sign(lid, text=None):
    x, y = lot_anchor(lid)
    return {"type": "sign", "x": x, "y": y, "owner": "LandBroker", "text": text or stake_text(lid, "LandBroker")}


def _step(slug, inventory, position, view, state=None, room=3, energy=80):
    personas = load_personas(ROOT)
    persona = personas[slug]
    observe = {"you": {"x": position[0], "y": position[1], "faction": {"id": 7, "name": "Land Office"}}, "tick": 1000}
    return plan_crew(
        persona, load_team(ROOT, "exchange"), state or PersonaState(mood="busy"), observe, view, dict(inventory), position, energy, persona.energy_reserve, room,
        {p.name for p in personas.values()}, {p.name: s for s, p in personas.items()}, None,
    )


def test_a_lot_ring_leaves_the_middle_of_every_side_open_and_neighbouring_gates_face_each_other():
    x0, y0, x1, y1 = lot_bounds(LOT)
    tiles = ring(LOT)
    assert len(tiles) == len(set(tiles)) == 16 and all(t[0] in (x0, x1) or t[1] in (y0, y1) for t in tiles)
    mx, my = (x0 + x1) // 2, (y0 + y1) // 2
    assert gates(LOT) == {(mx, y0), (mx, y1), (x0, my), (x1, my)}
    east, south = lot_id(x1 + 1, y0), lot_id(x0, y1 + 1)
    assert (x1 + 1, my) in gates(east) and (mx, y1 + 1) in gates(south)  # a straight corridor runs through any walled stretch


def test_only_the_offices_own_staked_lots_are_walled_holdings_first():
    holding, other, sold, contract, homestead = LOT, lot_id(95, 75), lot_id(100, 60), "I09-SE", lot_id(110, 40)
    spawn = lot_id(66, 66)
    structures = [
        _sign(holding), _sign(other), _sign(spawn), _sign(contract), _sign(homestead),
        _sign(sold, f"Lot {sold}: held by Mara, bought from the land office at tick 50. A public record."),
        {"type": "hut", "x": lot_anchor(homestead)[0] + 1, "y": lot_anchor(homestead)[1], "owner": "Mara"},
    ]
    held = [{"lot": holding}]
    first, rest = wall_lots(_claims(scope="staked"), held, structures, OFFICE)
    assert first == [holding] and other in rest
    assert not {sold, contract, homestead, spawn} & set(rest)  # sold, under contract (the factory), a homestead, the spawn: never walled
    assert wall_lots(_claims(scope="holdings"), held, structures, OFFICE) == ([holding], [])
    assert wall_lots(_claims(enabled=False), held, structures, OFFICE) == ([], [])


def _world(vault_storage, extra=(), nodes=()):
    vault = {"id": 1, "type": "storehouse", "x": 73, "y": 72, "owner": "LandBroker", "policy": "private", "storage": vault_storage}
    world = [vault, _sign(LOT), *extra]
    return WorldView(x0=70, y0=66, rows=ROWS, full_map=ROWS, structures=[vault, *[s for s in extra if s.get("type") == "storehouse"]], world_structures=world, world_resources=list(nodes), tick=1000)


def test_with_every_store_full_a_hand_walls_the_holding_beside_it_and_leaves_the_gate_open():
    x0, y0, _x1, _y1 = lot_bounds(LOT)
    here = (x0 - 1, y0 + 1)  # outside the west side: (x0, y0) and (x0, y0 + 1) beside, (x0, y0 + 2) is the gate
    full = _world({"stone": 500})
    step = _step("office-quarrier", {"stone": 20, "berries": 5}, here, full)
    assert step[0] == [{"action": "build", "type": "wall", "x": x0, "y": y0}, {"action": "build", "type": "wall", "x": x0, "y": y0 + 1}]
    assert "every store of the office is full" in step[1] and "gate" in step[1]
    roomy = _step("office-quarrier", {"stone": 20, "berries": 5}, here, _world({"stone": 100}))
    assert roomy is None or all(a.get("type") != "wall" for a in roomy[0])  # a store with room takes the stone: no walls
    node = _step("office-quarrier", {"stone": 20, "berries": 5}, here, _world({"stone": 500}, nodes=[{"kind": "stone", "x": x0, "y": y0, "amount": 9}]))
    assert node[0] == [{"action": "build", "type": "wall", "x": x0, "y": y0 + 1}]  # never on a node
    road = _step("office-quarrier", {"stone": 20, "berries": 5}, here, _world({"stone": 500}, extra=[{"type": "road", "x": x0, "y": y0 + 2, "owner": "Mara"}]))
    assert road[0] == [{"action": "build", "type": "wall", "x": x0, "y": y0}]  # a road stays a road, and no wall stands beside it
    bridge = _step("office-quarrier", {"stone": 20, "berries": 5}, here, _world({"stone": 500}, extra=[{"type": "bridge", "x": x0 - 1, "y": y0, "owner": "Mara"}]))
    assert bridge[0][0]["action"] == "move" and "wall ring open at" in bridge[1]  # beside another resident's bridge: no wall, on to the next tile
    far = _step("office-quarrier", {"stone": 20, "berries": 5}, (74, 73), full)
    assert far[0][0]["action"] == "move" and f"lot {LOT}" in far[1]
    tired = _step("office-quarrier", {"stone": 20, "berries": 5}, here, full, energy=load_personas(ROOT)["office-quarrier"].energy_reserve + 4)
    assert tired is None or all(a.get("type") != "wall" for a in tired[0])  # too tired for one build: rest first


def test_a_planned_wall_passes_the_persona_knob_check():
    """2026-10-25: every wall the hands planned broke the knob check (walls only inside the team's territory), and the wake was refused whole."""
    import pytest

    from hglab.persona import enforce_knobs

    x0, y0, _x1, _y1 = lot_bounds(LOT)
    here = (x0 - 1, y0 + 1)
    view = _world({"stone": 500})
    step = _step("office-quarrier", {"stone": 20, "berries": 5}, here, view)
    personas = load_personas(ROOT)
    persona, team = personas["office-quarrier"], load_team(ROOT, "exchange")
    office = {personas[m].name for m in team.members}
    observe = {"you": {"x": here[0], "y": here[1]}, "tick": 1000, "structures": list(view.world_structures)}
    enforce_knobs(step[0], persona, team, observe, member_names=office)
    gate = (x0, (y0 + lot_bounds(LOT)[3]) // 2)
    with pytest.raises(ValueError):
        enforce_knobs([{"action": "build", "type": "wall", "x": gate[0], "y": gate[1]}], persona, team, observe, member_names=office)  # a gate is never walled
    unsigned = [s for s in observe["structures"] if s.get("type") != "sign"]
    with pytest.raises(ValueError):
        enforce_knobs(step[0], persona, team, {**observe, "structures": unsigned}, member_names=office)  # no claim sign anywhere: not the office's lot
    beyond = [s for s in observe["structures"] if s.get("type") == "sign"]
    enforce_knobs(step[0], persona, team, {**observe, "structures": unsigned, "_claim_signs": beyond}, member_names=office)  # the sign beyond the view, from the public snapshot (Fellwright's walls on 2026-10-25)
    with pytest.raises(ValueError):
        enforce_knobs(step[0], persona, team, {**observe, "structures": [*observe["structures"], {"type": "road", "x": x0 - 1, "y": y0, "owner": "Clarion"}]}, member_names=office)  # beside another agent's path


def test_with_no_stone_in_the_pack_a_hand_draws_it_from_a_full_store_of_the_faction():
    depot = {"id": 2, "type": "storehouse", "x": 80, "y": 74, "owner": "Lintelstave", "policy": "faction", "faction": "Land Office", "storage": {"stone": 300, "wood": 200}}
    view = _world({"stone": 500}, extra=[depot])
    take = _step("office-feller", {"berries": 5}, (81, 74), view)
    assert take[0] == [{"action": "take", "x": 80, "y": 74, "item": "stone", "qty": 30}] and "to wall the staked lots" in take[1]


def test_a_store_marked_full_counts_full_and_a_refused_wall_tile_is_left_open_for_a_day():
    x0, y0, _x1, _y1 = lot_bounds(LOT)
    here = (x0 - 1, y0 + 1)
    state = PersonaState(mood="busy")
    _mark_full(state, (73, 72), 1000)  # the vault refused a give: full, whatever its contents showed
    marked = _step("office-quarrier", {"stone": 20, "berries": 5}, here, _world({"stone": 100}), state=state)
    assert marked[0][0] == {"action": "build", "type": "wall", "x": x0, "y": y0}
    mark_no_wall(state, (x0, y0), 1000)
    assert (x0, y0) in no_wall(state, 1000) and (x0, y0) not in no_wall(state, 1000 + 8641)
    again = _step("office-quarrier", {"stone": 20, "berries": 5}, here, _world({"stone": 100}), state=state)
    assert again[0] == [{"action": "build", "type": "wall", "x": x0, "y": y0 + 1}]


def test_the_drayman_leaves_alone_a_depot_it_may_not_take_from():
    private = {"id": 3, "type": "storehouse", "x": 73, "y": 58, "owner": "LandBroker", "policy": "private"}
    vault = {"id": 1, "type": "storehouse", "x": 73, "y": 72, "owner": "LandBroker", "policy": "private", "storage": {"wood": 10}}
    view = WorldView(x0=68, y0=52, rows=ROWS, full_map=ROWS, structures=[private], world_structures=[vault, private, _sign(LOT)], tick=1000)
    state = PersonaState(mood="busy")
    _step("office-drayman", {"berries": 6}, (73, 59), view, state=state)
    assert "73,58" in state.flags.get("empty_depots", {})  # Drayhand paced between two such depots on 2026-10-25


def test_the_holding_sign_says_the_lot_is_walled_with_a_gate():
    text = HOLDING_TEXT.format(lot="K08-NW", tags="ore, stone views, water")
    assert "Walled" in text and "gate" in text and "not a wall" not in text and len(text) <= 200
    claims_text = load_team(ROOT, "exchange").extra["pipeline"]["claims"]["text"]
    assert "not a wall" not in claims_text and "gate" in claims_text
