"""The 3D viewer's ground, ported: pinned to values its own code computed, and the factory's floors level on it."""

from pathlib import Path

import pytest

from hglab import factory
from hglab.terrain3d import CELL, Ground, foundation

ROOT = Path(__file__).resolve().parents[1]
TERRAIN = "".join((ROOT / "tests/fixtures/world/terrain.txt").read_text(encoding="utf-8").split())
# tile bases computed by the viewer's own World3DScene code under Node on 2026-10-25 (scratch harness, this terrain)
VIEWER = {
    (89, 84): 4.210796899795537, (90, 85): 2.864998345375065, (96, 80): 1.3253332281112704, (98, 81): 0.2424687322974209,
    (89, 87): 1.8982705736160315, (91, 89): 0.3853268939256671, (81, 87): 3.9993860673904464, (83, 88): 2.8244416666030907,
    (93, 90): 0.27329945921897897, (97, 98): 0.3551868331432344, (64, 64): 0.5459906888008119, (10, 120): 0.04,
}


@pytest.fixture(scope="module")
def ground():
    return Ground(128, 128, TERRAIN)


def test_the_port_draws_the_ground_the_viewer_draws(ground):
    for (x, y), base in VIEWER.items():
        assert ground.tile_base(x, y) == pytest.approx(base, abs=1e-9), (x, y)


def test_the_surveyed_plinths_match_the_ground(ground):
    design = factory.load_design(ROOT, "chocolate-factory")
    for section in design["sections"]:
        x0, y0, x1, y1 = section["tiles"]
        k = foundation(ground, [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)])
        assert section["foundation"] == [[k[(x, y)] for x in range(x0, x1 + 1)] for y in range(y0, y1 + 1)], section["id"]  # re-run `hglab factory level --write` after a design change


def test_every_floor_of_the_factory_draws_within_half_a_level_of_its_plane_and_every_window_faces_out(ground):
    """The owner's report of 2026-10-25: on the hillside the floors stepped from tile to tile and two sides' windows stood across their walls."""
    design, steps, _ = factory.blueprint(ROOT, "chocolate-factory")
    for section in design["sections"]:
        sid = section["id"]
        lift = factory.foundation_map(section)
        x0, y0, x1, y1 = section["tiles"]
        plane = max(ground.tile_base(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1))
        bx0, by0, bx1, by1 = factory.cells_rect(section["tiles"])
        for step in steps:
            if step["section"] != sid or step["kind"] != "place" or "foundation" in step["name"] or "support" in step["name"]:
                continue
            action = step["action"]
            for x, y, z in factory._cells_of(action):
                tile = (x // 4, y // 4)
                drawn = ground.tile_base(*tile) + (z + 0.5) * CELL
                meant = plane + (z - lift.get(tile, 0) + 0.5) * CELL
                assert abs(drawn - meant) <= CELL / 2, (sid, step["name"], (x, y, z))
                if action.get("shape") == "window":
                    side = "north" if y == by0 else "south" if y == by1 else "west" if x == bx0 else "east" if x == bx1 else None
                    assert action.get("facing") == side, (sid, step["name"], (x, y, z))


def test_a_plinth_stands_under_every_raised_tile_before_anything_rises_there():
    design, steps, _ = factory.blueprint(ROOT, "chocolate-factory")
    mill = next(s for s in design["sections"] if s["id"] == "mill")
    lift = factory.foundation_map(mill)
    order = [s for s in steps if s["section"] == "mill"]
    plinths = [s for s in order if "foundation" in s["name"]]
    assert len(plinths) == len(lift) and all(s["action"]["bz"] == 0 for s in plinths)
    first_build = min(i for i, s in enumerate(order) if s["kind"] == "place" and "foundation" not in s["name"])
    assert max(order.index(s) for s in plinths) < first_build  # the plinth before the building
    assert all(s["supported"] for s in steps)  # hidden columns hold any piece over a lower plinth
