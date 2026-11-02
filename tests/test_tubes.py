"""The factory's wild tubes (the owner's brief of 2026-11-02): thick tubes, legs laid in a builder's reach, and the old steps untouched."""

from pathlib import Path

from hglab import factory
from hglab.factory import _tube_runs, _tube_steps, builder_sections
from hglab.persona import load_team

ROOT = Path(__file__).parents[1]
OLD_SECTIONS = {"depots", "elevator", "lookout", "mill", "terrace", "candy", "packing", "tubes-candy", "tubes-packing", "campus-north", "campus-south", "campus-east", "campus-west", "campus-gate", "river-west", "river-terrace", "river-east"}
NEW_SECTIONS = {"silo", "boiler", "mast", "tubes-spine", "tubes-fudge", "tubes-haul", "tubes-sky", "tubes-bay", "tubes-crossing"}


def test_a_long_leg_is_laid_in_runs_of_five_tiles_and_a_vertical_leg_in_one():
    cells = [(bx, 386, 9) for bx in range(371, 337, -1)]  # the long haul's westward leg: tiles 92 down to 84
    runs = _tube_runs(cells, 0)
    assert [len(r) for r in runs] == [20, 14] and all(abs(r[0][0] // 4 - r[-1][0] // 4) <= 4 for r in runs)  # each run within a builder's reach either side
    assert _tube_runs([(390, 328, z) for z in range(9, 13)], 2) == [[(390, 328, z) for z in range(9, 13)]]
    steps = _tube_steps({"name": "long", "color": "indigo", "path": [[371, 386, 9], [338, 386, 9], [338, 386, 12]]})
    assert [n for n, _ in steps] == ["tube long (indigo) leg 1 run 1", "tube long (indigo) leg 1 run 2", "tube long (indigo) leg 2"]
    assert steps[0][1]["bx"] == 352 and steps[0][1]["bx2"] == 371 and steps[1][1]["bx"] == 338 and steps[1][1]["bx2"] == 351


def test_a_thick_tube_grows_from_the_path_toward_plus_y_and_plus_z():
    fat = _tube_steps({"name": "spiral", "color": "tan", "size": 3, "path": [[373, 376, 7], [373, 379, 7]]})
    assert len(fat) == 1 and fat[0][1]["bx2"] == 375 and fat[0][1]["by2"] == 379 and fat[0][1]["bz2"] == 9 and fat[0][1]["bx"] == 373
    thin = _tube_steps({"name": "thin", "color": "red", "path": [[377, 376, 7], [377, 379, 7]]})
    assert "bx2" not in thin[0][1] and "bz2" not in thin[0][1] and thin[0][1]["by2"] == 379  # size 1 is the tube of 2026-10-27, unchanged


def test_the_expansion_leaves_every_old_step_alone_and_keeps_the_worlds_rules():
    design, steps, _index = factory.blueprint(ROOT, "chocolate-factory")
    assert sum(1 for s in steps if s["section"] in OLD_SECTIONS) == 517  # the ledger's ids still name the same boxes
    assert {s["section"] for s in steps} == OLD_SECTIONS | NEW_SECTIONS
    assert factory.check(design, steps) == []  # boxes within reach, supported in order, under the ceiling, every step adds something
    new = [s for s in steps if s["section"] in NEW_SECTIONS]
    assert all(int(s["action"]["bz"]) >= 6 for s in new if s["section"].startswith("tubes"))  # no tube closes a tile
    assert sum(int(s["cells"]) for s in new) > 1000 and factory.materials(new)["ore"] <= 12  # ore stays scarce
    assert len({str(s["action"].get("color")) for s in new}) >= 12  # wild


def test_every_hand_has_sections_of_the_expansion_to_raise():
    team = load_team(ROOT, "chocolate-factory")
    assert builder_sections(team, "loompa-woodcutter") == ["silo", "tubes-fudge"]
    assert builder_sections(team, "loompa-quarrier") == ["tubes-spine"] and builder_sections(team, "loompa-provisioner") == ["tubes-haul"] and builder_sections(team, "loompa-hauler") == ["tubes-crossing"]
    assert "mast" in builder_sections(team, "wonka") and "boiler" in builder_sections(team, "mrs-bucket")
    assert builder_sections(team, "grandpa-joe") is None  # GrandadPail builds nothing (owner, 2026-10-24)
