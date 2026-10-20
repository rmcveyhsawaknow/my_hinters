from hglab.blocks import blocks_on, cells_of, footprint, house_plan, next_step, tile_cells


def test_tiles_map_to_cells_and_footprints_stay_in_the_world():
    assert tile_cells(66, 61) == (264, 244, 267, 247)
    assert footprint(66, 61, 1) == (66, 61, 66, 61) and footprint(66, 61, 3) == (65, 60, 67, 62)
    assert footprint(0, 0, 3) == (0, 0, 2, 2) and footprint(127, 127, 3) == (126, 126, 127, 127)


def test_a_one_tile_house_is_cheap_and_its_steps_add_up():
    plan = house_plan(66, 61, 1, "yellow")
    assert [s["name"] for s in plan] == ["door", "window", "walls", "roof"]
    door, window, walls, roof = plan
    assert door["action"]["shape"] == "door" and door["action"]["facing"] == "south" and door["cells"] == 3 and door["items"] == 1
    assert window["action"]["shape"] == "window" and window["cells"] == 4 and window["item"] == "wood"
    assert walls["action"]["fill"] == "walls" and walls["cells"] == 29 and walls["items"] == 8 and walls["item"] == "stone"
    assert roof["action"]["shape"] == "slab" and roof["action"]["color"] == "yellow" and roof["cells"] == 16 and roof["items"] == 4 and roof["item"] == "fiber"
    assert [s["cumulative"] for s in plan] == [3, 7, 36, 52]
    assert next_step(plan, 0)["name"] == "door" and next_step(plan, 5)["name"] == "window" and next_step(plan, 7)["name"] == "walls" and next_step(plan, 52) is None
    for step in plan:
        act = step["action"]
        for key in ("bx", "by", "bx2", "by2"):
            if key in act:
                assert 264 <= act[key] <= 267 or 244 <= act[key] <= 247


def test_a_three_tile_house_has_two_wall_courses_and_a_wide_roof():
    plan = house_plan(66, 61, 3, "purple")
    assert [s["name"] for s in plan] == ["door", "window", "lower walls", "upper walls", "roof"]
    assert plan[-1]["cells"] == 144 and plan[-1]["items"] == 36 and plan[-1]["action"]["bz"] == 6
    assert plan[2]["items"] + plan[3]["items"] <= 66 and all(step["cells"] <= 256 for step in plan)
    assert cells_of({"bx": 0, "by": 0, "bz": 0, "bx2": 11, "by2": 11, "bz2": 2, "fill": "walls"}) == 132


def test_progress_is_read_from_the_blocks_summary():
    observe = {"blocks": [{"x": 66, "y": 61, "count": 36, "owner": "Clarion"}, {"x": 65, "y": 61, "count": 9, "owner": "Quill"}]}
    assert blocks_on(observe, "Clarion", footprint(66, 61, 1)) == 36 and blocks_on(observe, "clarion", footprint(66, 61, 3)) == 36
    assert blocks_on(observe, "Quill", footprint(66, 61, 1)) == 0
