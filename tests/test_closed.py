"""Blocks close tiles beyond the view too (2026-11-02): the office's hands walked into the factory's campus wall for a day."""

import base64
import struct
from pathlib import Path

from hglab.blocks import SHAPES, closed_tiles
from hglab.crew import plan_crew
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView, _route_step, _step_toward

ROOT = Path(__file__).parents[1]
ROWS = ["g" * 128] * 128


def _packed(blocks, owners=("Mara", "Boundstone")):
    """blocks: (bx, by, bz, shape, owner index)."""
    data = b"".join(struct.pack("<HHHBBBB", bx, by, o, bz, 1, SHAPES.index(shape), 0) for bx, by, bz, shape, o in blocks)
    return {"data": base64.b64encode(data).decode(), "owners": list(owners), "shapes": list(SHAPES), "count": len(blocks)}


def test_a_block_below_level_six_closes_its_tile_unless_it_is_a_floor_or_a_door_of_ours():
    packed = _packed([
        (4 * 10, 4 * 10, 0, "cube", 0),    # (10,10): a cube on the ground closes
        (4 * 11, 4 * 10, 0, "slab", 0),    # (11,10): a floor
        (4 * 12, 4 * 10, 0, "slope", 0),   # (12,10): a ramp
        (4 * 13, 4 * 10, 6, "cube", 0),    # (13,10): a roof at level 6 closes nothing
        (4 * 14, 4 * 10, 0, "window", 0),  # (14,10): a window on the ground closes
        (4 * 15, 4 * 10, 3, "slab", 0),    # (15,10): a slab at level 3 is in the way
        (4 * 16, 4 * 10, 0, "door", 0),    # (16,10): Mara's door
        (4 * 17, 4 * 10, 0, "cube", 1), (4 * 17 + 1, 4 * 10, 0, "door", 1),  # (17,10): Boundstone's wall with his door in it
    ])
    strangers = closed_tiles(packed)
    assert strangers == {(10, 10), (14, 10), (15, 10), (16, 10), (17, 10)}
    assert closed_tiles(packed, {"Mara"}) == {(10, 10), (14, 10), (15, 10), (17, 10)}  # her door opens its tile to her
    assert closed_tiles(packed, {"boundstone"}) == {(10, 10), (14, 10), (15, 10), (16, 10)}  # his door opens the whole tile, wall and all
    assert closed_tiles({"data": "", "owners": [], "count": 0}) == set()


def test_the_view_knows_the_worlds_closed_tiles_and_a_route_goes_round_them():
    observe = {"view": {"x0": 80, "y0": 80, "rows": ROWS[:16]}, "blocks": [{"x": 85, "y": 85, "closed": True}], "_closed_world": [[90, y] for y in range(80, 100) if y != 91]}
    view = WorldView.from_observe(observe, ROWS)
    assert (85, 85) in view.closed and (90, 90) in view.closed and (90, 91) not in view.closed
    assert not view.walkable(90, 90) and view.walkable(90, 91)
    step = _route_step((86, 86), (94, 86), view)
    assert step is not None and step not in view.closed  # the wall of 2026-11-02 is in the route's way: it goes to the gap
    sealed = WorldView.from_observe({**observe, "_closed_world": [[90, y] for y in range(60, 120)]}, ROWS)  # longer than the route's horizon: no way round
    assert _route_step((86, 86), (94, 86), sealed, horizon=10) is None
    assert _step_toward((86, 86), {"x": 94, "y": 86}, sealed) not in sealed.closed  # the greedy step never walks into a block


def test_an_office_hand_never_carries_a_load_to_a_store_on_ground_under_contract():
    personas = load_personas(ROOT)
    persona, team = personas["office-quarrier"], load_team(ROOT, "exchange")
    inside = {"id": 1, "type": "storehouse", "x": 91, "y": 83, "owner": "Lintelstave", "policy": "faction", "faction": "Land Office", "storage": {"stone": 10}}  # J08: the factory's campus
    outside = {"id": 2, "type": "storehouse", "x": 92, "y": 78, "owner": "Lintelstave", "policy": "faction", "faction": "Land Office", "storage": {"stone": 10}}
    view = WorldView(x0=70, y0=66, rows=ROWS, full_map=ROWS, structures=[inside, outside], world_structures=[inside, outside], tick=1000)
    observe = {"you": {"x": 89, "y": 76, "faction": {"id": 7, "name": "Land Office"}}, "tick": 1000}
    step = plan_crew(persona, team, PersonaState(mood="busy"), observe, view, {"wood": 45, "berries": 5}, (89, 76), 80, persona.energy_reserve, 3, {p.name for p in personas.values()}, {p.name: s for s, p in personas.items()}, None)
    assert step is not None and "(91, 83)" not in step[1] and ("(92, 78)" in step[1] or step[0][0]["action"] in ("move", "build"))
